"""Senhas do site da MAX: cada pessoa entra com nome e senha.

A senha nunca é guardada. Em usuarios/<nome>/senha.json fica só um
resumo scrypt com sal (feito para ser lento de adivinhar por tentativa),
o nome como a pessoa escreveu e uma "versão", que muda a cada troca de
senha e derruba as sessões abertas com a senha antiga.

Primeiro acesso: quem entra com um nome que ainda não tem senha cria a
senha na hora. Esqueceu a senha? Quem cuida do MAX apaga o senha.json
da pessoa, e ela cria outra no próximo acesso (o histórico continua).

Depois de TENTATIVAS senhas erradas seguidas, o nome fica bloqueado
por BLOQUEIO_SEGUNDOS (só enquanto o servidor estiver ligado).
"""

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path


TAMANHO_MINIMO = 6
TENTATIVAS = 5
BLOQUEIO_SEGUNDOS = 300
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


class SenhaJaExiste(ValueError):
    """Este nome já tem senha: tem que entrar com ela, não criar outra."""


_trava = threading.Lock()


def identificador(nome):
    """'João da Silva' -> 'joao_da_silva': o nome da pasta da pessoa.

    Também é como os nomes são comparados (por exemplo, em ERP_USUARIOS):
    maiúsculas, acentos, espaços, hífens e apóstrofos não fazem diferença.
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", str(nome))
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")[:40]


def _arquivo(pasta):
    return Path(pasta) / "senha.json"


def _ler(pasta):
    try:
        return json.loads(_arquivo(pasta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _resumo(senha, sal, n, r, p):
    return hashlib.scrypt(
        senha.encode("utf-8"), salt=sal, n=n, r=r, p=p, maxmem=64 * 1024 * 1024, dklen=32
    ).hex()


def _gravar(pasta, nome, senha):
    if len(senha) < TAMANHO_MINIMO:
        raise ValueError(f"A senha precisa ter pelo menos {TAMANHO_MINIMO} caracteres.")
    sal = secrets.token_bytes(16)
    dados = {
        "nome": nome,
        "algoritmo": "scrypt",
        **SCRYPT,
        "sal": sal.hex(),
        "resumo": _resumo(senha, sal, **SCRYPT),
        "versao": secrets.token_hex(8),
        "alterada_em": datetime.now().isoformat(timespec="seconds"),
    }
    Path(pasta).mkdir(parents=True, exist_ok=True)
    _arquivo(pasta).write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def tem_senha(pasta):
    return _ler(pasta) is not None


def nome_cadastrado(pasta):
    """O nome como a pessoa escreveu ao criar a senha."""
    dados = _ler(pasta)
    return dados.get("nome") if dados else None


def versao(pasta):
    """Muda a cada troca de senha; None se a pessoa não tem senha."""
    dados = _ler(pasta)
    return dados.get("versao") if dados else None


def criar_senha(pasta, nome, senha):
    """Primeiro acesso. Recusa se o nome já tiver senha."""
    with _trava:
        if tem_senha(pasta):
            raise SenhaJaExiste("Este nome já tem senha. Entre com ela.")
        _gravar(pasta, nome, senha)


def trocar_senha(pasta, nova):
    with _trava:
        _gravar(pasta, nome_cadastrado(pasta), nova)


def conferir(pasta, senha):
    dados = _ler(pasta)
    if not dados:
        return False
    try:
        resumo = _resumo(senha, bytes.fromhex(dados["sal"]), dados["n"], dados["r"], dados["p"])
    except (KeyError, ValueError):
        return False
    return hmac.compare_digest(resumo, dados["resumo"])


# ============================================================
# BLOQUEIO DEPOIS DE MUITAS SENHAS ERRADAS
# ============================================================

_falhas = {}   # ident -> (quantas seguidas, momento da última)


def bloqueado(ident):
    """Segundos que ainda faltam de bloqueio (0 se pode tentar)."""
    with _trava:
        quantas, quando = _falhas.get(ident, (0, 0))
    if quantas < TENTATIVAS:
        return 0
    return max(0, int(quando + BLOQUEIO_SEGUNDOS - time.time()))


def registrar_falha(ident):
    with _trava:
        quantas, quando = _falhas.get(ident, (0, 0))
        if quantas >= TENTATIVAS and time.time() - quando >= BLOQUEIO_SEGUNDOS:
            quantas = 0   # o bloqueio anterior já passou: recomeça a contagem
        _falhas[ident] = (quantas + 1, time.time())


def limpar_falhas(ident):
    with _trava:
        _falhas.pop(ident, None)
