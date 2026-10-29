"""MAX na rede da empresa: abre pelo navegador, em qualquer computador.

Um computador (o servidor) roda este arquivo e os outros acessam pelo
endereço que aparece na tela, por exemplo http://192.168.0.50:8000.

Cada pessoa entra com o próprio nome e tem histórico e memória
separados, na pasta usuarios/<nome>. A chave do Gemini e a planilha
ficam só no servidor; quem acessa nunca vê a chave.

Para rodar:
    .venv/Scripts/python servidor.py
Em outra porta:
    .venv/Scripts/python servidor.py --porta 8080
"""

import argparse
import os
import re
import socket
import threading
import unicodedata
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, Response, abort, jsonify, request, send_from_directory

from modulos import ferramentas_pcp
from modulos.nucleo import Max


PASTA = Path(__file__).resolve().parent
PAGINA = PASTA / "interface" / "index.html"
PASTA_USUARIOS = PASTA / "usuarios"
PASTA_RELATORIOS = PASTA / "relatorios"

LIMITE_MENSAGEM = 4000  # caracteres por pergunta

app = Flask(__name__)


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
    ferramentas_pcp.comecar_registro_exportacoes()
    try:
        resposta = max_.responder(texto)
    except Exception as erro:
        print(f"[MAX] Erro para {nome}: {erro!r}", flush=True)
        return jsonify({"erro": str(erro)}), 500
    finally:
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


@app.get("/relatorios/<path:arquivo>")
def baixar(arquivo):
    if not re.fullmatch(r"Plano_Acao_PCP[\w\-]*\.xlsx", arquivo):
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


def main():
    parser = argparse.ArgumentParser(description="MAX na rede da empresa")
    parser.add_argument("--porta", type=int, default=8000)
    parser.add_argument("--threads", type=int, default=8,
                        help="quantas perguntas podem ser respondidas ao mesmo tempo")
    args = parser.parse_args()

    if not PAGINA.exists():
        raise SystemExit(f"Não encontrei a interface em {PAGINA}.")
    if not os.getenv("GEMINI_API_KEY"):
        print("[MAX] Aviso: não encontrei GEMINI_API_KEY no arquivo .env.")

    print("\nMAX no ar. Para acessar:")
    print(f"  Neste computador:   http://localhost:{args.porta}")
    print(f"  Nos outros da rede: http://{_ip_na_rede()}:{args.porta}")
    print("Para desligar, feche esta janela ou aperte Ctrl+C.\n", flush=True)

    from waitress import serve
    serve(app, host="0.0.0.0", port=args.porta, threads=args.threads)


if __name__ == "__main__":
    main()
