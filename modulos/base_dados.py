
from pathlib import Path
import unicodedata
import pandas as pd
import math


def normalizar(texto):
    texto = str(texto).upper().strip()
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if unicodedata.category(caractere) != "Mn"
    )


def localizar_planilha():
    pasta_dados = Path(__file__).parent.parent / "dados"

    arquivos = (
        list(pasta_dados.glob("ANÁLISE DIÁRIA DE PROGRAMAÇÃO.xlsm"))
        + list(pasta_dados.glob("ANÁLISE DIÁRIA DE PROGRAMAÇÃO.xlsx"))
    )

    if not arquivos:
        raise FileNotFoundError(
            "Coloque a planilha ANÁLISE DIÁRIA DE PROGRAMAÇÃO "
            "na pasta dados."
        )

    return arquivos[0]


def listar_abas_analise(arquivo):
    excel = pd.ExcelFile(arquivo, engine="openpyxl")

    return [
        aba for aba in excel.sheet_names
        if "ANALISE" in normalizar(aba)
    ]



def carregar_aba(arquivo, nome_aba):
    """Localiza o cabeçalho dos produtos e lê os registros abaixo dele."""

    bruto = pd.read_excel(
        arquivo,
        sheet_name=nome_aba,
        header=None,
        engine="openpyxl"
    )

    if bruto.empty:
        return pd.DataFrame()

    # Procura a linha que contém o cabeçalho dos produtos
    linha_cabecalho = None
    coluna_codigo = None

    for indice_linha in range(len(bruto)):
        valores = bruto.iloc[indice_linha].tolist()

        for indice_coluna, valor in enumerate(valores):
            if pd.isna(valor):
                continue

            nome = normalizar(valor)

            if nome in ("COD PRODT", "CODIGO"):
                linha_cabecalho = indice_linha
                coluna_codigo = indice_coluna
                break

        if linha_cabecalho is not None:
            break

    if linha_cabecalho is None:
        raise ValueError(
            f"Não encontrei o cabeçalho dos produtos na aba '{nome_aba}'."
        )

    # Usa a linha encontrada como cabeçalho
    colunas = bruto.iloc[linha_cabecalho].tolist()

    # Trata colunas sem nome
    colunas = [
        str(valor).strip()
        if pd.notna(valor) and str(valor).strip()
        else f"Coluna_{i + 1}"
        for i, valor in enumerate(colunas)
    ]

    df = bruto.iloc[linha_cabecalho + 1:].copy()
    df.columns = colunas

    # Identifica a coluna de código pelo cabeçalho original
    nome_codigo = colunas[coluna_codigo]

    # Remove linhas sem código de produto
    codigos = df[nome_codigo].astype("string").str.strip()

    df = df[
        codigos.notna()
        & codigos.ne("")
        & codigos.str.lower().ne("nan")
    ].copy()

    return df.reset_index(drop=True)


def buscar_item(df, termo):
    termo = str(termo).strip().lower()

    mascara = df.astype(str).apply(
        lambda coluna: coluna.str.lower().str.contains(
            termo, regex=False, na=False
        )
    ).any(axis=1)

    return df[mascara]


def remover_pet(df):
    """Remove o segmento PET da análise, sem alterar a planilha original.

    Na planilha, o PET fica na coluna REF (o Segmento vem como
    "Copo PET", "Kit PET" etc.). A coluna Segmento também é conferida,
    caso alguma aba use "PET" nela.
    """
    eh_pet = pd.Series(False, index=df.index)

    for coluna in df.columns:
        if normalizar(coluna) in ("REF", "SEGMENTO"):
            eh_pet |= (
                df[coluna]
                .astype(str)
                .str.strip()
                .str.upper()
                .eq("PET")
            )

    return df[~eh_pet].copy()


def resumo_numerico(df, meta_doh=45):
    """Analisa estoque e DOH em relação à meta, ignorando o segmento PET."""

    df = remover_pet(df)

    def localizar_coluna(nome):
        alvo = normalizar(nome)
        for coluna in df.columns:
            if normalizar(coluna) == alvo:
                return coluna
        return None

    col_estoque = localizar_coluna("Estoque")
    col_demanda = localizar_coluna("Demanda")
    col_carteira = localizar_coluna("Carteira")
    col_doh = localizar_coluna("DOH TT")

    if col_estoque is None or col_demanda is None:
        print(
            "Não encontrei as colunas Estoque e Demanda "
            "nesta aba."
        )
        print("Colunas disponíveis:", list(df.columns))
        return

    if col_doh is None:
        print(
            "Não encontrei a coluna DOH TT. "
            "Precisamos configurar o cálculo para esta aba."
        )
        return

    estoque = pd.to_numeric(
        df[col_estoque], errors="coerce"
    )

    demanda = pd.to_numeric(
        df[col_demanda], errors="coerce"
    ).fillna(0)

    carteira = (
        pd.to_numeric(df[col_carteira], errors="coerce").fillna(0)
        if col_carteira is not None
        else pd.Series(0, index=df.index)
    )

    doh = pd.to_numeric(df[col_doh], errors="coerce")

    # Considera somente produtos com demanda positiva.
    # Como o DOH vem fracionado, "dentro da meta" é DOH >= meta
    # (mesma regra usada no plano de ação).
    validos = demanda > 0
    abaixo = validos & (doh < meta_doh)
    dentro = validos & (doh >= meta_doh)

    # Carteira pendente + estoque necessário para 45 dias de demanda
    estoque_meta = carteira + (demanda / 21) * meta_doh

    # Quantidade adicional necessária, arredondada para cima
    necessidade = (
        (estoque_meta - estoque)
        .clip(lower=0)
        .apply(
            lambda valor: math.ceil(valor)
            if pd.notna(valor) else 0
        )
    )
    resultado = df.copy()
    resultado["DOH analisado"] = doh

    resultado["Prioridade"] = "Dentro da meta"

    resultado.loc[
        doh.notna() & (doh <= 0),
        "Prioridade"
    ] = "CRÍTICA"

    resultado.loc[
        doh.notna() & (doh > 0) & (doh < 15),
        "Prioridade"
    ] = "ALTA"

    resultado.loc[
        doh.notna() & (doh >= 15) & (doh < meta_doh),
        "Prioridade"
    ] = "MÉDIA"

    resultado.loc[
        demanda <= 0,
        "Prioridade"
    ] = "SEM DEMANDA"

    resultado["Estoque para meta"] = estoque_meta
    resultado["Necessidade estimada"] = necessidade

    resultado["Status DOH"] = "Dentro ou acima da meta"
    resultado.loc[abaixo, "Status DOH"] = "ABAIXO DA META"
    resultado.loc[~validos, "Status DOH"] = "Sem demanda"

    print(f"\n=== ANÁLISE DE PCP | META DOH: {meta_doh} DIAS ===")
    print(f"Produtos analisados: {len(df)}")
    print(f"Abaixo da meta: {int(abaixo.sum())}")
    print(f"Dentro ou acima da meta: {int(dentro.sum())}")
    print(f"Sem demanda: {int((~validos).sum())}")

    # Identifica as colunas de identificação do produto
    identificacao = [
        coluna for coluna in df.columns
        if normalizar(coluna) in (
            "COD PRODT", "CODIGO", "SEGMENTO", "REF", "COR"
        )
    ]

    colunas_saida = identificacao + [
        col_estoque,
        col_demanda,
        col_doh,
        "Estoque para meta",
        "Necessidade estimada",
        "Status DOH",
    ]

    # Remove colunas duplicadas da seleção
    colunas_saida = list(dict.fromkeys(colunas_saida))

    criticos = resultado.loc[abaixo].copy()
    criticos = criticos.sort_values(
        by="DOH analisado",
        ascending=True
    )

    print("\n--- Produtos abaixo da meta de DOH ---")

    if criticos.empty:
        print("Nenhum produto com demanda está abaixo da meta.")
    else:
        print(
            criticos[colunas_saida]
            .head(30)
            .round(2)
            .to_string(index=False)
        )
        print(
            f"\nExibindo até 30 de {len(criticos)} produtos."
        )
