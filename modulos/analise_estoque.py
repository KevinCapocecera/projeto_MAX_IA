
import pandas as pd
from pathlib import Path


def carregar_dados():
    """Carrega a planilha de previsão de estoque."""

    arquivo = (
        Path(__file__).parent.parent
        / "dados"
        / "Previsão de Estoque dos Produtos de Festa.xlsx"
    )

    if not arquivo.exists():
        raise FileNotFoundError(
            f"Planilha não encontrada: {arquivo}"
        )

    df = pd.read_excel(arquivo)

    # Padroniza nomes de colunas
    df.columns = [str(col).strip() for col in df.columns]

    # Converte colunas numéricas
    colunas_numericas = [
        "Média 4m",
        "Carteira",
        "Pedidos",
        "Separado",
    ]

    for coluna in colunas_numericas:
        if coluna in df.columns:
            df[coluna] = pd.to_numeric(
                df[coluna], errors="coerce"
            ).fillna(0)

    # Identifica as colunas que representam datas
    colunas_data = []

    for coluna in df.columns:
        data = pd.to_datetime(
            coluna,
            format="%d/%m/%Y",
            errors="coerce"
        )

        if pd.notna(data):
            colunas_data.append((data, coluna))

    # Ordena as datas cronologicamente
    colunas_data.sort(key=lambda item: item[0])

    for _, coluna in colunas_data:
        df[coluna] = pd.to_numeric(
            df[coluna], errors="coerce"
        )

    return df, [coluna for _, coluna in colunas_data]


def resumo_estoque(df, colunas_data):
    """Mostra um resumo da previsão de estoque."""

    if not colunas_data:
        return "Não encontrei colunas de estoque com datas."

    coluna_atual = colunas_data[0]
    estoque = df[coluna_atual].fillna(0)

    return (
        f"Data da previsão: {coluna_atual}\n"
        f"Produtos analisados: {len(df)}\n"
        f"Produtos com estoque negativo: {(estoque < 0).sum()}\n"
        f"Produtos com estoque zerado: {(estoque == 0).sum()}\n"
        f"Produtos com estoque positivo: {(estoque > 0).sum()}"
    )


def produtos_criticos(df, colunas_data):
    """Lista produtos com estoque projetado zero ou negativo."""

    if not colunas_data:
        return pd.DataFrame()

    coluna_atual = colunas_data[0]

    criticos = df[
        df[coluna_atual].fillna(0) <= 0
    ].copy()

    return criticos[
        ["Código", "Produto", coluna_atual]
    ].sort_values(
        by=coluna_atual,
        ascending=True
    )


def estoque_em_queda(df, colunas_data):
    """Identifica produtos cuja previsão diminui entre datas."""

    if len(colunas_data) < 2:
        return pd.DataFrame()

    data_seguinte = colunas_data[1]
    data_atual = colunas_data[0]

    resultado = df.copy()

    resultado["Variação prevista"] = (
        resultado[data_seguinte] - resultado[data_atual]
    )

    em_queda = resultado[
        resultado["Variação prevista"] < 0
    ].copy()

    return em_queda[
        [
            "Código",
            "Produto",
            data_seguinte,
            data_atual,
            "Variação prevista",
        ]
    ].sort_values(
        by="Variação prevista"
    )

def analisar_doh(df, colunas_data, meta_doh=45):
    """Compara a cobertura atual com a meta de DOH."""

    if not colunas_data:
        return pd.DataFrame()

    coluna_estoque = colunas_data[0]
    resultado = df.copy()

    estoque = pd.to_numeric(
        resultado[coluna_estoque], errors="coerce"
    ).fillna(0)

    media_mensal = pd.to_numeric(
        resultado["Média 4m"], errors="coerce"
    ).fillna(0)

    # Considera um mês padrão de 30 dias
    demanda_diaria = media_mensal / 30

    # Calcula os dias de cobertura
    resultado["DOH"] = float("inf")
    mascara = demanda_diaria > 0

    resultado.loc[mascara, "DOH"] = (
        estoque[mascara] / demanda_diaria[mascara]
    )

    # Estoque necessário para atingir 45 dias de cobertura
    resultado["Estoque meta DOH"] = (
        demanda_diaria * meta_doh
    )

    resultado["Necessidade estimada"] = (
        resultado["Estoque meta DOH"] - estoque
    ).clip(lower=0)

    resultado["Status DOH"] = "Dentro ou acima da meta"

    resultado.loc[
        resultado["DOH"] < meta_doh, "Status DOH"
    ] = "Abaixo da meta"

    resultado.loc[
        (demanda_diaria == 0) & (estoque <= 0),
        "Status DOH"
    ] = "Sem demanda média e sem estoque"

    resultado.loc[
        (demanda_diaria == 0) & (estoque > 0),
        "Status DOH"
    ] = "Sem demanda média"

    colunas = [
        "Código",
        "Produto",
        coluna_estoque,
        "Média 4m",
        "DOH",
        "Estoque meta DOH",
        "Necessidade estimada",
        "Status DOH",
    ]

    return resultado[colunas].sort_values(
        by="DOH",
        ascending=True,
    )
