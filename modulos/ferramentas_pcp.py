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
from modulos import planilhas
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


def abas_com_doh():
    """Abas de análise que têm de fato as colunas de DOH."""
    nomes = []
    for nome in abas_disponiveis():
        try:
            _dados_da_aba(nome)
        except ValueError:
            continue  # ex.: ANÁLISE ITENS DE COMPRA (sem Demanda/DOH TT)
        nomes.append(nome)
    return nomes


def _dados_da_aba(nome_aba):
    """Devolve (dados brutos, plano de ação) da aba."""
    arquivo = localizar_planilha()
    versao = arquivo.stat().st_mtime

    def carregar():
        bruto = carregar_aba(arquivo, nome_aba)
        return bruto, calcular_plano(bruto, meta_doh=META_DOH)

    return _do_cache(("aba", nome_aba), versao, carregar)


def contexto_pcp():
    """Linhas para o prompt do chat com as abas disponíveis."""
    try:
        texto = (
            "Abas com análise de DOH: "
            + ", ".join(abas_com_doh())
            + "."
        )
    except Exception as erro:
        return f"A planilha de PCP não pôde ser lida agora: {erro}"
    try:
        nomes = [
            t.nome + (" (oculta)" if t.oculta else "")
            for t in planilhas.tabelas()
        ]
        texto += " Todas as abas que dá para consultar: " + "; ".join(nomes) + "."
    except Exception as erro:
        texto += f" As outras abas não puderam ser lidas agora: {erro}"
    return texto


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
            "erro": (
                f"'{aba}' não é uma aba com análise de DOH. Para ler "
                "qualquer outra aba, use consultar_aba, resumir_aba ou "
                "listar_abas_planilha."
            ),
            "abas_com_doh": abas_com_doh(),
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
                f"A aba {nome} não tem análise de DOH (faltam as colunas "
                "Demanda e DOH TT), mas pode ser lida normalmente: use "
                f"consultar_aba ou resumir_aba com aba=\"{nome}\". Veja as "
                "colunas com listar_abas_planilha."
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


# Arquivos exportados durante a pergunta que está sendo respondida nesta
# thread. O servidor (servidor.py) usa isso para mostrar o botão de
# baixar logo abaixo da resposta.
_exportados = threading.local()


def comecar_registro_exportacoes():
    _exportados.lista = []


def exportacoes_registradas():
    return list(getattr(_exportados, "lista", []))


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
    if hasattr(_exportados, "lista"):
        _exportados.lista.append(arquivo.name)
    return {
        "aba": nome,
        "arquivo": str(arquivo.resolve()),
        "produtos": len(plano),
    }


# ============================================================
# QUALQUER ABA (consultas gerais)
# ============================================================

def _protegido(funcao, *args):
    try:
        return funcao(*args)
    except Exception as erro:
        return {"erro": f"Não consegui ler a planilha: {erro}"}


def listar_abas_planilha(parte_do_nome: str) -> dict:
    """Lista as abas das planilhas, com quantas linhas e quais colunas cada uma tem.

    Use para descobrir em qual aba está uma informação e os nomes
    exatos das colunas antes de usar consultar_aba ou resumir_aba.
    Inclui as abas ocultas.

    Args:
        parte_do_nome: Parte do nome da aba para filtrar a lista, por
            exemplo "compra" ou "vendas". Use "" para listar todas.

    Returns:
        Lista de abas com nome, linhas, colunas e se está oculta.
    """
    _log(f"listando as abas ({parte_do_nome or 'todas'})")
    catalogo = _protegido(planilhas.catalogo)
    if isinstance(catalogo, dict):
        return catalogo
    filtro = planilhas.normalizar(parte_do_nome)
    if filtro:
        catalogo = [a for a in catalogo if filtro in planilhas.normalizar(a["aba"])] or catalogo
    return {"abas": catalogo}


def consultar_aba(aba: str, filtros: str, colunas: str, ordenar_por: str, limite: int) -> dict:
    """Lê linhas de QUALQUER aba da planilha, com filtros e ordenação.

    Use para qualquer pergunta sobre o conteúdo das abas: solicitações
    de compra, prioridades, apontamentos, base de vendas, fornecedores,
    estoque e carteira, insumos, bobinas, as tabelas de análise etc.
    Não serve para somar ou contar: para isso use resumir_aba.

    Args:
        aba: Nome da aba, completo ou em parte. Ex.: "solicitações de
            compra", "apontamentos", "base de vendas", "fiesta".
        filtros: Condições separadas por ";". Operadores: =, !=, >, >=,
            <, <=, contém, não contém, começa com, termina com, entre,
            vazio, não vazio. Datas em dd/mm/aaaa. Maiúsculas e acentos
            não importam. Ex.: "Status = AGUARDANDO; Quantidade > 100",
            "Descrição contém COPO 200", "Data entre 01/10/2026 e
            31/10/2026", "Data de Entrega vazio". Use "" para nenhum.
        colunas: Colunas a mostrar, separadas por vírgula. Use "" para
            as primeiras colunas da aba.
        ordenar_por: Coluna para ordenar, com "desc" no fim para do
            maior para o menor. Ex.: "Quantidade desc". Use "" para a
            ordem da planilha.
        limite: Quantas linhas devolver (máximo 100).

    Returns:
        Total de linhas encontradas e as linhas pedidas. Em caso de
        erro, a mensagem e a lista de abas ou colunas válidas.
    """
    _log(f"consultando a aba {aba!r} ({filtros or 'sem filtro'})")
    return _protegido(planilhas.consultar, aba, filtros, colunas, ordenar_por, limite)


def resumir_aba(aba: str, filtros: str, agrupar_por: str, calculos: str) -> dict:
    """Soma, média, contagem, máximo ou mínimo de QUALQUER aba, com ou sem agrupamento.

    Use para totais e rankings: "quanto foi solicitado por fornecedor",
    "quantas solicitações estão aguardando", "venda de setembro por
    segmento", "média de estoque", "quantos fornecedores diferentes".

    Args:
        aba: Nome da aba, completo ou em parte.
        filtros: Mesmo formato de consultar_aba. Use "" para nenhum.
        agrupar_por: Coluna(s) para agrupar, separadas por vírgula. Ex.:
            "Fornecedor" ou "Segmento, Cor". Use "" para o total geral.
        calculos: Separados por vírgula: "contagem", "soma de <coluna>",
            "media de <coluna>", "maximo de <coluna>", "minimo de
            <coluna>", "distintos de <coluna>". Ex.: "soma de
            Quantidade, contagem".

    Returns:
        O resultado geral ou um grupo por linha, do maior para o menor
        no primeiro cálculo.
    """
    _log(f"resumindo a aba {aba!r} ({calculos})")
    return _protegido(planilhas.resumir, aba, filtros, agrupar_por, calculos)


def buscar_na_planilha(termo: str) -> dict:
    """Procura um código, descrição, fornecedor ou qualquer texto em TODAS as abas.

    Use quando o usuário citar um item e não estiver claro em qual aba
    ele está, ou para juntar tudo o que a planilha tem sobre um código.

    Args:
        termo: Texto a procurar (parte do código ou da descrição).

    Returns:
        As abas onde o termo aparece, quantas linhas em cada uma e
        alguns exemplos.
    """
    _log(f"procurando {termo!r} em todas as abas")
    return _protegido(planilhas.buscar, termo)


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
    listar_abas_planilha,
    consultar_aba,
    resumir_aba,
    buscar_na_planilha,
]
