"""Ferramentas de PCP que o MAX pode usar no chat.

O Gemini decide quando chamar cada função (function calling), mas quem
calcula é o Python, com os mesmos cálculos do plano de ação, direto na
planilha ANÁLISE DIÁRIA DE PROGRAMAÇÃO. Assim os números nunca são
inventados pelo modelo.

Regras das funções expostas ao Gemini (lista FERRAMENTAS_PCP):
- parâmetros simples (str ou int) e sem valor padrão (o google-genai
  2.31 quebra ao executar funções com Literal, então as opções ficam
  descritas na docstring e são validadas dentro da função);
- a docstring explica ao modelo quando usar a função e cada parâmetro;
- o retorno é sempre um dicionário com tipos simples (vira JSON);
- erros voltam como {"erro": ...} para o modelo explicar ao usuário.
"""

import math
import threading
from datetime import datetime

import pandas as pd

from modulos.base_dados import (
    carregar_aba,
    listar_abas_analise,
    localizar_planilha,
    normalizar,
)
from modulos.plano_acao import calcular_plano, salvar_plano


META_DOH = 45
LIMITE_MAXIMO = 50

PRIORIDADES = ["CRÍTICA", "ALTA", "MÉDIA", "DENTRO DA META", "SEM DEMANDA"]

FILTROS = {
    "abaixo_da_meta": ["CRÍTICA", "ALTA", "MÉDIA"],
    "menos_de_15_dias": ["CRÍTICA", "ALTA"],
    "critica": ["CRÍTICA"],
    "alta": ["ALTA"],
    "media": ["MÉDIA"],
    "dentro_da_meta": ["DENTRO DA META"],
    "sem_demanda": ["SEM DEMANDA"],
    "todas": PRIORIDADES,
}

COLUNAS_IDENTIFICACAO = ("COD PRODT", "CODIGO", "SEGMENTO", "REF", "COR")


# ============================================================
# LEITURA DA PLANILHA (com cache)
# ============================================================
# A planilha só é lida de novo quando o arquivo muda (data da última
# gravação). Ela é lida na última versão SALVA no Excel.

_cache = {}
_trava = threading.Lock()


def _do_cache(chave, versao, carregar):
    with _trava:
        item = _cache.get(chave)
        if item and item[0] == versao:
            return item[1]

    valor = carregar()

    with _trava:
        _cache[chave] = (versao, valor)
    return valor


def abas_disponiveis():
    """Nomes das abas de análise da planilha."""
    arquivo = localizar_planilha()
    versao = arquivo.stat().st_mtime
    return _do_cache(
        "abas", versao, lambda: listar_abas_analise(arquivo)
    )


def _dados_da_aba(nome_aba):
    """Devolve (dados brutos, plano de ação) da aba."""
    arquivo = localizar_planilha()
    versao = arquivo.stat().st_mtime

    def carregar():
        bruto = carregar_aba(arquivo, nome_aba)
        return bruto, calcular_plano(bruto, meta_doh=META_DOH)

    return _do_cache(("aba", nome_aba), versao, carregar)


def contexto_pcp():
    """Linha para o prompt do chat com as abas disponíveis."""
    try:
        return (
            "Abas de análise disponíveis na planilha: "
            + ", ".join(abas_disponiveis())
            + "."
        )
    except Exception as erro:
        return f"A planilha de PCP não pôde ser lida agora: {erro}"


# ============================================================
# AUXILIARES
# ============================================================

def _radical(palavra):
    """Tira o plural simples: "COPOS" -> "COPO", "TALHERES" -> "TALHER"."""
    if len(palavra) > 4 and palavra.endswith("ES"):
        return palavra[:-2]
    if len(palavra) > 3 and palavra.endswith("S"):
        return palavra[:-1]
    return palavra


def _resolver_aba(aba):
    """Acha a aba pelo nome completo ou por parte dele.

    Devolve (nome_da_aba, None) ou (None, dicionário de erro).
    """
    abas = abas_disponiveis()
    palavras = [
        _radical(p) for p in normalizar(aba).split()
        if p != "ANALISE"
    ]

    if not palavras:
        return None, {
            "erro": "Informe qual aba de análise usar.",
            "abas_disponiveis": abas,
        }

    exata = [
        a for a in abas
        if normalizar(a).replace("ANALISE", "").strip()
        == " ".join(palavras)
    ]
    if len(exata) == 1:
        return exata[0], None

    candidatas = [
        a for a in abas
        if all(p in normalizar(a) for p in palavras)
    ]

    if len(candidatas) == 1:
        return candidatas[0], None

    if not candidatas:
        return None, {
            "erro": f"Não encontrei a aba '{aba}'.",
            "abas_disponiveis": abas,
        }

    return None, {
        "erro": (
            f"'{aba}' combina com mais de uma aba. "
            "Pergunte ao usuário qual delas."
        ),
        "opcoes": candidatas,
    }


def _plano(aba):
    """Devolve (nome_da_aba, dados brutos, plano) ou um erro."""
    nome, erro = _resolver_aba(aba)
    if erro:
        return None, None, None, erro

    try:
        bruto, plano = _dados_da_aba(nome)
    except ValueError:
        return None, None, None, {
            "erro": (
                f"A aba {nome} ainda não tem análise de DOH "
                "(faltam as colunas Demanda e DOH TT)."
            )
        }

    return nome, bruto, plano, None


def _valor_simples(valor):
    """Converte valores do pandas/numpy em tipos que viram JSON."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(valor, "item"):
        valor = valor.item()
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        if math.isinf(valor):
            return None
        return int(valor) if valor.is_integer() else round(valor, 1)
    return str(valor).strip()


def _linhas(df):
    return [
        {str(coluna): _valor_simples(valor) for coluna, valor in linha.items()}
        for _, linha in df.iterrows()
    ]


_ouvintes = []


def ao_consultar(funcao):
    """Registra uma função chamada sempre que uma ferramenta lê a planilha.

    A interface usa isso para mostrar "Consultando a planilha" na hora.
    A função recebe uma descrição curta do que está sendo consultado.
    """
    _ouvintes.append(funcao)


def _log(texto):
    print(f"[MAX] Consultando a planilha: {texto}", flush=True)
    for funcao in list(_ouvintes):
        try:
            funcao(texto)
        except Exception as erro:
            print(f"[MAX] Aviso para a interface falhou: {erro}", flush=True)


def _contagem(plano):
    """Quantidade de produtos por prioridade e o total abaixo da meta."""
    contagem = plano["Prioridade"].value_counts()
    por_prioridade = {p: int(contagem.get(p, 0)) for p in PRIORIDADES}
    abaixo = sum(por_prioridade[p] for p in FILTROS["abaixo_da_meta"])
    return por_prioridade, abaixo


# ============================================================
# FERRAMENTAS EXPOSTAS AO GEMINI
# ============================================================

def resumo_pcp(aba: str) -> dict:
    """Resumo do estoque de uma aba de análise do PCP, comparado à meta de 45 dias de DOH.

    Use para perguntas gerais, como "como está a Fiesta?" ou "quantos
    produtos do Talher estão abaixo da meta?". O segmento PET fica de fora.

    Args:
        aba: Nome da aba de análise, completo ou em parte. Exemplos:
            "fiesta", "talher", "prato", "copo bco-trp", "copo colorido".

    Returns:
        Quantidade de produtos por prioridade (CRÍTICA: DOH até 0; ALTA:
        abaixo de 15 dias; MÉDIA: de 15 dias até abaixo da meta; DENTRO DA
        META; SEM DEMANDA) e a necessidade estimada total, em caixas.
    """
    _log(f"resumo da aba {aba!r}")
    nome, _, plano, erro = _plano(aba)
    if erro:
        return erro

    por_prioridade, abaixo = _contagem(plano)

    return {
        "aba": nome,
        "meta_doh_dias": META_DOH,
        "unidade": "caixas",
        "produtos_analisados": len(plano),
        "abaixo_da_meta": abaixo,
        "por_prioridade": por_prioridade,
        "necessidade_estimada_total": int(
            plano["Necessidade estimada"].sum()
        ),
    }


def listar_produtos_pcp(aba: str, filtro: str, limite: int) -> dict:
    """Lista os produtos de uma aba de análise do PCP, dos mais urgentes para os menos urgentes.

    Cada produto vem com estoque, carteira, demanda, DOH, estoque alvo,
    necessidade estimada (em caixas) e prioridade. O PET fica de fora.

    Args:
        aba: Nome da aba de análise, completo ou em parte. Exemplos:
            "fiesta", "talher", "prato", "copo bco-trp", "copo colorido".
        filtro: Quais produtos listar. "abaixo_da_meta" junta CRÍTICA,
            ALTA e MÉDIA; "menos_de_15_dias" junta CRÍTICA e ALTA;
            "critica", "alta", "media", "dentro_da_meta" e "sem_demanda"
            trazem só aquela prioridade; "todas" traz tudo.
        limite: Quantos produtos devolver, de 1 a 50. Use 10 se o
            usuário não disser.
    """
    _log(f"produtos da aba {aba!r}, filtro {filtro!r}, limite {limite}")
    nome, _, plano, erro = _plano(aba)
    if erro:
        return erro

    if filtro not in FILTROS:
        return {
            "erro": f"Filtro '{filtro}' inválido.",
            "filtros_validos": list(FILTROS),
        }

    limite = max(1, min(int(limite), LIMITE_MAXIMO))
    selecionados = plano[plano["Prioridade"].isin(FILTROS[filtro])]

    return {
        "aba": nome,
        "filtro": filtro,
        "unidade": "caixas",
        "total_encontrado": len(selecionados),
        "mostrando": min(limite, len(selecionados)),
        "produtos": _linhas(selecionados.head(limite)),
    }


def buscar_produto_pcp(termo: str) -> dict:
    """Procura produtos em todas as abas de análise do PCP.

    A busca olha o código, o segmento, a REF e a cor. Todas as palavras
    do termo precisam aparecer no produto. Produtos PET também são
    encontrados, mas vêm marcados como fora da análise.

    Args:
        termo: Código do produto ou parte dele (ex.: "CCPT10-20X6",
            "PFLISPIN"), ou palavras como segmento, REF e cor
            (ex.: "canudo rosa", "forminha azul").
    """
    _log(f"busca por {termo!r}")
    palavras = normalizar(termo).split()
    if not palavras:
        return {"erro": "Informe o código ou o nome do produto."}

    encontrados = []
    abas_sem_analise = []

    for nome in abas_disponiveis():
        try:
            bruto, plano = _dados_da_aba(nome)
        except ValueError:
            abas_sem_analise.append(nome)
            continue

        colunas_id = [
            c for c in bruto.columns
            if normalizar(c) in COLUNAS_IDENTIFICACAO
        ]
        # Junta as colunas de identificação num texto só, pulando as
        # células vazias (no pandas 3 elas continuam NaN após astype).
        texto = bruto[colunas_id].apply(
            lambda linha: normalizar(
                " ".join(str(v) for v in linha if pd.notna(v))
            ),
            axis=1,
        )
        achou = texto.apply(lambda t: all(p in t for p in palavras))

        for indice in bruto.index[achou]:
            if indice in plano.index:
                item = _linhas(plano.loc[[indice]])[0]
            else:
                colunas = colunas_id + [
                    c for c in ("Estoque", "Carteira", "Demanda", "DOH TT")
                    if c in bruto.columns
                ]
                item = _linhas(bruto.loc[[indice], colunas])[0]
                item["Prioridade"] = "PET (fora da análise)"
            item["aba"] = nome
            encontrados.append(item)

    resultado = {
        "termo": termo,
        "unidade": "caixas",
        "total_encontrado": len(encontrados),
        "produtos": encontrados[:20],
    }
    if len(encontrados) > 20:
        resultado["aviso"] = (
            "Mostrando só os 20 primeiros. Peça um termo mais específico."
        )
    if abas_sem_analise:
        resultado["abas_nao_pesquisadas"] = abas_sem_analise
    return resultado


def exportar_plano_pcp(aba: str) -> dict:
    """Gera o plano de ação de uma aba em Excel, na pasta relatorios do projeto.

    Use somente quando o usuário pedir para exportar, gerar ou salvar
    o plano de ação.

    Args:
        aba: Nome da aba de análise, completo ou em parte. Exemplos:
            "fiesta", "talher", "prato", "copo bco-trp", "copo colorido".

    Returns:
        O caminho do arquivo gerado e quantos produtos ele tem.
    """
    _log(f"exportando o plano da aba {aba!r}")
    nome, _, plano, erro = _plano(aba)
    if erro:
        return erro

    arquivo = salvar_plano(plano, nome_aba=nome)
    return {
        "aba": nome,
        "arquivo": str(arquivo.resolve()),
        "produtos": len(plano),
    }


# ============================================================
# QUADRO DA INTERFACE (não é ferramenta do Gemini)
# ============================================================

def painel():
    """Resumo de todas as abas com análise de DOH, para o quadro "Estoque por aba"."""
    arquivo = localizar_planilha()
    salva = datetime.fromtimestamp(arquivo.stat().st_mtime)

    abas = []
    for nome in abas_disponiveis():
        try:
            _, plano = _dados_da_aba(nome)
        except ValueError:
            continue  # aba sem DOH (ex.: ANÁLISE ITENS DE COMPRA)
        por_prioridade, abaixo = _contagem(plano)
        abas.append({
            "nome": nome,
            "analisados": len(plano),
            "abaixo": abaixo,
            "por_prioridade": por_prioridade,
        })

    return {"salva_em": f"{salva:%d/%m} às {salva:%H:%M}", "abas": abas}


FERRAMENTAS_PCP = [
    resumo_pcp,
    listar_produtos_pcp,
    buscar_produto_pcp,
    exportar_plano_pcp,
]
