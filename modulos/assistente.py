
import unicodedata
import pandas as pd

from modulos.base_dados import remover_pet


def normalizar(texto):
    texto = str(texto).strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def localizar_coluna(df, nome):
    alvo = normalizar(nome)
    for coluna in df.columns:
        if normalizar(coluna) == alvo:
            return coluna
    return None


def responder_pergunta(df, pergunta, meta_doh=45):
    pergunta_original = pergunta.strip()
    pergunta = normalizar(pergunta)

    if not pergunta_original:
        print("Digite uma pergunta para a Max.")
        return

    # Exclui PET das análises, sem modificar a planilha original
    # (na planilha, o PET fica na coluna REF)
    dados = remover_pet(df)

    col_estoque = localizar_coluna(dados, "Estoque")
    col_demanda = localizar_coluna(dados, "Demanda")
    col_carteira = localizar_coluna(dados, "Carteira")
    col_doh = localizar_coluna(dados, "DOH TT")

    # Pesquisa de produtos por código, referência, cor ou descrição.
    # Só vira busca com um verbo de busca ou quando a frase começa com
    # "produto"/"código"; assim "Quais produtos estão abaixo da meta?"
    # segue para a análise de DOH.
    verbos_busca = [
        "procure", "buscar", "busque", "pesquise",
        "encontre", "localize"
    ]

    if (
        any(verbo in pergunta for verbo in verbos_busca)
        or pergunta.startswith(("produto ", "codigo "))
    ):
        termo_busca = pergunta_original

        for separador in ["produto", "codigo", "código",
                          "procure", "buscar", "busque",
                          "pesquise", "encontre", "localize"]:
            if normalizar(separador) in pergunta:
                partes = pergunta_original.lower().split(separador, 1)
                if len(partes) > 1 and partes[1].strip():
                    termo_busca = partes[1].strip()
                    break

        termo_busca = termo_busca.strip(" ?!.,:")
        if not termo_busca:
            print("Informe o código ou nome do produto.")
            return

        mascara = dados.astype("string").apply(
            lambda coluna: coluna.str.contains(
                termo_busca, case=False, regex=False, na=False
            )
        ).any(axis=1)

        encontrados = dados[mascara]

        if encontrados.empty:
            print(f"Não encontrei o produto: {termo_busca}")
        else:
            print(f"\nEncontrei {len(encontrados)} resultado(s):")
            print(encontrados.head(20).to_string(index=False))
        return

    # Perguntas sobre DOH e estoque
    if col_doh is None or col_demanda is None or col_estoque is None:
        print(
            "Esta aba não possui todas as colunas necessárias "
            "para análise de DOH. Selecione uma aba de análise "
            "de produtos."
        )
        return

    estoque = pd.to_numeric(
        dados[col_estoque], errors="coerce"
    ).fillna(0)

    demanda = pd.to_numeric(
        dados[col_demanda], errors="coerce"
    ).fillna(0)

    carteira = (
        pd.to_numeric(dados[col_carteira], errors="coerce").fillna(0)
        if col_carteira is not None
        else pd.Series(0, index=dados.index)
    )

    doh = pd.to_numeric(dados[col_doh], errors="coerce")

    # Necessidade para atender à carteira e alcançar a meta de DOH
    estoque_alvo = carteira + (demanda / 21) * meta_doh
    necessidade = (
        (estoque_alvo - estoque).clip(lower=0).apply(
            lambda valor: int(valor) + (valor % 1 > 0)
        )
    )

    dados["DOH analisado"] = doh
    dados["Necessidade estimada"] = necessidade

    validos = demanda > 0
    abaixo = validos & doh.notna() & (doh < meta_doh)
    criticos = validos & doh.notna() & (doh <= 0)
    acima = validos & doh.notna() & (doh >= meta_doh)

    identificacao = [
        coluna for coluna in dados.columns
        if normalizar(coluna) in (
            "cod prodt", "codigo", "segmento", "ref", "cor"
        )
    ]

    colunas_saida = list(dict.fromkeys(
        identificacao + [
            col_estoque, col_carteira, col_demanda, col_doh,
            "DOH analisado", "Necessidade estimada"
        ]
    ))
    colunas_saida = [
        coluna for coluna in colunas_saida if coluna is not None
    ]

    if "necessidade total" in pergunta or "quanto preciso" in pergunta:
        total = necessidade[validos].sum()
        print(
            f"Necessidade estimada total: {int(total)} unidades."
        )
        print(
            "O cálculo considera carteira + demanda para "
            f"{meta_doh} dias - estoque atual."
        )
        return

    if "sem demanda" in pergunta:
        resultado = dados[demanda <= 0]
        print(f"Produtos sem demanda: {len(resultado)}")
        print(resultado[colunas_saida].head(30).to_string(index=False))
        return

    if "acima da meta" in pergunta or "acima de 45" in pergunta:
        resultado = dados[acima].sort_values(
            by="DOH analisado", ascending=False
        )
        print(f"Produtos dentro ou acima da meta: {len(resultado)}")
        print(resultado[colunas_saida].head(30).to_string(index=False))
        return

    if "abaixo de 15" in pergunta or "menos de 15" in pergunta:
        resultado = dados[
            validos & doh.notna() & (doh < 15)
        ].sort_values("DOH analisado")
        print(f"Produtos com menos de 15 dias de DOH: {len(resultado)}")
        print(resultado[colunas_saida].head(30).to_string(index=False))
        return

    if "mais criticos" in pergunta or "mais criticas" in pergunta:
        resultado = dados[abaixo].sort_values("DOH analisado")
        print("Produtos mais críticos:")
        print(resultado[colunas_saida].head(10).to_string(index=False))
        return

    if "critico" in pergunta or "critica" in pergunta:
        resultado = dados[criticos].sort_values("DOH analisado")
        print(f"Produtos com DOH crítico: {len(resultado)}")
        print(resultado[colunas_saida].head(30).to_string(index=False))
        return

    if "abaixo da meta" in pergunta or "abaixo de 45" in pergunta:
        resultado = dados[abaixo].sort_values("DOH analisado")
        print(f"Produtos abaixo da meta de {meta_doh} dias: {len(resultado)}")
        print(resultado[colunas_saida].head(30).to_string(index=False))
        return

    if "ajuda" in pergunta or "o que voce pode fazer" in pergunta:
        print("""
Posso responder perguntas como:
- Quais produtos estão abaixo da meta?
- Quais produtos estão abaixo de 15 dias?
- Quais são os produtos críticos?
- Mostre os 10 produtos mais críticos.
- Quais produtos estão acima da meta?
- Qual é a necessidade total?
- Quais produtos estão sem demanda?
- Procure o produto PRB-21.
""")
        return

    print(
        "Ainda não reconheci essa pergunta. Digite 'ajuda' "
        "para ver exemplos do que consigo analisar."
    )
