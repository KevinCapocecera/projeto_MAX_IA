"""MAX na rede da empresa: abre pelo navegador, em qualquer computador.

O seu PC roda este arquivo e os outros acessam pelo endereço que
aparece na tela, por exemplo http://nome-do-pc:8000.

Cada pessoa entra com o próprio nome e tem histórico e memória
separados, na pasta usuarios/<nome>. A chave do Gemini e a planilha
ficam só no servidor; quem acessa nunca vê a chave. As planilhas que
cada pessoa anexa pelo chat ficam em usuarios/<nome>/anexos e só ela vê.

Para rodar:
    .venv/Scripts/python servidor.py
Em outra porta:
    .venv/Scripts/python servidor.py --porta 8080
"""

import argparse
import os
import re
import socket
import sys
import threading
import unicodedata
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from modulos import ferramentas_pcp, planilhas
from modulos.nucleo import Max


PASTA = Path(__file__).resolve().parent
PAGINA = PASTA / "interface" / "index.html"
PASTA_USUARIOS = PASTA / "usuarios"
PASTA_RELATORIOS = PASTA / "relatorios"

LIMITE_MENSAGEM = 4000  # caracteres por pergunta
LIMITE_ANEXO_MB = 30    # tamanho máximo de uma planilha anexada

# Quantas perguntas o MAX responde ao mesmo tempo. Cada uma fica presa
# esperando o Gemini (alguns segundos), por isso o limite é separado das
# chamadas rápidas da página (LED, quadro, histórico), que ganham
# VAGAS_RAPIDAS linhas de atendimento só para elas e nunca ficam na fila.
# Mude no .env com MAX_SIMULTANEAS=50, ou com --simultaneas 50.
SIMULTANEAS_PADRAO = 32
VAGAS_RAPIDAS = 8
ESPERA_NA_FILA = 90  # segundos que uma pergunta espera por uma vaga


def _simultaneas_do_env():
    try:
        return max(1, int(os.getenv("MAX_SIMULTANEAS", SIMULTANEAS_PADRAO)))
    except ValueError:
        return SIMULTANEAS_PADRAO


_vagas = threading.BoundedSemaphore(_simultaneas_do_env())

# Fila: perguntas que chegam com todas as vagas ocupadas esperam aqui. Cada
# uma também prende uma linha de atendimento, então a fila tem tamanho
# máximo (igual ao número de vagas) e linhas próprias, separadas das
# VAGAS_RAPIDAS. Com a fila cheia, a resposta é imediata ("tente de novo").
_fila_maxima = _simultaneas_do_env()
_na_fila = 0
_trava_fila = threading.Lock()


def _ocupar_vaga():
    """Pega uma vaga para responder; espera na fila se precisar."""
    global _na_fila
    if _vagas.acquire(blocking=False):
        return True
    with _trava_fila:
        if _na_fila >= _fila_maxima:
            return False
        _na_fila += 1
    try:
        return _vagas.acquire(timeout=ESPERA_NA_FILA)
    finally:
        with _trava_fila:
            _na_fila -= 1

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = LIMITE_ANEXO_MB * 1024 * 1024


# ============================================================
# USUÁRIOS
# ============================================================
# Sem senha: o nome só serve para separar o histórico de cada pessoa.
# Cada nome ganha um Max próprio, criado na primeira pergunta e
# guardado enquanto o servidor estiver ligado.

_assistentes = {}
_estados = {}
_trava = threading.Lock()


def _identificador(nome):
    """'João da Silva' -> 'joao_da_silva' (nome da pasta da pessoa)."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", nome)
        if unicodedata.category(c) != "Mn"
    )
    ident = re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")
    return ident[:40]


def _usuario():
    """Lê o nome enviado pela página (cabeçalho X-Usuario)."""
    nome = unquote(request.headers.get("X-Usuario", "")).strip()
    nome = re.sub(r"\s+", " ", nome)[:60]
    ident = _identificador(nome)
    if not ident:
        abort(401, description="Informe seu nome para usar o MAX.")
    return nome, ident


def _assistente(nome, ident):
    with _trava:
        max_ = _assistentes.get(ident)
        if max_ is None:
            max_ = Max(
                pasta=PASTA_USUARIOS / ident,
                nome_usuario=nome,
                modo_web=True,
            )
            max_.ao_mudar_estado = lambda estado: _estados.__setitem__(ident, estado)
            _assistentes[ident] = max_
        return max_


@app.errorhandler(400)
@app.errorhandler(401)
@app.errorhandler(404)
@app.errorhandler(500)
def _erro(erro):
    return jsonify({"erro": getattr(erro, "description", str(erro))}), getattr(erro, "code", 500)


@app.errorhandler(413)
def _grande_demais(erro):
    return jsonify({"erro": f"A planilha passou de {LIMITE_ANEXO_MB} MB."}), 413


# ============================================================
# PÁGINA
# ============================================================

@app.get("/")
def pagina():
    # Avisa a página que ela está no servidor (sai do modo demonstração).
    html = PAGINA.read_text(encoding="utf-8").replace(
        "</head>", "<script>window.MAX_SERVIDOR = true;</script>\n</head>", 1
    )
    return Response(html, mimetype="text/html")


ICONES = {"icone.svg", "icone.ico", "icone-180.png"}


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(PAGINA.parent, "icone.ico", max_age=86400)


@app.get("/icones/<nome>")
def icone(nome):
    if nome not in ICONES:
        abort(404, description="Arquivo não encontrado.")
    return send_from_directory(PAGINA.parent, nome, max_age=86400)


# ============================================================
# API USADA PELA PÁGINA
# ============================================================

@app.post("/api/perguntar")
def perguntar():
    nome, ident = _usuario()
    dados = request.get_json(silent=True) or {}
    texto = str(dados.get("texto", "")).strip()
    if not texto:
        abort(400, description="Digite uma mensagem.")
    if len(texto) > LIMITE_MENSAGEM:
        abort(400, description=f"A mensagem passou de {LIMITE_MENSAGEM} caracteres.")

    max_ = _assistente(nome, ident)
    _estados[ident] = "pensando"
    if not _ocupar_vaga():
        _estados.pop(ident, None)
        print(f"[MAX] Fila cheia: {nome} não conseguiu vaga.", flush=True)
        return jsonify({"erro": (
            "O MAX está respondendo muitas perguntas ao mesmo tempo. "
            "Tente de novo em alguns segundos."
        )}), 503
    ferramentas_pcp.comecar_registro_exportacoes()
    try:
        resposta = max_.responder(texto)
    except Exception as erro:
        print(f"[MAX] Erro para {nome}: {erro!r}", flush=True)
        return jsonify({"erro": str(erro)}), 500
    finally:
        _vagas.release()
        _estados.pop(ident, None)

    arquivos = [
        {"nome": arquivo, "url": f"/relatorios/{arquivo}"}
        for arquivo in ferramentas_pcp.exportacoes_registradas()
    ]
    return jsonify({"texto": resposta, "arquivos": arquivos})


@app.get("/api/estado")
def estado():
    _, ident = _usuario()
    return jsonify({"estado": _estados.get(ident)})


@app.get("/api/historico")
def historico():
    nome, ident = _usuario()
    max_ = _assistente(nome, ident)
    return jsonify({"mensagens": max_.historico[-30:]})


@app.get("/api/painel")
def painel():
    try:
        return jsonify(ferramentas_pcp.painel())
    except Exception as erro:
        return jsonify({"erro": str(erro)}), 500


# ============================================================
# PLANILHAS ANEXADAS PELO CHAT
# ============================================================

def _pasta_anexos(ident):
    return PASTA_USUARIOS / ident / "anexos"


def _lista_de_anexos(ident):
    return [p.name for p in planilhas.arquivos_anexos(_pasta_anexos(ident))]


def _resumo_do_anexo(nome_arquivo, tabelas):
    """Texto que o MAX mostra ao receber a planilha (sem gastar o Gemini)."""
    prefixo = os.path.splitext(nome_arquivo)[0] + " - "   # "Estoque - Planilha1" -> "Planilha1"
    partes = []
    for t in tabelas[:8]:
        aba = t.nome[len(prefixo):] if t.nome.startswith(prefixo) else t.nome
        colunas = ", ".join(str(c) for c in t.df.columns[:8])
        if len(t.df.columns) > 8:
            colunas += f" e mais {len(t.df.columns) - 8}"
        linhas = "1 linha" if len(t.df) == 1 else f"{len(t.df)} linhas"
        partes.append(f"{aba}: {linhas}, colunas {colunas}")
    if len(tabelas) > 8:
        partes.append(f"e mais {len(tabelas) - 8} abas")
    abas = "1 aba" if len(tabelas) == 1 else f"{len(tabelas)} abas"
    return (
        f"Recebi a planilha {nome_arquivo}, com {abas}.\n"
        + "\n".join(partes)
        + "\nO que você quer saber dela? Posso fazer uma análise geral, "
        "somar, contar, achar os maiores e menores ou exportar uma parte."
    )


@app.get("/api/anexos")
def anexos():
    _, ident = _usuario()
    return jsonify({"anexos": _lista_de_anexos(ident)})


@app.post("/api/anexos")
def anexar():
    nome, ident = _usuario()
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        abort(400, description="Escolha uma planilha para anexar.")
    nome_arquivo = planilhas.nome_do_anexo(arquivo.filename)
    extensao = os.path.splitext(nome_arquivo)[1]
    if extensao == ".xls":
        abort(400, description=(
            "Arquivos .xls (Excel antigo) ainda não são lidos. Abra no Excel e "
            "salve como .xlsx (Arquivo > Salvar como > Pasta de Trabalho do Excel)."
        ))
    if extensao not in planilhas.EXTENSOES_ANEXO or len(nome_arquivo) <= len(extensao):
        abort(400, description="Anexe uma planilha .xlsx, .xlsm ou .csv.")

    pasta = _pasta_anexos(ident)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome_arquivo
    temporario = pasta / f"~enviando_{threading.get_ident()}{extensao}"
    arquivo.save(temporario)
    try:
        tabelas = planilhas.receber_anexo(temporario, destino)
    except Exception as erro:
        print(f"[MAX] Anexo de {nome} recusado ({nome_arquivo}): {erro!r}", flush=True)
        abort(400, description=f"Não consegui ler a planilha {nome_arquivo}: {erro}")

    print(f"[MAX] {nome} anexou {nome_arquivo}.", flush=True)
    texto = _resumo_do_anexo(nome_arquivo, tabelas)
    _assistente(nome, ident).registrar_anexo(f"Anexei a planilha {nome_arquivo}.", texto)
    return jsonify({"texto": texto, "anexos": _lista_de_anexos(ident)})


@app.post("/api/anexos/remover")
def remover_anexo():
    _, ident = _usuario()
    nome_arquivo = str((request.get_json(silent=True) or {}).get("nome", ""))
    caminho = next(
        (p for p in planilhas.arquivos_anexos(_pasta_anexos(ident)) if p.name == nome_arquivo),
        None,
    )
    if caminho is None:
        abort(404, description="Essa planilha não está mais anexada.")
    planilhas.esquecer(caminho)
    caminho.unlink()
    return jsonify({"anexos": _lista_de_anexos(ident)})


@app.get("/relatorios/<path:arquivo>")
def baixar(arquivo):
    if not re.fullmatch(r"(Plano_Acao_PCP|Consulta|Resumo)[\w\-]*\.xlsx", arquivo):
        abort(404, description="Arquivo não encontrado.")
    return send_from_directory(PASTA_RELATORIOS, arquivo, as_attachment=True)


# ============================================================
# INÍCIO
# ============================================================

def _ip_na_rede():
    """IP deste computador na rede local (para mostrar o endereço)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def _manter_acordado():
    """Impede o Windows de suspender enquanto o MAX estiver ligado.

    Vale só enquanto esta janela estiver aberta; a tela ainda pode
    apagar. Fechar a tampa do notebook ainda suspende (isso se muda nas
    opções de energia do Windows). Em outros sistemas não faz nada.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    ))


def main():
    parser = argparse.ArgumentParser(description="MAX na rede da empresa")
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("--simultaneas", "--threads", type=int, default=_simultaneas_do_env(),
                        help="quantas perguntas podem ser respondidas ao mesmo tempo "
                             f"(padrão: MAX_SIMULTANEAS do .env ou {SIMULTANEAS_PADRAO})")
    args = parser.parse_args()

    global _vagas, _fila_maxima
    simultaneas = max(1, args.simultaneas)
    _vagas = threading.BoundedSemaphore(simultaneas)
    _fila_maxima = simultaneas
    linhas = simultaneas + _fila_maxima + VAGAS_RAPIDAS

    if not PAGINA.exists():
        raise SystemExit(f"Não encontrei a interface em {PAGINA}.")
    if not os.getenv("GEMINI_API_KEY"):
        print("[MAX] Aviso: não encontrei GEMINI_API_KEY no arquivo .env.")

    nome_pc = socket.gethostname().lower()
    print("\nMAX no ar. Para acessar:")
    print(f"  Neste computador:   http://localhost:{args.porta}")
    print(f"  Nos outros da rede: http://{nome_pc}:{args.porta}")
    print(f"           ou então:  http://{_ip_na_rede()}:{args.porta}")
    print("  (o endereço com o nome do PC continua valendo se o IP mudar)")
    if _manter_acordado():
        print("O computador não vai suspender enquanto esta janela estiver aberta.")
    print(f"Até {simultaneas} perguntas ao mesmo tempo (mude com MAX_SIMULTANEAS no .env).")
    print("Para desligar, feche esta janela ou aperte Ctrl+C.\n", flush=True)

    from waitress import serve
    serve(
        app,
        host="0.0.0.0",
        port=args.porta,
        threads=linhas,
        connection_limit=max(100, linhas * 4),
    )


if __name__ == "__main__":
    main()
