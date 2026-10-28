
from pathlib import Path
from datetime import datetime
import re
import pandas as pd

from modulos.base_dados import normalizar, remover_pet


def calcular_plano(df, meta_doh=45):
    """Calcula o plano de ação de uma aba (sem PET), ordenado por prioridade.

    Devolve a mesma tabela que vai para o Excel. É usada pela opção 5
    do menu (main.py) e pelas ferramentas da Max no chat.
    """
    # Identifica colunas independentemente de maiúsculas e acentos
    def localizar_coluna(nome):
        alvo = nome.upper().strip()
        for coluna in df.columns:
            normalizada = (
                str(coluna).upper().strip()
                .replace("Á", "A")
                .replace("É", "E")
                .replace("Í", "I")
                .replace("Ó", "O")
                .replace("Ú", "U")
            )
            if normalizada == alvo:
                return coluna
        return None

    col_estoque = localizar_coluna("ESTOQUE")
    col_demanda = localizar_coluna("DEMANDA")
    col_carteira = localizar_coluna("CARTEIRA")
    col_doh = localizar_coluna("DOH TT")

    if col_estoque is None or col_demanda is None or col_doh is None:
        raise ValueError(
            "A aba precisa conter Estoque, Demanda e DOH TT."
        )

    # Remove o segmento PET da análise (na planilha ele fica na REF)
    resultado = remover_pet(df)

    estoque = pd.to_numeric(
        resultado[col_estoque], errors="coerce"
    ).fillna(0)

    demanda = pd.to_numeric(
        resultado[col_demanda], errors="coerce"
    ).fillna(0)

    carteira = (
        pd.to_numeric(
            resultado[col_carteira], errors="coerce"
        ).fillna(0)
        if col_carteira is not None
        else pd.Series(0, index=resultado.index)
    )

    doh = pd.to_numeric(
        resultado[col_doh], errors="coerce"
    )

    # Carteira pendente + demanda para 45 dias - estoque atual
    estoque_meta = carteira + (demanda / 21) * meta_doh
    necessidade = (
        (estoque_meta - estoque).clip(lower=0).apply(
            lambda valor: int(valor) if valor == int(valor)
            else int(valor) + 1
        )
    )

    resultado["DOH analisado"] = doh
    resultado["Estoque alvo"] = estoque_meta
    resultado["Necessidade estimada"] = necessidade

    resultado["Prioridade"] = "DENTRO DA META"
    resultado.loc[
        doh.notna() & (doh <= 0), "Prioridade"
    ] = "CRÍTICA"
    resultado.loc[
        doh.notna() & (doh > 0) & (doh < 15), "Prioridade"
    ] = "ALTA"
    resultado.loc[
        doh.notna() & (doh >= 15) & (doh < meta_doh),
        "Prioridade"
    ] = "MÉDIA"
    resultado.loc[
        demanda <= 0, "Prioridade"
    ] = "SEM DEMANDA"

    ordem = {
        "CRÍTICA": 0,
        "ALTA": 1,
        "MÉDIA": 2,
        "DENTRO DA META": 3,
        "SEM DEMANDA": 4,
    }

    resultado["_ordem"] = resultado["Prioridade"].map(ordem)
    resultado = resultado.sort_values(
        ["_ordem", "DOH analisado"],
        ascending=[True, True],
        na_position="last",
    ).drop(columns="_ordem")

    colunas_id = [
        c for c in resultado.columns
        if str(c).strip().upper() in
        ["COD PRODT", "CODIGO", "SEGMENTO", "REF", "COR"]
    ]

    colunas_saida = list(dict.fromkeys(
        colunas_id + [
            col_estoque,
            col_carteira,
            col_demanda,
            col_doh,
            "Estoque alvo",
            "Necessidade estimada",
            "Prioridade",
        ]
    ))
    colunas_saida = [
        c for c in colunas_saida if c is not None
    ]

    return resultado[colunas_saida].copy()


def salvar_plano(relatorio, nome_aba=None):
    """Grava o plano em Excel na pasta relatorios e devolve o caminho."""
    pasta_saida = Path(__file__).parent.parent / "relatorios"
    pasta_saida.mkdir(parents=True, exist_ok=True)

    # Com o nome da aba no arquivo, dois planos gerados no mesmo
    # segundo (o que pode acontecer pelo chat) não se sobrescrevem.
    sufixo = ""
    if nome_aba:
        nome = normalizar(nome_aba).replace("ANALISE", "")
        sufixo = "_" + re.sub(r"[^A-Z0-9-]+", "_", nome).strip("_")

    arquivo = pasta_saida / (
        f"Plano_Acao_PCP{sufixo}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    )

    with pd.ExcelWriter(arquivo, engine="openpyxl") as writer:
        relatorio.to_excel(
            writer, sheet_name="Plano de Acao", index=False
        )

        resumo = (
            relatorio["Prioridade"]
            .value_counts()
            .rename_axis("Prioridade")
            .reset_index(name="Quantidade de produtos")
        )
        resumo.to_excel(writer, sheet_name="Resumo", index=False)

        for planilha in writer.sheets.values():
            planilha.freeze_panes = "A2"
            planilha.auto_filter.ref = planilha.dimensions

            for coluna in planilha.columns:
                letra = coluna[0].column_letter
                largura = max(
                    len(str(celula.value or ""))
                    for celula in coluna
                )
                planilha.column_dimensions[letra].width = min(
                    largura + 2, 35
                )

    return arquivo


def exportar_plano_acao(df, meta_doh=45, nome_aba=None):
    """Calcula e exporta o plano de ação (opção 5 do menu)."""
    relatorio = calcular_plano(df, meta_doh=meta_doh)
    arquivo = salvar_plano(relatorio, nome_aba=nome_aba)
    print(f"\nPlano de ação exportado com sucesso:\n{arquivo.resolve()}")
    return arquivo
