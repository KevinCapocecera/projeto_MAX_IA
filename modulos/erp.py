"""Estoque e previsões (pelo BelloPortal) e pedidos (pelo ERP Bellocopo).

Estoque e as quatro previsões vêm do portal (modulos/portal.py), das
telas Previsão de Produtos e Previsão de Insumos, nos Tipos Descartáveis
e Festa. O estoque atual é o saldo de fim do dia de ONTEM na Previsão de
Produtos, juntando os dois Tipos (um item está em um Tipo só).

Os pedidos ainda vêm do ERP (sistema-erp.herokuapp.com), enquanto o
portal não tem essas telas: a MAX entra no ERP com o login do .env e faz
as buscas das telas "Consulta por Pedido" e "Consulta por Produto" do
menu Pedidos, lendo a tabela do resultado.
Só LÊ: no ERP, as únicas chamadas são o login e as da lista
CHAMADAS_PERMITIDAS. Nunca grava nada no ERP nem no portal.

Configuração no .env:
    PORTAL_USUARIO=...     usuário de serviço do portal (estoque e previsões)
    PORTAL_SENHA=...       senha dele
    ERP_EMAIL=...          login do ERP (pedidos)
    ERP_SENHA=...          senha do ERP
    ERP_USUARIOS=Kevin Pereira, Outra Pessoa
                           quem pode consultar o ERP pela MAX (os nomes
                           digitados ao entrar no site). Sem esta linha,
                           ninguém consulta pelo site. A janela do
                           max.py (uma pessoa só, neste PC) sempre pode.
    ERP_SO_NESTE_PC=1      (padrão) o ERP só responde a perguntas feitas
                           neste computador, porque usa o login de uma
                           pessoa. Com um usuário do ERP só para a MAX,
                           use 0 para liberar quem está em ERP_USUARIOS
                           em qualquer PC (cada um entra na MAX com a
                           própria senha).
    ERP_URL=...            (opcional) outro endereço do ERP

Cada relatório vira uma tabela "Portal - <nome>", lida pelas mesmas
ferramentas das planilhas (consultar_aba, resumir_aba...), e é lido de
novo depois de portal.VALIDADE_MINUTOS.

Nas previsões, a MAX acrescenta colunas calculadas a partir do estoque
previsto de cada dia: Estoque atual (fim de ontem), Previsto hoje, em 7,
15 e 30 dias, Menor estoque previsto, Zera em e Dias até zerar.
"""

import os
import re
import threading
import time
from datetime import datetime
from html.parser import HTMLParser

import httpx
import pandas as pd

from modulos import contas, planilhas, portal


URL_PADRAO = "https://sistema-erp.herokuapp.com"
TEMPO_LIMITE = 90       # segundos; o Heroku demora quando o ERP está "dormindo"

# relatorio -> (título, tela do portal, festa). O estoque junta a
# Previsão de Produtos dos dois Tipos e fica só com a coluna de ontem.
RELATORIOS = {
    "estoque": ("Estoque de Produtos", "produtos", None),
    "previsao_produtos": ("Previsão de Produtos (Descartáveis)", "produtos", False),
    "previsao_insumos": ("Previsão de Insumos (Descartáveis)", "insumos", False),
    "previsao_produtos_festa": ("Previsão de Produtos (Festa)", "produtos", True),
    "previsao_insumos_festa": ("Previsão de Insumos (Festa)", "insumos", True),
}

CONSULTA_PEDIDO = "/pedido/consultaPorPedido"     # campo numPedido
CONSULTA_PRODUTO = "/pedido/consultaPorProduto"   # campo codigo

# Tudo o que a MAX pode pedir ao ERP, além do login. As duas buscas usam
# POST porque o formulário do ERP é assim, mas só consultam.
CHAMADAS_PERMITIDAS = {
    ("POST", CONSULTA_PEDIDO),
    ("POST", CONSULTA_PRODUTO),
}


class ErroERP(RuntimeError):
    """Não deu para ler o ERP ou o portal; a mensagem já está pronta para o usuário."""


# ============================================================
# QUEM PODE CONSULTAR
# ============================================================

def erp_configurado():
    """Login do ERP no .env (só para as consultas de pedidos)."""
    return bool(os.getenv("ERP_EMAIL") and os.getenv("ERP_SENHA"))


def configurado():
    """Há pelo menos uma fonte ligada: o portal (estoque e previsões) ou o ERP (pedidos)."""
    return portal.configurado() or erp_configurado()


def liberado_para(nome_usuario):
    """True se esta pessoa pode consultar o ERP pela MAX.

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
    """True (padrão): o ERP só vale para perguntas feitas no PC que roda a MAX."""
    return os.getenv("ERP_SO_NESTE_PC", "1").strip().lower() not in ("0", "nao", "não", "false")


def motivo_sem_acesso(nome_usuario, permitido_aqui=True):
    """Por que esta pessoa não pode usar o ERP agora (None se pode).

    permitido_aqui: False quando a pergunta veio de outro PC e o ERP
    está só no PC do servidor (ERP_SO_NESTE_PC).
    """
    if not configurado():
        return ("o portal e o ERP não estão configurados no servidor: faltam PORTAL_USUARIO e "
                "PORTAL_SENHA (ou ERP_EMAIL e ERP_SENHA) no arquivo .env")
    if not liberado_para(nome_usuario):
        return f"o nome {nome_usuario} não está na lista ERP_USUARIOS do arquivo .env"
    if not permitido_aqui:
        return ("por enquanto o ERP só pode ser consultado no computador que roda a MAX "
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
# CONEXÃO COM O ERP (só pedidos)
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
    return resposta.url.path.rstrip("/") == "/login" or 'action="/login"' in resposta.text


def _requisitar(metodo, caminho, dados=None):
    """Resposta do ERP para uma chamada permitida; entra de novo se a sessão tiver expirado."""
    global _cliente
    if (metodo, caminho.split("?")[0]) not in CHAMADAS_PERMITIDAS:
        raise ErroERP(f"A MAX não tem permissão para {metodo} {caminho} no ERP.")
    if not erp_configurado():
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


# ============================================================
# COLUNAS CALCULADAS
# ============================================================

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
    todos = _colunas_de_dia(df)
    dias = [(d, c) for d, c in todos if d >= hoje]
    if not dias:
        return df
    valores = pd.DataFrame({c: planilhas._numeros(df[c]) for _, c in dias}, index=df.index)
    de_ontem = [c for d, c in todos if d == portal.ontem(hoje)]

    def no_dia(n):
        alvo = [c for d, c in dias if (d - hoje).days <= n] or [dias[0][1]]
        return valores[alvo[-1]]

    zera = valores.le(0)
    primeira = zera.idxmax(axis=1).where(zera.any(axis=1))
    data_da_coluna = {c: d for d, c in dias}
    zera_em = primeira.map(lambda c: data_da_coluna.get(c) if isinstance(c, str) else None)

    calculadas = {}
    if de_ontem:
        calculadas["Estoque atual"] = planilhas._numeros(df[de_ontem[0]])
    calculadas.update({
        "Previsto hoje": valores[dias[0][1]],
        "Estoque em 7 dias": no_dia(7),
        "Estoque em 15 dias": no_dia(15),
        "Estoque em 30 dias": no_dia(30),
        "Menor estoque previsto": valores.min(axis=1),
        "Zera em": zera_em.map(lambda d: datetime(d.year, d.month, d.day) if d else None),
        "Dias até zerar": zera_em.map(lambda d: (d - hoje).days if d else None),
    })
    calculadas = pd.DataFrame(calculadas, index=df.index).astype(object)
    calculadas = calculadas.where(calculadas.notna(), None)

    primeira_de_dia = min(list(df.columns).index(c) for _, c in todos)
    return pd.concat(
        [df.iloc[:, :primeira_de_dia], calculadas, df.iloc[:, primeira_de_dia:]], axis=1
    )


# ============================================================
# TABELAS PRONTAS (montadas com os dados do portal)
# ============================================================

_carregados = {}   # relatorio -> (momento da leitura, Tabela)
_trava = threading.Lock()


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def _df_previsao(dados, tela, festa):
    """DataFrame de uma previsão do portal, com as colunas que a MAX conhece."""
    datas = [portal.data_da_coluna(d) for d in dados["datas"]]
    nomes_dias = [f"{d:%d/%m/%Y}" for d in datas]
    linhas = []
    for item in dados["itens"]:
        linha = {
            "Código": _texto(item.get("codigo")),
            "Produto": _texto(item.get("nome")),
            "Tipo": portal.TIPOS[bool(festa)],
            "Segmento": _texto(item.get("segmento")),
            "Categoria": _texto(item.get("categoria")),
            "Linha": _texto(item.get("linha")),
            "Unidade": _texto(item.get("unidade")),
            "Média 4m": item.get("media4m"),
            "Carteira": item.get("carteira"),
        }
        if tela == "produtos":   # a tela de insumos não mostra estas duas
            linha["Pedidos"] = item.get("numPedidos")
            linha["Separado"] = item.get("separado")
        quantidades = item.get("quantidade") or []
        for i, coluna in enumerate(nomes_dias):
            linha[coluna] = quantidades[i] if i < len(quantidades) else None
        linhas.append(linha)
    return pd.DataFrame(linhas).astype(object)


def _origem(momento, dados_lidos):
    """Texto do campo "baixado": quando a MAX leu e quando o portal calculou o estoque."""
    texto = f"Portal (lido {momento:%d/%m %H:%M}"
    calculos = [c for c in (portal.estoque_inicial_calculado_em(d) for d in dados_lidos) if c]
    if calculos:
        texto += f"; estoque inicial calculado {min(calculos):%d/%m %H:%M}"
    return texto + ")"


def _montar_previsao(relatorio):
    titulo, tela, festa = RELATORIOS[relatorio]
    dados = portal.previsao(tela, festa)
    momento = dados["momento"]
    df = _com_colunas_calculadas(_df_previsao(dados, tela, festa), momento.date())
    return planilhas.Tabela(
        nome=f"Portal - {titulo}", arquivo=_origem(momento, [dados]), oculta=False,
        df=df.reset_index(drop=True),
    )


def _montar_estoque():
    """Estoque atual: fim do dia de ontem na Previsão de Produtos, Descartáveis e depois Festa."""
    partes, lidos = [], []
    for festa in (False, True):
        dados = portal.previsao("produtos", festa)
        lidos.append(dados)
        df = _df_previsao(dados, "produtos", festa)
        coluna = f"{portal.ontem(dados['momento'].date()):%d/%m/%Y}"
        if coluna not in df.columns:
            raise ErroERP(f"O portal não mandou a coluna de ontem ({coluna}) na Previsão de Produtos.")
        partes.append(pd.DataFrame({
            "Código": df["Código"],
            "Nome": df["Produto"],
            "Tipo": df["Tipo"],
            "Segmento": df["Segmento"],
            "Categoria": df["Categoria"],
            "Linha": df["Linha"],
            "Unidade": df["Unidade"],
            "Quantidade": df[coluna],
        }))
    momento = min(d["momento"] for d in lidos)
    return planilhas.Tabela(
        nome=f"Portal - {RELATORIOS['estoque'][0]}", arquivo=_origem(momento, lidos), oculta=False,
        df=pd.concat(partes, ignore_index=True).astype(object),
    )


def carregar(relatorio):
    """Lê (se preciso) e devolve a Tabela do relatório. Pode levar alguns segundos."""
    if relatorio not in RELATORIOS:
        raise ErroERP(f"Relatório '{relatorio}' não existe. Use um destes: {', '.join(RELATORIOS)}.")
    with _trava:
        item = _carregados.get(relatorio)
    if item and time.time() - item[0].timestamp() < portal.VALIDADE_MINUTOS * 60:
        return item[1]
    try:
        tabela = _montar_estoque() if relatorio == "estoque" else _montar_previsao(relatorio)
    except portal.ErroPortal as erro:
        raise ErroERP(str(erro)) from None
    with _trava:
        _carregados[relatorio] = (datetime.now(), tabela)
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


LIMITE_PEDIDOS = 100


def consultar_produto(codigo, status=""):
    """Pedidos de um produto (tela Consulta por Produto), com totais por status.

    status: só os pedidos com esse status ("Programado", "analise"...; sem
    diferença de acento ou maiúscula). Vazio traz todos. O filtro é feito
    aqui, e não pelo modelo, para que a lista devolvida já seja a resposta:
    filtrando de cabeça uma lista longa, o modelo chegou a inventar pedidos.
    """
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
        status_do_pedido = por_status.setdefault(pedido.get("Status") or "(sem status)", {"pedidos": 0, "quantidade": 0})
        status_do_pedido["pedidos"] += 1
        if isinstance(pedido.get("Quantidade"), (int, float)):
            status_do_pedido["quantidade"] += pedido["Quantidade"]
    resultado = {
        "produto": codigo,
        "quantidade_de_pedidos": len(pedidos),
        "quantidade_total": sum(s["quantidade"] for s in por_status.values()),
        "por_status": por_status,
    }

    filtro = planilhas.normalizar(status or "")
    if filtro:
        escolhidos = [p for p in pedidos if filtro in planilhas.normalizar(p.get("Status") or "")]
        resultado["filtro_status"] = status
        resultado["pedidos_no_filtro"] = len(escolhidos)
        resultado["quantidade_no_filtro"] = sum(
            p["Quantidade"] for p in escolhidos if isinstance(p.get("Quantidade"), (int, float))
        )
        if not escolhidos:
            resultado["aviso"] = (f"Nenhum pedido com status '{status}'. Status que existem: "
                                  f"{', '.join(por_status)}.")
        pedidos = escolhidos

    # Uma linha de texto por pedido, já na ordem do ERP (por data programada):
    # é o que a MAX copia para a resposta, sem montar nada.
    resultado["pedidos"] = [
        f"{p.get('Data Programada', '')} | pedido {p.get('Pedido', '')} | "
        f"{p.get('Status', '')} | quantidade {p.get('Quantidade', '')}"
        for p in pedidos[:LIMITE_PEDIDOS]
    ]
    resultado["consultado"] = f"{datetime.now():%d/%m %H:%M}"
    if len(pedidos) > LIMITE_PEDIDOS:
        resultado["aviso"] = (f"Mostrando só os {LIMITE_PEDIDOS} primeiros de {len(pedidos)} pedidos; "
                              "os totais contam todos.")
    return resultado
