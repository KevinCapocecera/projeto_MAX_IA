"""Confere uma lista de itens (de um PDF, de uma mensagem...) no estoque do ERP.

A MAX lê o documento, monta a lista "código ou descrição; quantidade" e
chama conferir(). Quem acha cada item e faz as contas é o Python:

1. código igual ao do ERP (sem diferença de maiúsculas e espaços);
2. GTIN/EAN (o código de barras de 13 dígitos);
3. código igual ignorando "-", "." e "/" (TBFCRC20-50F = TBFCRC2050F);
4. um pedaço da linha que seja um código ("TCSAZP 50 COLHER AZUL");
5. código cortado ("TCSAZP" -> TCSAZP-50), desempatado pela descrição;
6. descrição: o produto do ERP com mais palavras em comum.
Os casos 5 e 6 voltam como "provável", com outras opções quando há,
para a MAX pedir confirmação ao usuário.

Itens com o mesmo código no documento têm as quantidades somadas antes
de comparar com o estoque.
"""

import difflib
import math
import re

from modulos import planilhas


SEPARADORES = re.compile(r"\s*[;|\t]\s*")
NOTA_MINIMA = 0.6          # fração das palavras da descrição achadas no nome do ERP
LIMITE_ITENS = 300
PALAVRAS_IGNORADAS = {"de", "da", "do", "das", "dos", "com", "c", "e", "un", "und", "cx", "pct"}


def _codigo(texto):
    return re.sub(r"\s+", "", str(texto or "")).upper()


def _codigo_solto(texto):
    return re.sub(r"[\s\-./]", "", str(texto or "")).upper()


def _gtin(valor):
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return ""
    if isinstance(valor, float):
        valor = f"{valor:.0f}"
    digitos = re.sub(r"\D", "", str(valor))
    return digitos.lstrip("0")


def _palavras(texto):
    return [
        p for p in re.findall(r"[a-z0-9]+", planilhas.normalizar(texto).lower())
        if p not in PALAVRAS_IGNORADAS
    ]


def _quantidade(texto):
    if texto is None or not str(texto).strip():
        return None
    valor = planilhas._numeros(planilhas.pd.Series([str(texto).strip()])).iloc[0]
    return None if math.isnan(valor) else valor


def ler_itens(texto):
    """'código ou descrição; quantidade' por linha -> [(termo, quantidade|None)]."""
    itens = []
    for linha in str(texto or "").splitlines():
        linha = linha.strip().lstrip("-•*").strip()
        if not linha:
            continue
        partes = SEPARADORES.split(linha)
        termo = partes[0].strip()
        quantidade = _quantidade(partes[-1]) if len(partes) > 1 else None
        if termo:
            itens.append((termo, quantidade))
    return itens[:LIMITE_ITENS]


class _Estoque:
    """Índices do relatório de estoque do ERP para achar os itens rápido."""

    def __init__(self, df):
        self.df = df.reset_index(drop=True)
        self.codigo = {}
        self.solto = {}
        self.gtin = {}
        self.palavras = []
        tem_gtin = "GTIN-13" in df.columns
        for i, linha in self.df.iterrows():
            self.codigo.setdefault(_codigo(linha["Código"]), i)
            self.solto.setdefault(_codigo_solto(linha["Código"]), i)
            if tem_gtin and _gtin(linha["GTIN-13"]):
                self.gtin.setdefault(_gtin(linha["GTIN-13"]), i)
            self.palavras.append(set(_palavras(linha.get("Nome", ""))))

    def achar(self, termo):
        """(índice, como achou, [outras opções]) ou (None, motivo, opções)."""
        for indice, como in (
            (self.codigo.get(_codigo(termo)), "código"),
            (self.gtin.get(_gtin(termo)) if len(_gtin(termo)) >= 8 else None, "código de barras"),
            (self.solto.get(_codigo_solto(termo)), "código"),
        ):
            if indice is not None:
                return indice, como, []

        # "TCSAZP 50 COLHER SOBREMESA AZUL": código e descrição juntos.
        pedacos = str(termo).split()
        for tamanho in (2, 1):
            for inicio in range(len(pedacos) - tamanho + 1):
                pedaco = "".join(pedacos[inicio:inicio + tamanho])
                indice = self.codigo.get(_codigo(pedaco))
                if indice is None:
                    indice = self.solto.get(_codigo_solto(pedaco))
                if indice is None and pedaco.isdigit() and len(pedaco) >= 8:
                    indice = self.gtin.get(_gtin(pedaco))
                if indice is not None:
                    return indice, "código", []

        notas = self._notas_da_descricao(_palavras(termo))

        # Código cortado ("TCSAZP" para TCSAZP-50): os códigos que começam assim.
        inicio = _codigo_solto(pedacos[0]) if pedacos else ""
        if len(inicio) >= 4:
            parecidos = [i for codigo, i in self.solto.items() if codigo.startswith(inicio)]
            if parecidos:
                nota_de = {i: (nota, desempate) for nota, desempate, i in notas}

                def ordem(i):
                    # TCSAZP: TCSAZP-50 (o código continua depois de um traço
                    # ou número) vem antes de TCSAZPP-50; depois, a descrição.
                    resto = _codigo(self.df.iloc[i]["Código"])[len(_codigo(pedacos[0])):]
                    na_divisa = not resto or not resto[0].isalpha()
                    return (na_divisa, nota_de.get(i, (0, 0)), -len(resto))

                parecidos.sort(key=ordem, reverse=True)
                return parecidos[0], "código parecido (provável)", parecidos[1:4]

        if not notas:
            return None, "não encontrado", []
        opcoes = [i for nota, _, i in notas[:4] if nota >= NOTA_MINIMA]
        if not opcoes:
            return None, "não encontrado", [i for _, _, i in notas[:3]]
        melhor = notas[0]
        empatados = [i for nota, _, i in notas[1:4] if nota >= melhor[0] - 0.01 and nota >= NOTA_MINIMA]
        return melhor[2], "descrição (provável)", empatados

    def _notas_da_descricao(self, procuradas):
        """[(fração das palavras achadas, semelhança, índice)], da melhor para a pior."""
        if not procuradas:
            return []
        notas = []
        for i, palavras in enumerate(self.palavras):
            achadas = sum(1 for p in procuradas if p in palavras)
            if not achadas:
                continue
            nota = achadas / len(procuradas)
            desempate = difflib.SequenceMatcher(
                None, " ".join(procuradas), " ".join(sorted(palavras))
            ).ratio()
            notas.append((nota, desempate, i))
        notas.sort(reverse=True)
        return notas


def _produto(df, i):
    linha = df.iloc[i]
    return f"{linha['Código']} - {linha.get('Nome', '')}".strip(" -")


def _numero(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(numero) else numero


def _bonito(numero):
    return int(numero) if float(numero).is_integer() else round(numero, 2)


def conferir(itens_texto, tabela_estoque):
    """Compara cada item com a coluna Quantidade do estoque do ERP."""
    itens = ler_itens(itens_texto)
    if not itens:
        return {"erro": "Mande os itens, um por linha, no formato 'código ou descrição; quantidade'."}

    estoque = _Estoque(tabela_estoque.df)
    df = estoque.df
    achados = {}       # índice no estoque -> item
    resultado = []
    for termo, quantidade in itens:
        indice, como, opcoes = estoque.achar(termo)
        if indice is None:
            item = {"item_do_documento": termo, "situacao": "não encontrado no ERP"}
            if quantidade is not None:
                item["quantidade_pedida"] = _bonito(quantidade)
            if opcoes:
                item["parecidos"] = [_produto(df, i) for i in opcoes]
            resultado.append(item)
            continue
        if indice in achados:   # mesmo produto em outra linha: soma
            item = achados[indice]
            item["linhas_no_documento"] += 1
            if quantidade is not None:
                item["_pedida"] = (item["_pedida"] or 0) + quantidade
            continue
        linha = df.iloc[indice]
        item = {
            "item_do_documento": termo,
            "codigo": linha["Código"],
            "produto": linha.get("Nome", ""),
            "achado_por": como,
            "estoque_erp": _bonito(_numero(linha.get("Quantidade"))),
            "linhas_no_documento": 1,
            "_pedida": quantidade,
        }
        if not planilhas._vazio(linha.get("Segmento")):
            item["segmento"] = linha["Segmento"]
        if opcoes:
            item["outras_opcoes"] = [_produto(df, i) for i in opcoes]
        achados[indice] = item
        resultado.append(item)

    contagem = {}
    for item in resultado:
        if "codigo" in item:
            pedida = item.pop("_pedida")
            disponivel = _numero(item["estoque_erp"])
            if item["linhas_no_documento"] == 1:
                del item["linhas_no_documento"]
            if pedida is None:
                item["situacao"] = "tem estoque" if disponivel > 0 else "sem estoque"
            else:
                item["quantidade_pedida"] = _bonito(pedida)
                if disponivel >= pedida:
                    item["situacao"] = "tem estoque"
                    item["sobra"] = _bonito(disponivel - pedida)
                elif disponivel > 0:
                    item["situacao"] = "estoque parcial"
                    item["falta"] = _bonito(pedida - disponivel)
                else:
                    item["situacao"] = "sem estoque"
                    item["falta"] = _bonito(pedida)
        contagem[item["situacao"]] = contagem.get(item["situacao"], 0) + 1

    return {
        "estoque_de": f"{tabela_estoque.nome} ({tabela_estoque.arquivo})",
        "itens_conferidos": len(resultado),
        "por_situacao": contagem,
        "itens": resultado,
        "atencao": (
            "O ERP não diz a unidade da Quantidade. Se o documento estiver em "
            "outra unidade (unidades x caixas), avise o usuário antes de "
            "concluir. Itens 'descrição (provável)' precisam de confirmação."
        ),
    }
