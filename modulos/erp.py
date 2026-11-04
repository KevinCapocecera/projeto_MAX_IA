"""Leitura do ERP Bellocopo (sistema-erp.herokuapp.com): estoque, previsões e pedidos.

O MAX entra no ERP com o login do .env e:
- baixa os mesmos arquivos Excel dos botões de download do menu
  Inventário (estoque e as quatro previsões);
- faz as buscas das telas "Consulta por Pedido" e "Consulta por
  Produto" do menu Pedidos e lê a tabela do resultado.
Só LÊ: as únicas chamadas são o login e as da lista CHAMADAS_PERMITIDAS.
Nunca usa "Atualizar previsão", "Atualizar Estoques" nem qualquer tela
que grave alguma coisa no ERP.

Configuração no .env:
    ERP_EMAIL=...          login do ERP
    ERP_SENHA=...          senha do ERP
    ERP_USUARIOS=Kevin Pereira, Outra Pessoa
                           quem pode consultar o ERP pelo MAX (os nomes
                           digitados ao entrar no site). Sem esta linha,
                           ninguém consulta pelo site. A janela do
                           max.py (uma pessoa só, neste PC) sempre pode.
    ERP_SO_NESTE_PC=1      (padrão) o ERP só responde a perguntas feitas
                           neste computador, porque usa o login de uma
                           pessoa. Com um usuário do ERP só para o MAX,
                           use 0 para liberar quem está em ERP_USUARIOS
                           em qualquer PC (cada um entra no MAX com a
                           própria senha).
    ERP_URL=...            (opcional) outro endereço do ERP

Cada relatório baixado vira uma tabela "ERP - <nome>", lida pelas mesmas
ferramentas das planilhas (consultar_aba, resumir_aba...). Os arquivos
ficam na pasta erp/ e são baixados de novo depois de VALIDADE_MINUTOS.

Nas previsões, o MAX acrescenta colunas calculadas a partir do estoque
previsto de cada dia: Estoque hoje, em 7, 15 e 30 dias, Menor estoque
previsto, Zera em e Dias até zerar. Nos produtos, traz também Segmento e
Marca do relatório de estoque.
"""

import os
import re
import threading
import time
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pandas as pd

from modulos import contas, planilhas


PASTA = Path(__file__).resolve().parent.parent / "erp"
URL_PADRAO = "https://sistema-erp.herokuapp.com"
VALIDADE_MINUTOS = 10
DIAS_PARA_PREVER = 30   # o máximo que o ERP aceita
TEMPO_LIMITE = 90       # segundos; o Heroku demora quando o ERP está "dormindo"

TIPO_EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_PREVISAO = f"?diasAnteriores=1&diasParaPrever={DIAS_PARA_PREVER}"
RELATORIOS = {
    "estoque": ("Estoque de Produtos", "/inventario/download"),
    "previsao_produtos": ("Previsão de Produtos", "/inventario/previsaoProdutos/download" + _PREVISAO),
    "previsao_insumos": ("Previsão de Insumos", "/inventario/previsaoInsumos/download" + _PREVISAO),
    "previsao_produtos_festa": ("Previsão de Produtos de Festa",
                                "/inventario/previsaoProdutosFesta/download" + _PREVISAO),
    "previsao_insumos_festa": ("Previsão de Insumos de Festa",
                               "/inventario/previsaoInsumosFesta/download" + _PREVISAO),
}

CONSULTA_PEDIDO = "/pedido/consultaPorPedido"     # campo numPedido
CONSULTA_PRODUTO = "/pedido/consultaPorProduto"   # campo codigo

# Tudo o que o MAX pode pedir ao ERP, além do login. As duas buscas usam
# POST porque o formulário do ERP é assim, mas só consultam.
CHAMADAS_PERMITIDAS = {("GET", caminho.split("?")[0]) for _, caminho in RELATORIOS.values()} | {
    ("POST", CONSULTA_PEDIDO),
    ("POST", CONSULTA_PRODUTO),
}


class ErroERP(RuntimeError):
    """Não deu para ler o ERP; a mensagem já está pronta para o usuário."""


# ============================================================
# QUEM PODE CONSULTAR
# ============================================================

def configurado():
    return bool(os.getenv("ERP_EMAIL") and os.getenv("ERP_SENHA"))


def liberado_para(nome_usuario):
    """True se esta pessoa pode consultar o ERP pelo MAX.

    nome_usuario None é a janela do max.py, de uma pessoa só neste PC.
    """
    if not configurado():
        return False
    if nome_usuario is None:
        return True
    # Compara como o nome da pasta: "Maria-José", "maria jose" e
    # "maria_jose" são a mesma pessoa.
    nomes = {contas.identificador(n) for n in os.getenv("ERP_USUARIOS", "").split(",") if n.strip()}
    return contas.identificador(nome_usuario) in nomes


def so_neste_pc():
    """True (padrão): o ERP só vale para perguntas feitas no PC que roda o MAX."""
    return os.getenv("ERP_SO_NESTE_PC", "1").strip().lower() not in ("0", "nao", "não", "false")


def motivo_sem_acesso(nome_usuario, permitido_aqui=True):
    """Por que esta pessoa não pode usar o ERP agora (None se pode).

    permitido_aqui: False quando a pergunta veio de outro PC e o ERP
    está só no PC do servidor (ERP_SO_NESTE_PC).
    """
    if not configurado():
        return "o ERP não está configurado no servidor: faltam ERP_EMAIL e ERP_SENHA no arquivo .env"
    if not liberado_para(nome_usuario):
        return f"o nome {nome_usuario} não está na lista ERP_USUARIOS do arquivo .env"
    if not permitido_aqui:
        return ("por enquanto o ERP só pode ser consultado no computador que roda o MAX "
                "(ERP_SO_NESTE_PC no arquivo .env)")
    return None


_thread = threading.local()


def usar(liberado, motivo=None):
    """Liga ou desliga o ERP para a pergunta que está sendo respondida nesta thread."""
    _thread.liberado = bool(liberado)
    _thread.motivo = motivo


def liberado_agora():
    return getattr(_thread, "liberado", False)


def motivo_agora():
    """Por que o ERP está desligado nesta pergunta (para a mensagem de erro)."""
    return getattr(_thread, "motivo", None) or "o ERP não está liberado para esta pessoa ou para este computador"


# ============================================================
# DOWNLOAD
# ============================================================

_cliente = None
_trava_rede = threading.Lock()


def _novo_cliente():
    return httpx.Client(
        base_url=os.getenv("ERP_URL", URL_PADRAO).rstrip("/"),
        follow_redirects=True,
        timeout=TEMPO_LIMITE,
        headers={"User-Agent": "MAX-PCP/1.0 (assistente interno de PCP)"},
    )


def _entrar(cliente):
    cliente.post("/login", data={
        "username": os.getenv("ERP_EMAIL", ""),
        "password": os.getenv("ERP_SENHA", ""),
    })


def _pediu_login(resposta):
    """O ERP devolveu a tela de login (sessão expirada ou senha errada)."""
    if resposta.headers.get("content-type", "").startswith(TIPO_EXCEL):
        return False
    return resposta.url.path.rstrip("/") == "/login" or 'action="/login"' in resposta.text


def _requisitar(metodo, caminho, dados=None):
    """Resposta do ERP para uma chamada permitida; entra de novo se a sessão tiver expirado."""
    global _cliente
    if (metodo, caminho.split("?")[0]) not in CHAMADAS_PERMITIDAS:
        raise ErroERP(f"O MAX não tem permissão para {metodo} {caminho} no ERP.")
    if not configurado():
        raise ErroERP("O ERP não está configurado: faltam ERP_EMAIL e ERP_SENHA no arquivo .env.")
    with _trava_rede:
        try:
            if _cliente is None:
                _cliente = _novo_cliente()
                _entrar(_cliente)
            for tentativa in (1, 2):
                resposta = _cliente.request(metodo, caminho, data=dados)
                if resposta.status_code >= 500:
                    raise ErroERP(
                        f"O ERP respondeu com erro {resposta.status_code}. Ele pode estar fora "
                        "do ar; tente de novo em alguns minutos."
                    )
                if not _pediu_login(resposta):
                    return resposta
                if tentativa == 1:   # sessão expirada: entra de novo e repete
                    _entrar(_cliente)
        except httpx.TimeoutException:
            raise ErroERP(f"O ERP demorou mais de {TEMPO_LIMITE} segundos para responder.") from None
        except httpx.HTTPError as erro:
            raise ErroERP(f"Não consegui me conectar ao ERP: {erro}") from None
    raise ErroERP(
        "Não consegui entrar no ERP com o login do .env (ERP_EMAIL e ERP_SENHA). "
        "Confira se a senha mudou."
    )


def _baixar(caminho):
    """Bytes do Excel de um download do ERP."""
    resposta = _requisitar("GET", caminho)
    if resposta.status_code != 200 or not resposta.headers.get("content-type", "").startswith(TIPO_EXCEL):
        raise ErroERP(f"O ERP não devolveu a planilha (resposta {resposta.status_code}).")
    return resposta.content


# ============================================================
# COLUNAS CALCULADAS
# ============================================================

# Colunas de número no ERP (além das de dia). Ele usa ponto decimal ("92.25"),
# e as planilhas da empresa usam o padrão brasileiro, em que "1.250" é mil
# duzentos e cinquenta; por isso o ERP é convertido já na leitura.
COLUNAS_NUMERO = {"Média 4m", "Carteira", "Pedidos", "Separado", "Quantidade"}


def _numero_do_erp(valor):
    if isinstance(valor, str) and re.fullmatch(r"-?\d+(\.\d+)?", valor.strip()):
        numero = float(valor)
        return int(numero) if numero.is_integer() else numero
    return valor


def _converter_numeros(df):
    df = df.copy()
    for coluna in df.columns:
        if coluna in COLUNAS_NUMERO or re.fullmatch(r"\d{2}/\d{2}/\d{4}", str(coluna)):
            df[coluna] = pd.Series([_numero_do_erp(v) for v in df[coluna]], index=df.index, dtype=object)
    return df


def _colunas_de_dia(df):
    """[(data, coluna)] das colunas "dd/mm/aaaa", em ordem."""
    dias = []
    for coluna in df.columns:
        try:
            dias.append((datetime.strptime(str(coluna), "%d/%m/%Y").date(), coluna))
        except ValueError:
            pass
    return sorted(dias)


def _com_colunas_calculadas(df, hoje):
    """Acrescenta, antes das colunas de dia, o resumo do estoque previsto."""
    dias = [(d, c) for d, c in _colunas_de_dia(df) if d >= hoje]
    if not dias:
        return df
    valores = pd.DataFrame({c: planilhas._numeros(df[c]) for _, c in dias}, index=df.index)

    def no_dia(n):
        alvo = [c for d, c in dias if (d - hoje).days <= n] or [dias[0][1]]
        return valores[alvo[-1]]

    zera = valores.le(0)
    primeira = zera.idxmax(axis=1).where(zera.any(axis=1))
    data_da_coluna = {c: d for d, c in dias}
    zera_em = primeira.map(lambda c: data_da_coluna.get(c) if isinstance(c, str) else None)

    calculadas = pd.DataFrame({
        "Estoque hoje": valores[dias[0][1]],
        "Estoque em 7 dias": no_dia(7),
        "Estoque em 15 dias": no_dia(15),
        "Estoque em 30 dias": no_dia(30),
        "Menor estoque previsto": valores.min(axis=1),
        "Zera em": zera_em.map(lambda d: datetime(d.year, d.month, d.day) if d else None),
        "Dias até zerar": zera_em.map(lambda d: (d - hoje).days if d else None),
    }, index=df.index).astype(object)
    calculadas = calculadas.where(calculadas.notna(), None)

    primeira_de_dia = min(list(df.columns).index(c) for _, c in _colunas_de_dia(df))
    return pd.concat(
        [df.iloc[:, :primeira_de_dia], calculadas, df.iloc[:, primeira_de_dia:]], axis=1
    )


def _com_segmento(df, estoque):
    """Traz Segmento e Marca do relatório de estoque, pelo Código."""
    if estoque is None or "Código" not in df.columns:
        return df
    base = estoque.df.drop_duplicates("Código").set_index("Código")
    extras = {c: df["Código"].map(base[c]) for c in ("Segmento", "Marca") if c in base.columns}
    if not extras:
        return df
    posicao = 2 if len(df.columns) > 2 else len(df.columns)   # depois de Código e Produto
    partes = [df.iloc[:, :posicao], pd.DataFrame(extras, index=df.index).astype(object), df.iloc[:, posicao:]]
    juntas = pd.concat(partes, axis=1)
    return juntas.where(juntas.notna(), None)


# ============================================================
# TABELAS PRONTAS
# ============================================================

_carregados = {}   # relatorio -> (momento do download, Tabela)
_trava = threading.Lock()


def _ler_tabela(relatorio, conteudo, momento):
    titulo = RELATORIOS[relatorio][0]
    PASTA.mkdir(parents=True, exist_ok=True)
    arquivo = PASTA / f"{relatorio}.xlsx"
    arquivo.write_bytes(conteudo)
    lidas = [t for t in planilhas._ler_arquivo(arquivo, nome=f"{titulo}.xlsx") if len(t.df)]
    if not lidas:
        raise ErroERP(f"O ERP mandou o relatório {titulo} vazio.")
    tabela = lidas[0]
    tabela.nome = f"ERP - {titulo}"
    tabela.arquivo = f"ERP ({momento:%d/%m %H:%M})"
    tabela.df = _converter_numeros(tabela.df)
    return tabela


def carregar(relatorio):
    """Baixa (se preciso) e devolve a Tabela do relatório. Pode levar alguns segundos."""
    if relatorio not in RELATORIOS:
        raise ErroERP(f"Relatório '{relatorio}' não existe. Use um destes: {', '.join(RELATORIOS)}.")
    with _trava:
        item = _carregados.get(relatorio)
    if item and time.time() - item[0].timestamp() < VALIDADE_MINUTOS * 60:
        return item[1]

    estoque = carregar("estoque") if relatorio in ("previsao_produtos", "previsao_produtos_festa") else None
    momento = datetime.now()
    tabela = _ler_tabela(relatorio, _baixar(RELATORIOS[relatorio][1]), momento)
    if relatorio.startswith("previsao"):
        df = _com_colunas_calculadas(tabela.df, momento.date())
        tabela.df = _com_segmento(df, estoque).reset_index(drop=True)
    with _trava:
        _carregados[relatorio] = (momento, tabela)
    return tabela


def tabelas_carregadas():
    """Tabelas do ERP já baixadas (sem baixar nada). Usada por planilhas.tabelas()."""
    if not liberado_agora():
        return []
    with _trava:
        return [tabela for _, tabela in _carregados.values()]


# ============================================================
# PEDIDOS (telas Consulta por Pedido e Consulta por Produto)
# ============================================================
# O ERP devolve uma página com uma tabela (cabeçalho, linhas e, no fim, o
# total). "Produtos do Pedido X" ocupa duas colunas: código e nome.

class _LeitorTabelas(HTMLParser):
    """Tabelas do HTML em texto: cabeçalho [(texto, colspan)], linhas e rodapé."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tabelas = []
        self._secao = None
        self._linha = None
        self._celula = None
        self._colspan = 1

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tabelas.append({"cabecalho": [], "linhas": [], "rodape": []})
        elif not self.tabelas:
            return
        elif tag in ("thead", "tbody", "tfoot"):
            self._secao = tag
        elif tag == "tr":
            self._linha = []
        elif tag in ("td", "th") and self._linha is not None:
            self._celula = []
            try:
                self._colspan = max(1, int(dict(attrs).get("colspan") or 1))
            except ValueError:
                self._colspan = 1

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._celula is not None:
            self._linha.append((re.sub(r"\s+", " ", "".join(self._celula)).strip(), self._colspan))
            self._celula = None
        elif tag == "tr" and self._linha is not None and self.tabelas:
            tabela = self.tabelas[-1]
            if self._secao == "thead":
                tabela["cabecalho"] = self._linha
            elif self._secao == "tfoot":
                tabela["rodape"] = [texto for texto, _ in self._linha]
            else:
                tabela["linhas"].append([texto for texto, _ in self._linha])
            self._linha = None
        elif tag in ("thead", "tbody", "tfoot"):
            self._secao = None

    def handle_data(self, dados):
        if self._celula is not None:
            self._celula.append(dados)


def _tabela_do_resultado(html):
    leitor = _LeitorTabelas()
    leitor.feed(html)
    leitor.close()
    return next((t for t in leitor.tabelas if t["cabecalho"]), None)


def _colunas(cabecalho):
    nomes = []
    for texto, colspan in cabecalho:
        if texto.startswith("Produtos do Pedido") and colspan == 2:
            nomes += ["Código", "Produto"]
        elif texto.startswith("Pedidos do Produto"):
            nomes += ["Pedido"] + [f"Pedido ({i})" for i in range(2, colspan + 1)]
        else:
            nomes += [texto] + [f"{texto} ({i})" for i in range(2, colspan + 1)]
    return nomes


def _numero_da_tela(texto):
    """Quantidades e estoques da tela: inteiros, às vezes com ponto de milhar."""
    t = texto.strip()
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        return int(t.replace(".", ""))
    if re.fullmatch(r"-?\d+,\d+", t):
        return float(t.replace(",", "."))
    return texto


def _linhas_da_tabela(tabela):
    if tabela is None:
        return []
    colunas = _colunas(tabela["cabecalho"])
    linhas = []
    for celulas in tabela["linhas"]:
        if celulas and celulas[0].strip().lower() == "total":
            continue
        item = {}
        for nome, valor in zip(colunas, celulas):
            if nome == "#" or valor == "":
                continue
            item[nome] = _numero_da_tela(valor) if re.search("Quantidade|Estoque", nome) else valor
        if item:
            linhas.append(item)
    return linhas


def consultar_pedido(numero):
    """Itens de um pedido (tela Consulta por Pedido)."""
    numero = re.sub(r"\s+", "", str(numero or ""))
    if not numero:
        raise ErroERP("Informe o número do pedido.")
    # O ERP usa 8 dígitos ("00130101"); quem pergunta costuma dizer "130101".
    tentativas = [numero]
    if numero.isdigit() and len(numero) < 8:
        tentativas.insert(0, numero.zfill(8))
    for tentativa in tentativas:
        resposta = _requisitar("POST", CONSULTA_PEDIDO, {"numPedido": tentativa})
        itens = _linhas_da_tabela(_tabela_do_resultado(resposta.text))
        if itens:
            return {
                "pedido": tentativa,
                "quantidade_de_itens": len(itens),
                "itens": itens[:100],
                "consultado": f"{datetime.now():%d/%m %H:%M}",
            }
    return {"pedido": numero, "itens": [], "aviso": "O ERP não encontrou itens com esse número de pedido."}


def consultar_produto(codigo):
    """Pedidos de um produto (tela Consulta por Produto), com totais por status."""
    codigo = str(codigo or "").strip().upper()
    if not codigo:
        raise ErroERP("Informe o código do produto.")
    resposta = _requisitar("POST", CONSULTA_PRODUTO, {"codigo": codigo})
    pedidos = _linhas_da_tabela(_tabela_do_resultado(resposta.text))
    if not pedidos:
        return {"produto": codigo, "pedidos": [], "aviso": (
            "O ERP não encontrou pedidos para esse código. Confira o código do produto."
        )}

    por_status = {}
    for pedido in pedidos:
        status = por_status.setdefault(pedido.get("Status") or "(sem status)", {"pedidos": 0, "quantidade": 0})
        status["pedidos"] += 1
        if isinstance(pedido.get("Quantidade"), (int, float)):
            status["quantidade"] += pedido["Quantidade"]
    resultado = {
        "produto": codigo,
        "quantidade_de_pedidos": len(pedidos),
        "quantidade_total": sum(s["quantidade"] for s in por_status.values()),
        "por_status": por_status,
        "pedidos": pedidos[:100],
        "consultado": f"{datetime.now():%d/%m %H:%M}",
    }
    if len(pedidos) > 100:
        resultado["aviso"] = "Mostrando só os 100 primeiros pedidos; os totais contam todos."
    return resultado
