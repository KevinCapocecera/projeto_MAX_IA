"""MAX com a interface nova (interface/index.html).

Abre a página numa janela do Windows com o pywebview e liga a página ao
Python: as perguntas vão para o Gemini com as ferramentas de PCP, o
quadro "Estoque por aba" vem da planilha de verdade, e o painel de LED
mostra quando a planilha está sendo consultada.

Para rodar:
    .venv/Scripts/python max.py
Com as ferramentas de desenvolvedor da página (para investigar erros):
    .venv/Scripts/python max.py --debug
"""

import json
import sys
from pathlib import Path

try:
    import webview
except ImportError:
    print(
        "O pywebview não está instalado nesta venv. Rode:\n"
        "    .venv/Scripts/python -m pip install -r requirements.txt\n"
        "Enquanto isso, a janela antiga funciona com:\n"
        "    .venv/Scripts/python janela_chat.py"
    )
    raise SystemExit(1)

from modulos import ferramentas_pcp
from modulos.nucleo import Max


PASTA = Path(__file__).resolve().parent
PAGINA = PASTA / "interface" / "index.html"


class Ponte:
    """Funções que a página chama por window.pywebview.api.

    O pywebview roda cada chamada numa thread separada, então a janela
    não trava enquanto o Gemini pensa. Atributos que começam com "_"
    não ficam visíveis para a página.
    """

    def __init__(self, assistente):
        self._assistente = assistente
        self._janela = None
        assistente.ao_mudar_estado = self._mostrar_estado

    def perguntar(self, texto):
        """Envia a pergunta ao MAX e devolve {"texto": resposta}."""
        return {"texto": self._assistente.responder(texto)}

    def painel(self):
        """Resumo das abas para o quadro "Estoque por aba"."""
        return ferramentas_pcp.painel()

    def _mostrar_estado(self, estado):
        """Muda o painel de LED (ex.: "consultando") enquanto o Python trabalha."""
        if self._janela is None:
            return
        self._janela.run_js(
            "try { window.assistente && window.assistente.estado("
            + json.dumps(estado)
            + "); } catch (erro) {}"
        )


def main():
    if not PAGINA.exists():
        print(f"Não encontrei a interface em {PAGINA}.")
        print("Coloque o index.html dentro da pasta 'interface' do projeto.")
        raise SystemExit(1)

    assistente = Max()
    if not assistente.configurada:
        print("[MAX] Aviso: não encontrei GEMINI_API_KEY no arquivo .env.")

    ponte = Ponte(assistente)
    janela = webview.create_window(
        "MAX",
        # "#app" avisa a página que ela está no programa, não no navegador
        # (assim ela nunca entra no modo demonstração).
        url=PAGINA.as_uri() + "#app",
        js_api=ponte,
        width=1200,
        height=800,
        min_size=(720, 560),
        background_color="#191E22",
        text_select=True,  # permite copiar códigos e respostas
    )
    ponte._janela = janela

    # private_mode=False guarda a escolha de tema entre uma vez e outra.
    webview.start(debug="--debug" in sys.argv, private_mode=False)


if __name__ == "__main__":
    main()
