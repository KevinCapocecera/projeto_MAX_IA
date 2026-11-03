"""Leitura de QUALQUER aba das planilhas da pasta dados.

O MAX usa este módulo para responder perguntas sobre qualquer aba
(solicitações de compra, apontamentos, base de vendas, fornecedores,
estoque e carteira...), não só a análise de DOH.

Como cada aba tem um formato, a leitura é automática:
- o cabeçalho é a linha, entre as primeiras, com mais textos/datas;
- nas abas de ANÁLISE (Fiesta, Talher...), a tabela de produtos começa
  na linha "Cod Prodt" e o quadro do topo vira uma tabela à parte,
  "<aba> - RESUMO POR SEGMENTO";
- linhas e colunas totalmente vazias são descartadas.

Quem calcula é sempre o Python (filtros, somas, médias, contagens), com
os valores da última versão SALVA de cada planilha. Ela só é lida de
novo quando o arquivo muda.

Planilhas anexadas pelo chat ficam em usuarios/<nome>/anexos e só
aparecem para quem anexou: o MAX chama usar_anexos(pasta) antes de
responder, e as abas desses arquivos entram na lista só naquela thread.
O nome delas começa pelo nome do arquivo ("Estoque - Planilha1").
"""

import io
import math
import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook


PASTA_DADOS = Path(__file__).resolve().parent.parent / "dados"
PASTA_RELATORIOS = Path(__file__).resolve().parent.parent / "relatorios"
LIMITE_EXPORTACAO = 100_000   # linhas por arquivo exportado

LINHAS_VAZIAS_PARA_PARAR = 500   # algumas abas vão "formatadas" até a linha 1.048.576
LINHAS_PROCURA_CABECALHO = 15
LIMITE_LINHAS = 100
LIMITE_COLUNAS = 30
LIMITE_GRUPOS = 60
LIMITE_TEXTO = 120
EXTENSOES_ANEXO = (".xlsx", ".xlsm", ".csv")


# ============================================================
# TEXTO
# ============================================================

def normalizar(texto):
    """Maiúsculas, sem acentos e com espaços simples."""
    texto = unicodedata.normalize("NFD", str(texto))
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip().upper()


def _radical(palavra):
    """Tira o plural simples: "COPOS" -> "COPO", "TALHERES" -> "TALHER"."""
    if len(palavra) > 4 and palavra.endswith("ES"):
        return palavra[:-2]
    if len(palavra) > 3 and palavra.endswith("S"):
        return palavra[:-1]
    return palavra


def _vazio(valor):
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return isinstance(valor, str) and not valor.strip()


# ============================================================
# LEITURA DAS ABAS
# ============================================================

@dataclass
class Tabela:
    nome: str
    arquivo: str
    oculta: bool
    df: pd.DataFrame = field(repr=False)
    anexo: bool = False


def _nome_coluna(valor, indice):
    """Texto do cabeçalho; datas viram "08/2025" (mês) ou "28/10/2026"."""
    if isinstance(valor, datetime):
        if valor.day == 1 and valor.time() == time(0):
            return f"{valor:%m/%Y}"
        return f"{valor:%d/%m/%Y}"
    if isinstance(valor, date):
        return f"{valor:%d/%m/%Y}"
    if _vazio(valor):
        letra = ""
        n = indice + 1
        while n:
            n, resto = divmod(n - 1, 26)
            letra = chr(65 + resto) + letra
        return f"Coluna {letra}"
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor)).strip()


def _sem_repetir(nomes):
    vistos = {}
    saida = []
    for nome in nomes:
        chave = normalizar(nome)
        if chave in vistos:
            vistos[chave] += 1
            nome = f"{nome} ({vistos[chave]})"
        else:
            vistos[chave] = 1
        saida.append(nome)
    return saida


def _ler_linhas(ws):
    """Todas as linhas com algum valor (para depois de muitas vazias seguidas)."""
    linhas = []
    vazias = 0
    for linha in ws.iter_rows(values_only=True):
        if all(_vazio(v) for v in linha):
            vazias += 1
            if vazias >= LINHAS_VAZIAS_PARA_PARAR:
                break
            linhas.append(None)
        else:
            vazias = 0
            linhas.append(list(linha))
    while linhas and linhas[-1] is None:
        linhas.pop()
    largura = max((len(l) for l in linhas if l), default=0)
    return [
        (l + [None] * (largura - len(l))) if l else [None] * largura
        for l in linhas
    ]


def _montar_df(cabecalho, linhas, manter=None):
    """DataFrame só com as colunas que têm nome ou algum dado."""
    nomes = _sem_repetir([_nome_coluna(v, i) for i, v in enumerate(cabecalho)])
    df = pd.DataFrame(linhas, columns=nomes, dtype=object)
    preenchidas = pd.Series(
        [not all(_vazio(v) for v in linha) for linha in df.itertuples(index=False)],
        index=df.index, dtype=bool,
    )
    df = df.loc[preenchidas]
    colunas = [
        nome for i, nome in enumerate(nomes)
        if (manter and nome in manter)
        or not _vazio(cabecalho[i])
        or not df[nome].map(_vazio).all()
    ]
    return df[colunas].reset_index(drop=True)


def _linha_do_cabecalho(linhas):
    """Entre as primeiras linhas, a que tem mais textos e datas."""
    melhor, pontos_melhor = 0, -1
    for i, linha in enumerate(linhas[:LINHAS_PROCURA_CABECALHO]):
        if not linha:
            continue
        pontos = sum(
            1 for v in linha
            if isinstance(v, (str, datetime, date)) and not _vazio(v)
        )
        if pontos > pontos_melhor:
            melhor, pontos_melhor = i, pontos
    return melhor


def _tabelas_da_aba(ws, arquivo):
    linhas = _ler_linhas(ws)
    oculta = ws.sheet_state != "visible"
    if not linhas:
        return []

    # Abas de análise: tabela de produtos a partir de "Cod Prodt".
    produtos = None
    for i, linha in enumerate(linhas[:80]):
        if linha and any(normalizar(v) in ("COD PRODT", "CODIGO") for v in linha if isinstance(v, str)):
            if i > 2:
                produtos = i
            break

    if produtos is None:
        h = _linha_do_cabecalho(linhas)
        dados = [l for l in linhas[h + 1:] if l]
        return [Tabela(ws.title, arquivo, oculta, _montar_df(linhas[h], dados))]

    tabelas = []
    cab = linhas[produtos]
    col_codigo = next(
        j for j, v in enumerate(cab)
        if isinstance(v, str) and normalizar(v) in ("COD PRODT", "CODIGO")
    )
    dados = [l for l in linhas[produtos + 1:] if l and not _vazio(l[col_codigo])]
    tabelas.append(Tabela(ws.title, arquivo, oculta, _montar_df(cab, dados)))

    # Quadro do topo: linha 1 = nomes, linha 2 = unidades, depois segmentos.
    topo, unidades = linhas[0], linhas[1] if len(linhas) > 1 else None
    if topo:
        col_seg = next((j for j, v in enumerate(topo) if not _vazio(v)), 1) - 1
        if col_seg >= 0:
            nomes = []
            for j, v in enumerate(topo):
                if j < col_seg:
                    nomes.append(None)
                elif j == col_seg:
                    nomes.append("Segmento")
                else:
                    unidade = unidades[j] if unidades and isinstance(unidades[j], str) else ""
                    nome = _nome_coluna(v, j)
                    if unidade.strip() and not normalizar(unidade).startswith("CLIQUE"):
                        nome = f"{nome} ({unidade.strip()})"
                    nomes.append(nome if not _vazio(v) else None)
            segs = [
                l for l in linhas[2:produtos]
                if l and not _vazio(l[col_seg])
            ]
            if segs:
                df = _montar_df(nomes, segs, manter={"Segmento"})
                df = df[[c for c in df.columns if not c.startswith("Coluna ")]]
                tabelas.append(Tabela(
                    f"{ws.title} - RESUMO POR SEGMENTO", arquivo, oculta, df
                ))
    return tabelas


_cache = {}
_trava = threading.Lock()


def arquivos():
    """Planilhas da pasta dados (sem os temporários "~$" do Excel)."""
    return sorted(
        p for p in PASTA_DADOS.glob("*.xls[xm]")
        if not p.name.startswith("~$")
    )


def _ler_csv(caminho):
    """Tabela de um .csv (separador ; , ou tabulação, como o Excel salva)."""
    dados = caminho.read_bytes()
    for codificacao in ("utf-8-sig", "cp1252", "latin-1"):   # latin-1 lê qualquer byte
        try:
            texto = dados.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    primeira = texto.split("\n", 1)[0]
    separador = max([";", ",", "\t"], key=primeira.count)
    bruto = pd.read_csv(io.StringIO(texto), sep=separador, dtype=str, keep_default_na=False)
    cabecalho = [None if str(c).startswith("Unnamed:") else c for c in bruto.columns]
    linhas = [[None if _vazio(v) else v for v in linha] for linha in bruto.values.tolist()]
    df = _montar_df(cabecalho, linhas)

    # Datas chegam como texto; viram datas para os filtros "entre" e "<".
    def para_data(valor):
        data = None if _vazio(valor) else _data_texto(valor)
        return None if data is None or pd.isna(data) else data.to_pydatetime()

    for coluna in df.columns:
        preenchidos = df[coluna][~df[coluna].map(_vazio)]
        if not preenchidos.empty and preenchidos.map(_data_texto).notna().mean() >= 0.8:
            # dtype=object: continua datetime do Python, como vem do Excel (sem NaT).
            df[coluna] = pd.Series([para_data(v) for v in df[coluna]], index=df.index, dtype=object)
    return df


def _ler_arquivo(caminho, anexo=False, nome=None):
    """Tabelas de um arquivo, sem cache. nome: o nome do arquivo para mostrar."""
    nome = nome or caminho.name
    if caminho.suffix.lower() == ".csv":
        return [Tabela(Path(nome).stem, nome, False, _ler_csv(caminho), anexo)]

    wb = load_workbook(caminho, read_only=True, data_only=True)
    try:
        tabelas = []
        for ws in wb.worksheets:
            try:
                tabelas.extend(_tabelas_da_aba(ws, nome))
            except Exception as erro:  # uma aba estranha não derruba as outras
                print(f"[MAX] Não consegui ler a aba {ws.title!r}: {erro}", flush=True)
    finally:
        wb.close()
    if anexo:
        for t in tabelas:
            t.nome = f"{Path(nome).stem} - {t.nome}"
            t.anexo = True
    return tabelas


def _tabelas_do_arquivo(caminho, anexo=False):
    versao = caminho.stat().st_mtime
    with _trava:
        item = _cache.get(caminho)
        if item and item[0] == versao:
            return item[1]
        tabelas = _ler_arquivo(caminho, anexo)
        _cache[caminho] = (versao, tabelas)
        return tabelas


# ============================================================
# PLANILHAS ANEXADAS PELO CHAT
# ============================================================

_anexos = threading.local()


def usar_anexos(pasta):
    """Pasta das planilhas anexadas visíveis nesta thread (None: nenhuma)."""
    _anexos.pasta = Path(pasta) if pasta else None


def arquivos_anexos(pasta):
    """Planilhas anexadas de uma pessoa (sem as que ainda estão chegando, "~")."""
    pasta = Path(pasta)
    if not pasta.is_dir():
        return []
    return sorted(
        p for p in pasta.iterdir()
        if p.suffix.lower() in EXTENSOES_ANEXO and not p.name.startswith("~")
    )


def receber_anexo(temporario, destino):
    """Lê a planilha recém-enviada e, se der certo, guarda no lugar dela.

    Se a leitura falhar, apaga o temporário e mantém a versão anterior
    (se houver). Devolve as tabelas lidas.
    """
    try:
        lidas = _ler_arquivo(temporario, anexo=True, nome=destino.name)
        if not any(len(t.df) for t in lidas):
            raise ValueError("não encontrei nenhuma linha com dados")
    except Exception:
        temporario.unlink(missing_ok=True)
        raise
    os.replace(temporario, destino)
    with _trava:
        _cache[destino] = (destino.stat().st_mtime, lidas)
    return lidas


def esquecer(caminho):
    """Tira um arquivo do cache (ex.: anexo removido)."""
    with _trava:
        _cache.pop(Path(caminho), None)


def tabelas():
    """Todas as tabelas das planilhas da pasta dados e dos anexos desta thread."""
    todas = []
    for caminho in arquivos():
        todas.extend(_tabelas_do_arquivo(caminho))
    pasta = getattr(_anexos, "pasta", None)
    if pasta:
        for caminho in arquivos_anexos(pasta):
            todas.extend(_tabelas_do_arquivo(caminho, anexo=True))
    # Mesmo nome de aba em arquivos diferentes: acrescenta o arquivo. Usa
    # cópias, porque as tabelas do cache valem para todas as pessoas.
    contagem = {}
    for t in todas:
        contagem[normalizar(t.nome)] = contagem.get(normalizar(t.nome), 0) + 1
    return [
        replace(t, nome=f"{t.nome} [{t.arquivo}]") if contagem[normalizar(t.nome)] > 1 else t
        for t in todas
    ]


def resolver_tabela(nome):
    """Acha a tabela pelo nome completo ou por parte dele.

    Devolve (Tabela, None) ou (None, dicionário de erro).
    """
    todas = tabelas()
    alvo = normalizar(nome)
    if not alvo:
        return None, {"erro": "Informe qual aba usar.", "abas": [t.nome for t in todas]}

    exatas = [t for t in todas if normalizar(t.nome) == alvo]
    if len(exatas) == 1:
        return exatas[0], None

    palavras = [_radical(p) for p in re.split(r"[\s\-_.]+", alvo) if p and p != "ANALISE"]
    candidatas = [t for t in todas if all(p in normalizar(t.nome) for p in palavras)]
    if not any(p in ("RESUMO", "SEGMENTO") for p in palavras):
        sem_resumo = [t for t in candidatas if "RESUMO POR SEGMENTO" not in normalizar(t.nome)]
        candidatas = sem_resumo or candidatas

    if len(candidatas) == 1:
        return candidatas[0], None
    if not candidatas:
        return None, {
            "erro": f"Não encontrei a aba '{nome}'.",
            "abas": [t.nome for t in todas],
        }
    return None, {
        "erro": f"'{nome}' combina com mais de uma aba. Pergunte ao usuário qual delas.",
        "opcoes": [t.nome for t in candidatas],
    }


def resolver_coluna(df, nome):
    """Acha a coluna pelo nome (sem diferenciar acentos e maiúsculas)."""
    alvo = normalizar(nome).strip(" .:")
    colunas = list(df.columns)
    for criterio in (
        lambda c: normalizar(c) == alvo,
        lambda c: normalizar(c).strip(" .:") == alvo,
        lambda c: normalizar(c).startswith(alvo),
        lambda c: alvo in normalizar(c),
    ):
        achadas = [c for c in colunas if criterio(c)]
        if len(achadas) == 1:
            return achadas[0], None
        if len(achadas) > 1:
            return None, {
                "erro": f"A coluna '{nome}' combina com mais de uma: {achadas}.",
                "colunas": colunas,
            }
    return None, {"erro": f"Não existe a coluna '{nome}' nesta aba.", "colunas": colunas}


# ============================================================
# VALORES
# ============================================================

def valor_para_json(valor):
    """Valor da planilha em formato simples para o Gemini."""
    if _vazio(valor):
        return None
    if hasattr(valor, "item") and not isinstance(valor, (datetime, date)):
        valor = valor.item()
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, datetime):
        return f"{valor:%d/%m/%Y}" if valor.time() == time(0) else f"{valor:%d/%m/%Y %H:%M}"
    if isinstance(valor, date):
        return f"{valor:%d/%m/%Y}"
    if isinstance(valor, time):
        return f"{valor:%H:%M}"
    if isinstance(valor, int):
        return valor
    if isinstance(valor, float):
        if math.isinf(valor):
            return None
        if valor.is_integer():
            return int(valor)
        return round(valor, 2) if abs(valor) >= 1 else round(valor, 6)
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return texto if len(texto) <= LIMITE_TEXTO else texto[:LIMITE_TEXTO] + "…"


def _numeros(serie):
    def conv(v):
        if isinstance(v, bool) or _vazio(v):
            return math.nan
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            t = v.strip().replace("%", "")
            if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):   # 1.234,5
                t = t.replace(".", "").replace(",", ".")
            elif re.fullmatch(r"-?\d+,\d+", t):                 # 12,5
                t = t.replace(",", ".")
            try:
                return float(t)
            except ValueError:
                return math.nan
        return math.nan
    return serie.map(conv).astype(float)


def _datas(serie):
    def conv(v):
        if isinstance(v, datetime):
            return pd.Timestamp(v)
        if isinstance(v, date):
            return pd.Timestamp(v)
        if isinstance(v, str):
            return _data_texto(v)
        return pd.NaT
    return pd.to_datetime(serie.map(conv), errors="coerce")


def _data_texto(texto):
    t = str(texto).strip()
    for formato in ("%d/%m/%Y", "%d/%m/%y", "%d/%m/%Y %H:%M", "%Y-%m-%d", "%m/%Y"):
        try:
            return pd.Timestamp(datetime.strptime(t, formato))
        except ValueError:
            pass
    return pd.NaT


def _texto(serie):
    return serie.map(lambda v: "" if _vazio(v) else normalizar(valor_para_json(v)))


def _tipo(serie):
    """'numero', 'data' ou 'texto', pelo que predomina na coluna."""
    preenchidos = serie[~serie.map(_vazio)]
    if preenchidos.empty:
        return "texto"
    if _datas(preenchidos).notna().mean() >= 0.8 and preenchidos.map(
        lambda v: isinstance(v, (datetime, date))
    ).any():
        return "data"
    if _numeros(preenchidos).notna().mean() >= 0.8:
        return "numero"
    return "texto"


# ============================================================
# FILTROS
# ============================================================

_OPERADORES_PALAVRA = [
    (r"n[aã]o\s+cont[eé]m", "nao_contem"),
    (r"cont[eé]m", "contem"),
    (r"come[cç]a\s+com", "comeca"),
    (r"termina\s+com", "termina"),
    (r"n[aã]o\s+(?:est[aá]\s+|[eé]\s+)?vazi[oa]", "nao_vazio"),
    (r"(?:est[aá]\s+|[eé]\s+)?vazi[oa]", "vazio"),
    (r"entre", "entre"),
]
_OPERADORES_SIMBOLO = [(">=", ">="), ("<=", "<="), ("!=", "!="), ("<>", "!="), ("=", "="), (">", ">"), ("<", "<")]


def _separar_condicao(condicao):
    """'Status = AGUARDANDO' -> ('Status', '=', 'AGUARDANDO')."""
    for padrao, op in _OPERADORES_PALAVRA:
        m = re.match(rf"^(.+?)\s+{padrao}(?:\s+(.*))?$", condicao, re.IGNORECASE)
        if m:
            return m.group(1).strip(), op, (m.group(2) or "").strip()
    for simbolo, op in _OPERADORES_SIMBOLO:
        m = re.match(rf"^(.+?)\s*{re.escape(simbolo)}\s*(.*)$", condicao)
        if m:
            return m.group(1).strip(), op, m.group(2).strip()
    return None


def _sem_aspas(texto):
    return texto.strip().strip("\"'“”‘’").strip()


def aplicar_filtros(df, filtros):
    """Filtros separados por ";". Ex.: "Status = AGUARDANDO; Quantidade > 100".

    Devolve (df filtrado, None) ou (None, dicionário de erro).
    """
    for condicao in [c.strip() for c in str(filtros or "").split(";") if c.strip()]:
        partes = _separar_condicao(condicao)
        if not partes:
            return None, {
                "erro": f"Não entendi o filtro '{condicao}'.",
                "exemplo": "Status = AGUARDANDO; Quantidade > 100; Descrição contém COPO",
            }
        nome, op, valor = partes
        coluna, erro = resolver_coluna(df, nome)
        if erro:
            return None, erro
        serie = df[coluna]
        valor = _sem_aspas(valor)

        if op == "vazio":
            mascara = serie.map(_vazio)
        elif op == "nao_vazio":
            mascara = ~serie.map(_vazio)
        elif op in ("contem", "nao_contem", "comeca", "termina"):
            alvo = normalizar(valor)
            texto = _texto(serie)
            if op == "comeca":
                mascara = texto.str.startswith(alvo)
            elif op == "termina":
                mascara = texto.str.endswith(alvo)
            else:
                mascara = texto.str.contains(alvo, regex=False)
                if op == "nao_contem":
                    mascara = ~mascara
        else:
            mascara, erro = _comparar(serie, op, valor, coluna)
            if erro:
                return None, erro
        df = df[mascara.fillna(False).astype(bool)]
    return df, None


def _comparar(serie, op, valor, coluna):
    if op == "entre":
        partes = re.split(r"\s+e\s+|\s*;\s*|\s*,\s*(?=\S)", valor, maxsplit=1)
        if len(partes) != 2:
            return None, {"erro": f"Use: {coluna} entre 10 e 20."}
        a, erro = _comparar(serie, ">=", partes[0], coluna)
        if erro:
            return None, erro
        b, erro = _comparar(serie, "<=", partes[1], coluna)
        if erro:
            return None, erro
        return a & b, None

    tipo = _tipo(serie)
    alvo_data = _data_texto(valor)
    alvo_num = _numeros(pd.Series([valor])).iloc[0]

    if tipo == "data" and not pd.isna(alvo_data):
        esquerda, direita = _datas(serie), alvo_data
        if op in ("=", "!=") and alvo_data.time() == time(0):
            esquerda = esquerda.dt.normalize()
    elif not math.isnan(alvo_num) and op in (">", ">=", "<", "<=") or (
        not math.isnan(alvo_num) and tipo == "numero"
    ):
        esquerda, direita = _numeros(serie), alvo_num
    elif op in ("=", "!="):
        esquerda, direita = _texto(serie), normalizar(valor)
    else:
        return None, {
            "erro": f"Para usar '{op}' na coluna '{coluna}', informe um número ou uma data (dd/mm/aaaa)."
        }

    comparacoes = {
        "=": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        ">=": lambda a, b: a >= b,
        "<": lambda a, b: a < b,
        "<=": lambda a, b: a <= b,
    }
    return comparacoes[op](esquerda, direita), None


# ============================================================
# CONSULTAS
# ============================================================

def _ordenar(df, ordenar_por):
    texto = str(ordenar_por or "").strip()
    if not texto:
        return df, None
    decrescente = False
    m = re.match(r"^(.*?)\s+(desc|decrescente|maior para (?:o )?menor|asc|crescente|menor para (?:o )?maior)$",
                 texto, re.IGNORECASE)
    if m:
        texto = m.group(1)
        decrescente = normalizar(m.group(2)).startswith(("DESC", "DECRESC", "MAIOR"))
    coluna, erro = resolver_coluna(df, texto)
    if erro:
        return None, erro
    tipo = _tipo(df[coluna])
    chave = {"numero": _numeros, "data": _datas, "texto": _texto}[tipo](df[coluna])
    ordem = chave.sort_values(ascending=not decrescente, na_position="last").index
    return df.loc[ordem], None


def _escolher_colunas(df, colunas):
    nomes = [c.strip() for c in str(colunas or "").split(",") if c.strip()]
    if not nomes:
        return list(df.columns[:LIMITE_COLUNAS]), None
    escolhidas = []
    for nome in nomes:
        coluna, erro = resolver_coluna(df, nome)
        if erro:
            return None, erro
        if coluna not in escolhidas:
            escolhidas.append(coluna)
    return escolhidas, None


def linhas_json(df, colunas):
    return [
        {c: v for c in colunas if (v := valor_para_json(linha[c])) is not None}
        for _, linha in df.iterrows()
    ]


def catalogo():
    """Lista de abas com o tamanho e as colunas de cada uma."""
    todas = tabelas()
    varios_arquivos = len({t.arquivo for t in todas}) > 1
    saida = []
    for t in todas:
        item = {
            "aba": t.nome,
            "linhas": len(t.df),
            "colunas": [str(c) for c in t.df.columns[:40]],
        }
        if len(t.df.columns) > 40:
            item["outras_colunas"] = len(t.df.columns) - 40
        if t.oculta:
            item["oculta"] = True
        if t.anexo:
            item["anexada_pelo_usuario"] = True
        if varios_arquivos:
            item["arquivo"] = t.arquivo
        saida.append(item)
    return saida


def consultar(aba, filtros, colunas, ordenar_por, limite):
    tabela, erro = resolver_tabela(aba)
    if erro:
        return erro
    df, erro = aplicar_filtros(tabela.df, filtros)
    if erro:
        return {"aba": tabela.nome, **erro}
    df, erro = _ordenar(df, ordenar_por)
    if erro:
        return {"aba": tabela.nome, **erro}
    escolhidas, erro = _escolher_colunas(tabela.df, colunas)
    if erro:
        return {"aba": tabela.nome, **erro}

    try:
        limite = int(limite)
    except (TypeError, ValueError):
        limite = 20
    limite = max(1, min(limite, LIMITE_LINHAS))

    resultado = {
        "aba": tabela.nome,
        "linhas_encontradas": len(df),
        "linhas_mostradas": min(limite, len(df)),
        "linhas": linhas_json(df.head(limite), escolhidas),
    }
    if len(tabela.df.columns) > len(escolhidas):
        resultado["outras_colunas_da_aba"] = [c for c in tabela.df.columns if c not in escolhidas][:40]
    return resultado


_CALCULOS = {
    "SOMA": "soma", "SOMAR": "soma", "TOTAL": "soma",
    "MEDIA": "media", "MEDIO": "media",
    "MAX": "maximo", "MAXIMO": "maximo", "MAIOR": "maximo",
    "MIN": "minimo", "MINIMO": "minimo", "MENOR": "minimo",
    "CONTAGEM": "contagem", "CONTAR": "contagem", "QUANTIDADE DE LINHAS": "contagem",
    "DISTINTOS": "distintos", "CONTAGEM DISTINTA": "distintos",
}


def _ler_calculos(df, calculos):
    lista = []
    for parte in [p.strip() for p in str(calculos or "contagem").split(",") if p.strip()]:
        m = re.match(r"^(.+?)(?:\s+(?:de|do|da|dos|das)\s+(.+))?$", parte, re.IGNORECASE)
        operacao = _CALCULOS.get(normalizar(m.group(1))) if m else None
        if operacao is None:
            return None, {
                "erro": f"Não entendi o cálculo '{parte}'.",
                "exemplo": "soma de Quantidade, media de Estoque, contagem, distintos de Fornecedor",
            }
        coluna = None
        if operacao != "contagem" or m.group(2):
            if not m.group(2):
                return None, {"erro": f"Informe a coluna: '{parte} de <coluna>'."}
            coluna, erro = resolver_coluna(df, m.group(2))
            if erro:
                return None, erro
        lista.append((operacao, coluna))
    return lista, None


def _calcular(df, operacao, coluna):
    if operacao == "contagem":
        return len(df) if coluna is None else int((~df[coluna].map(_vazio)).sum())
    if operacao == "distintos":
        return int(_texto(df[coluna]).replace("", pd.NA).nunique())
    if _tipo(df[coluna]) == "data" and operacao in ("maximo", "minimo"):
        datas = _datas(df[coluna])
        valor = datas.max() if operacao == "maximo" else datas.min()
        return None if pd.isna(valor) else valor_para_json(valor.to_pydatetime())
    numeros = _numeros(df[coluna])
    valor = {
        "soma": numeros.sum,
        "media": numeros.mean,
        "maximo": numeros.max,
        "minimo": numeros.min,
    }[operacao]()
    return None if pd.isna(valor) else valor_para_json(float(valor))


def resumir(aba, filtros, agrupar_por, calculos, limite_grupos=LIMITE_GRUPOS):
    tabela, erro = resolver_tabela(aba)
    if erro:
        return erro
    df, erro = aplicar_filtros(tabela.df, filtros)
    if erro:
        return {"aba": tabela.nome, **erro}
    lista, erro = _ler_calculos(tabela.df, calculos)
    if erro:
        return {"aba": tabela.nome, **erro}

    def rotulo(operacao, coluna):
        return operacao if coluna is None else f"{operacao} de {coluna}"

    grupos_nomes = [g.strip() for g in str(agrupar_por or "").split(",") if g.strip()]
    if not grupos_nomes:
        return {
            "aba": tabela.nome,
            "linhas_consideradas": len(df),
            "resultado": {rotulo(o, c): _calcular(df, o, c) for o, c in lista},
        }

    grupos = []
    for nome in grupos_nomes:
        coluna, erro = resolver_coluna(tabela.df, nome)
        if erro:
            return {"aba": tabela.nome, **erro}
        grupos.append(coluna)

    chaves = df[grupos].apply(
        lambda s: s.map(lambda v: "(vazio)" if _vazio(v) else valor_para_json(v))
    )
    linhas = []
    for valores, indices in chaves.groupby(grupos, sort=False).groups.items():
        valores = valores if isinstance(valores, tuple) else (valores,)
        parte = df.loc[indices]
        item = dict(zip(grupos, valores))
        for o, c in lista:
            item[rotulo(o, c)] = _calcular(parte, o, c)
        linhas.append(item)

    primeira = rotulo(*lista[0])
    linhas.sort(key=lambda i: (i[primeira] is None, -(i[primeira] or 0) if isinstance(i[primeira], (int, float)) else 0))
    return {
        "aba": tabela.nome,
        "linhas_consideradas": len(df),
        "grupos_encontrados": len(linhas),
        "grupos": linhas[:limite_grupos] if limite_grupos else linhas,
    }


def buscar(termo, limite_por_aba=5):
    """Procura um texto (código, descrição, fornecedor...) em todas as abas."""
    alvo = normalizar(termo)
    if not alvo:
        return {"erro": "Informe o que procurar."}
    achados = []
    for t in tabelas():
        if t.df.empty:
            continue
        texto = t.df.apply(_texto)
        mascara = texto.apply(lambda s: s.str.contains(alvo, regex=False)).any(axis=1)
        total = int(mascara.sum())
        if not total:
            continue
        colunas = list(t.df.columns[:20])
        achados.append({
            "aba": t.nome,
            "linhas_encontradas": total,
            "exemplos": linhas_json(t.df[mascara].head(limite_por_aba), colunas),
        })
    if not achados:
        return {"termo": termo, "resultado": "Não encontrei em nenhuma aba."}
    achados.sort(key=lambda a: -a["linhas_encontradas"])
    return {"termo": termo, "abas": achados[:12]}


# ============================================================
# EXPORTAÇÃO PARA EXCEL
# ============================================================

def _arquivo_novo(prefixo, aba):
    """relatorios/<Prefixo>_<ABA>_<data_hora>.xlsx, sem acentos nem espaços."""
    PASTA_RELATORIOS.mkdir(parents=True, exist_ok=True)
    nome = re.sub(r"[^A-Z0-9-]+", "_", normalizar(aba).replace("ANALISE", "")).strip("_")[:40]
    base = f"{prefixo}_{nome or 'ABA'}_{datetime.now():%Y%m%d_%H%M%S}"
    caminho = PASTA_RELATORIOS / f"{base}.xlsx"
    n = 2
    while caminho.exists():
        caminho = PASTA_RELATORIOS / f"{base}_{n}.xlsx"
        n += 1
    return caminho


def _para_excel(valor):
    """Valor como o Excel entende (números e datas continuam números e datas)."""
    if _vazio(valor):
        return None
    if hasattr(valor, "item") and not isinstance(valor, (datetime, date)):
        valor = valor.item()
    if isinstance(valor, float) and math.isinf(valor):
        return None
    return valor


def _salvar_excel(caminho, df, nome_planilha, info):
    """Grava a tabela com cabeçalho destacado, filtros e larguras ajustadas.

    info vira uma segunda planilha, "Sobre", com a origem dos dados.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = nome_planilha[:31]
    colunas = [str(c) for c in df.columns]
    ws.append(colunas)
    for linha in df.itertuples(index=False):
        ws.append([_para_excel(v) for v in linha])

    destaque = PatternFill("solid", fgColor="1B4D4A")
    for celula in ws[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = destaque
        celula.alignment = Alignment(vertical="center")
    ws.freeze_panes = "A2"
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions

    for indice, coluna in enumerate(ws.iter_cols(min_row=1, max_row=min(ws.max_row, 500)), start=1):
        largura = 8
        for celula in coluna:
            valor = celula.value
            if isinstance(valor, (datetime, date)):
                celula.number_format = "DD/MM/YYYY" if (
                    not isinstance(valor, datetime) or valor.time() == time(0)
                ) else "DD/MM/YYYY HH:MM"
                largura = max(largura, 12)
            elif valor is not None:
                largura = max(largura, len(str(valor)))
        ws.column_dimensions[coluna[0].column_letter].width = min(largura + 2, 50)

    sobre = wb.create_sheet("Sobre")
    for chave, valor in info.items():
        sobre.append([chave, valor])
    for celula in sobre["A"]:
        celula.font = Font(bold=True)
    sobre.column_dimensions["A"].width = 18
    sobre.column_dimensions["B"].width = 70

    wb.save(caminho)
    return caminho


def exportar_consulta(aba, filtros, colunas, ordenar_por):
    """Exporta para Excel as linhas de uma aba (com filtros e ordenação)."""
    tabela, erro = resolver_tabela(aba)
    if erro:
        return erro
    df, erro = aplicar_filtros(tabela.df, filtros)
    if erro:
        return {"aba": tabela.nome, **erro}
    df, erro = _ordenar(df, ordenar_por)
    if erro:
        return {"aba": tabela.nome, **erro}
    nomes = [c.strip() for c in str(colunas or "").split(",") if c.strip()]
    if nomes:
        escolhidas, erro = _escolher_colunas(tabela.df, colunas)
        if erro:
            return {"aba": tabela.nome, **erro}
    else:
        escolhidas = list(tabela.df.columns)  # exportação leva todas as colunas
    if df.empty:
        return {"aba": tabela.nome, "erro": "Nenhuma linha atende aos filtros; nada para exportar."}

    cortado = len(df) > LIMITE_EXPORTACAO
    caminho = _arquivo_novo("Consulta", tabela.nome)
    _salvar_excel(caminho, df[escolhidas].head(LIMITE_EXPORTACAO), "Consulta", {
        "Aba": tabela.nome,
        "Planilha": tabela.arquivo,
        "Filtros": filtros or "(nenhum)",
        "Ordenação": ordenar_por or "(ordem da planilha)",
        "Linhas": min(len(df), LIMITE_EXPORTACAO),
        "Gerado em": datetime.now().strftime("%d/%m/%Y %H:%M"),
    })
    resultado = {"aba": tabela.nome, "arquivo": caminho.name, "linhas": min(len(df), LIMITE_EXPORTACAO),
                 "colunas": len(escolhidas)}
    if cortado:
        resultado["aviso"] = f"Só as primeiras {LIMITE_EXPORTACAO} linhas foram exportadas."
    return resultado


def exportar_resumo(aba, filtros, agrupar_por, calculos):
    """Exporta para Excel um resumo (totais por grupo) de uma aba."""
    resultado = resumir(aba, filtros, agrupar_por, calculos, limite_grupos=None)
    if "erro" in resultado:
        return resultado
    if "grupos" in resultado:
        df = pd.DataFrame(resultado["grupos"])
    else:
        df = pd.DataFrame([resultado["resultado"]])
    caminho = _arquivo_novo("Resumo", resultado["aba"])
    _salvar_excel(caminho, df, "Resumo", {
        "Aba": resultado["aba"],
        "Filtros": filtros or "(nenhum)",
        "Agrupado por": agrupar_por or "(total geral)",
        "Cálculos": calculos,
        "Linhas consideradas": resultado["linhas_consideradas"],
        "Gerado em": datetime.now().strftime("%d/%m/%Y %H:%M"),
    })
    return {"aba": resultado["aba"], "arquivo": caminho.name, "linhas": len(df)}
