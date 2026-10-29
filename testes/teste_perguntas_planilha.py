"""Testa o MAX com perguntas sobre várias abas da planilha.

Usa a chave do Gemini do arquivo .env (gasta um pouco da cota) e mostra,
para cada pergunta, quais abas o MAX consultou e a resposta. Não mexe no
histórico nem na memória de ninguém.

Rodar na pasta do projeto:
    .venv/Scripts/python testes/teste_perguntas_planilha.py
Só algumas perguntas (pelos números):
    .venv/Scripts/python testes/teste_perguntas_planilha.py 1 5 8
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modulos import nucleo  # noqa: E402

PERGUNTAS = [
    "Quantas solicitações de compra estão aguardando e de quais fornecedores?",
    "Qual fornecedor tem a maior quantidade solicitada nas solicitações de compra?",
    "O que foi apontado de produção nos últimos 7 dias?",
    "Qual o lead time dos itens do fornecedor Sonho Encantado?",
    "Quanto vendemos de talher em setembro de 2026, por cor?",
    "Quais os 5 produtos com o estoque mais negativo no BD.ESTOQUE CARTEIRA?",
    "Qual é a prioridade de produção número 1 e a quantidade?",
    "Me fala tudo o que a planilha tem sobre o código TCCFRB-10.",
    "Como está a Fiesta?",
    "Qual a carteira do segmento PET na análise da Fiesta?",
]


def main():
    escolhidas = [int(n) for n in sys.argv[1:] if n.isdigit()] or range(1, len(PERGUNTAS) + 1)

    # A memória de longo prazo não é atualizada no teste (economiza cota).
    nucleo.Max.atualizar_memoria = lambda self, mensagens: None
    pasta = Path(tempfile.mkdtemp(prefix="max_teste_"))
    max_ = nucleo.Max(pasta=pasta, nome_usuario="Teste", modo_web=True)
    if not max_.configurada:
        raise SystemExit("Não encontrei GEMINI_API_KEY no arquivo .env.")

    for numero in escolhidas:
        pergunta = PERGUNTAS[numero - 1]
        max_.historico.clear()  # cada pergunta é independente
        print("\n" + "=" * 70)
        print(f"{numero}. {pergunta}")
        print("-" * 70, flush=True)
        inicio = time.time()
        try:
            resposta = max_.responder(pergunta)
        except Exception as erro:
            resposta = f"ERRO: {erro!r}"
        print("-" * 70)
        print(resposta)
        print(f"({time.time() - inicio:.1f} s)", flush=True)


if __name__ == "__main__":
    main()
