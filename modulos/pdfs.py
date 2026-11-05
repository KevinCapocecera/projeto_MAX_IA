"""Leitura de PDFs anexados pelo chat (pedidos, orçamentos, listas de itens...).

Um PDF anexado vira tabelas, como uma planilha, para as mesmas
ferramentas (consultar_aba, buscar_na_planilha...):
- "<arquivo> - Tabela N": cada tabela que o pdfplumber reconhece (com
  linhas e colunas desenhadas ou bem alinhadas). Tabelas que continuam
  na página seguinte, com o mesmo cabeçalho, viram uma só;
- "<arquivo> - Texto": todo o texto, uma linha do PDF por linha da
  tabela (colunas Página e Texto). Serve para PDFs sem tabela.

O texto corrido também sai em partes por texto_em_partes(), para a MAX
ler o documento inteiro (ferramenta ler_pdf) e montar a lista de itens
que vai conferir no estoque.

PDF escaneado (só imagem) não tem texto: a leitura avisa.
"""

import re
import threading
from pathlib import Path

import pandas as pd
import pdfplumber


LIMITE_PAGINAS = 200
TAMANHO_PARTE = 12_000   # caracteres por parte do texto (ler_pdf)

_cache = {}   # caminho -> (mtime, paginas)
_trava = threading.Lock()


class PdfSemTexto(ValueError):
    pass


def _limpar(valor):
    if valor is None:
        return None
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    return texto or None


def _ler(caminho):
    """[(texto da página, [tabelas da página])], cada tabela uma lista de linhas."""
    paginas = []
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages[:LIMITE_PAGINAS]:
            texto = pagina.extract_text() or ""
            tabelas = []
            for bruta in pagina.extract_tables():
                linhas = [[_limpar(c) for c in linha] for linha in bruta]
                linhas = [l for l in linhas if any(l)]
                if len(linhas) >= 2 and max(len(l) for l in linhas) >= 2:
                    tabelas.append(linhas)
            paginas.append((texto, tabelas))
    if not any(texto.strip() for texto, _ in paginas):
        raise PdfSemTexto(
            "o PDF não tem texto, só imagem (provavelmente escaneado). "
            "Peça o PDF original, gerado pelo sistema, ou a planilha"
        )
    return paginas


def paginas(caminho):
    """Páginas do PDF (com cache pela data do arquivo)."""
    caminho = Path(caminho)
    versao = caminho.stat().st_mtime
    with _trava:
        item = _cache.get(caminho)
        if item and item[0] == versao:
            return item[1]
    lidas = _ler(caminho)
    with _trava:
        _cache[caminho] = (versao, lidas)
    return lidas


def esquecer(caminho):
    with _trava:
        _cache.pop(Path(caminho), None)


def _df_da_tabela(linhas, montar_df):
    largura = max(len(l) for l in linhas)
    linhas = [l + [None] * (largura - len(l)) for l in linhas]
    return montar_df(linhas[0], linhas[1:])


def tabelas(caminho, montar_df):
    """[(nome, DataFrame)] do PDF. montar_df(cabecalho, linhas) vem de planilhas."""
    lidas = paginas(caminho)
    saida = []

    juntas = []   # [cabecalho, linhas]
    for _, tabelas_da_pagina in lidas:
        for linhas in tabelas_da_pagina:
            cabecalho, corpo = linhas[0], linhas[1:]
            if juntas and juntas[-1][0] == cabecalho:
                juntas[-1][1].extend(corpo)      # continuação da página anterior
            else:
                juntas.append([cabecalho, list(corpo)])
    for numero, (cabecalho, corpo) in enumerate(juntas, start=1):
        df = _df_da_tabela([cabecalho] + corpo, montar_df)
        if len(df):
            saida.append((f"Tabela {numero}", df))

    linhas_texto = [
        (numero, linha.strip())
        for numero, (texto, _) in enumerate(lidas, start=1)
        for linha in texto.splitlines()
        if linha.strip()
    ]
    saida.append(("Texto", pd.DataFrame(linhas_texto, columns=["Página", "Texto"], dtype=object)))
    return saida


def texto_em_partes(caminho, parte):
    """Texto do PDF, página por página, cortado em partes de TAMANHO_PARTE."""
    lidas = paginas(caminho)
    texto = "\n\n".join(
        f"--- Página {numero} ---\n{conteudo.strip()}"
        for numero, (conteudo, _) in enumerate(lidas, start=1)
    )
    partes = [texto[i:i + TAMANHO_PARTE] for i in range(0, len(texto), TAMANHO_PARTE)] or [""]
    parte = min(max(int(parte or 1), 1), len(partes))
    return {
        "paginas": len(lidas),
        "parte": parte,
        "total_de_partes": len(partes),
        "texto": partes[parte - 1],
    }
