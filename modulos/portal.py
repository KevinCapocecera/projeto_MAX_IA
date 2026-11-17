"""Leitura do BelloPortal (portal.bellocopo.com.br): previsões e estoque.

O portal é um site em React; os dados vêm da API api-portal.bellocopo.com.br.
A MAX entra com o usuário de serviço do .env e lê só as telas
"Previsão de Produtos" e "Previsão de Insumos" do menu Produção, cada uma
nos dois Tipos: Descartáveis (festa=false) e Festa (festa=true). Um item
de Descartáveis não aparece em Festa e vice-versa.

Só LÊ: as únicas chamadas são o login e as da lista CHAMADAS_PERMITIDAS.
Nunca usa "Atualizar pedidos", "Recalcular estoque inicial" nem qualquer
tela que grave alguma coisa no portal.

Configuração no .env:
    PORTAL_USUARIO=...     e-mail do usuário de serviço do portal
    PORTAL_SENHA=...       senha dele
    PORTAL_API=...         (opcional) outro endereço da API

Quem pode consultar (ERP_USUARIOS e ERP_SO_NESTE_PC) continua no erp.py.
"""

import os
import threading
import time
from datetime import date, datetime, timedelta

import httpx

API_PADRAO = "https://api-portal.bellocopo.com.br"
TEMPO_LIMITE = 60     # segundos
VALIDADE_MINUTOS = 10
DIAS_PARA_PREVER = 30

# (tela, festa) -> rótulo do Tipo, como aparece no portal
TIPOS = {False: "Descartáveis", True: "Festa"}
TELAS = ("produtos", "insumos")

LOGIN = "/usuarios/autenticar"
CHAMADAS_PERMITIDAS = {("GET", f"/previsoesEstoque/{tela}") for tela in TELAS}


class ErroPortal(RuntimeError):
    """Não deu para ler o portal; a mensagem já está pronta para o usuário."""


def configurado():
    return bool(os.getenv("PORTAL_USUARIO") and os.getenv("PORTAL_SENHA"))


# ============================================================
# CONEXÃO
# ============================================================

_cliente = None
_token = None
_trava_rede = threading.Lock()


def _novo_cliente():
    return httpx.Client(
        base_url=os.getenv("PORTAL_API", API_PADRAO).rstrip("/"),
        timeout=TEMPO_LIMITE,
        headers={"User-Agent": "MAX-PCP/1.0 (assistente interno de PCP)"},
    )


def _entrar(cliente):
    resposta = cliente.post(LOGIN, json={
        "email": os.getenv("PORTAL_USUARIO", ""),
        "senha": os.getenv("PORTAL_SENHA", ""),
    })
    token = resposta.json().get("token") if resposta.status_code == 200 else None
    if not token:
        raise ErroPortal(
            "Não consegui entrar no portal com o login do .env (PORTAL_USUARIO e "
            "PORTAL_SENHA). Confira se a senha mudou."
        )
    return token


def _requisitar(caminho, parametros):
    """JSON de uma chamada GET permitida; entra de novo se o token tiver expirado."""
    global _cliente, _token
    if ("GET", caminho) not in CHAMADAS_PERMITIDAS:
        raise ErroPortal(f"A MAX não tem permissão para GET {caminho} no portal.")
    if not configurado():
        raise ErroPortal("O portal não está configurado: faltam PORTAL_USUARIO e PORTAL_SENHA no arquivo .env.")
    with _trava_rede:
        try:
            if _cliente is None:
                _cliente = _novo_cliente()
            for tentativa in (1, 2):
                if _token is None:
                    _token = _entrar(_cliente)
                resposta = _cliente.get(caminho, params=parametros, headers={"x-access-token": _token})
                if resposta.status_code in (401, 403) and tentativa == 1:
                    _token = None   # token expirado: entra de novo e repete
                    continue
                if resposta.status_code >= 500:
                    raise ErroPortal(
                        f"O portal respondeu com erro {resposta.status_code}. Ele pode estar "
                        "fora do ar; tente de novo em alguns minutos."
                    )
                if resposta.status_code != 200:
                    raise ErroPortal(f"O portal recusou a consulta (resposta {resposta.status_code}).")
                return resposta.json()
        except httpx.TimeoutException:
            raise ErroPortal(f"O portal demorou mais de {TEMPO_LIMITE} segundos para responder.") from None
        except httpx.HTTPError as erro:
            raise ErroPortal(f"Não consegui me conectar ao portal: {erro}") from None
        except ValueError:
            raise ErroPortal("O portal mandou uma resposta que não consegui ler.") from None
    raise ErroPortal("O portal não aceitou o login do .env (PORTAL_USUARIO e PORTAL_SENHA).")


# ============================================================
# PREVISÕES
# ============================================================

_cache = {}   # (tela, festa) -> (momento, json)
_trava = threading.Lock()


def previsao(tela, festa):
    """JSON da Previsão de Produtos ou de Insumos de um Tipo, a partir de ontem.

    Devolve {"datas": ["aaaa-mm-dd", ...], "itens": [...], "atualizacao": {...},
    "momento": datetime}. Cada item tem codigo, nome, segmento, categoria,
    linha, unidade, media4m, carteira, numPedidos, separado e "quantidade",
    o saldo previsto de fim de dia, uma posição por data.
    """
    if tela not in TELAS:
        raise ErroPortal(f"Tela '{tela}' não existe. Use uma destas: {', '.join(TELAS)}.")
    chave = (tela, bool(festa))
    with _trava:
        item = _cache.get(chave)
    if item and time.time() - item[0].timestamp() < VALIDADE_MINUTOS * 60:
        return item[1]

    dados = _requisitar(f"/previsoesEstoque/{tela}", {
        "dias": DIAS_PARA_PREVER,
        "diasAnteriores": 1,   # a primeira coluna é ontem: o estoque atual
        "festa": "true" if festa else "false",
    })
    if not isinstance(dados, dict) or "itens" not in dados or "datas" not in dados:
        raise ErroPortal(f"O portal mandou a Previsão de {tela.capitalize()} num formato que não conheço.")
    dados["momento"] = datetime.now()
    with _trava:
        _cache[chave] = (dados["momento"], dados)
    return dados


def data_da_coluna(texto):
    """'2026-11-16' -> date(2026, 11, 16)."""
    return date.fromisoformat(str(texto)[:10])


def ontem(hoje=None):
    return (hoje or date.today()) - timedelta(days=1)


def estoque_inicial_calculado_em(dados):
    """Hora do último "Recalcular estoque inicial" do portal, no horário local, ou None."""
    texto = ((dados.get("atualizacao") or {}).get("calculoEstoqueInicial") or {}).get("concluidoEm")
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except ValueError:
        return None
