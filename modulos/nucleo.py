"""Cérebro do MAX, sem nenhuma interface.

Conversa com o Gemini (com as ferramentas de PCP), guarda o histórico e
consolida a memória de longo prazo. É usado pela janela nova
(max.py) e pela janela antiga em Tkinter (janela_chat.py), então
as duas respondem do mesmo jeito.
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from modulos import ferramentas_pcp
from modulos.ferramentas_pcp import FERRAMENTAS_PCP, contexto_pcp

# O SDK avisa no terminal que prefere function calling pelo chats.create;
# aqui o histórico já é montado à mão, então o aviso só polui a tela.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

ARQUIVO_HISTORICO = BASE_DIR / "historico.json"
ARQUIVO_MEMORIA = BASE_DIR / "memoria.json"

load_dotenv(BASE_DIR / ".env")

MODELO = "gemini-3.5-flash-lite"

INSTRUCOES = (
    "Seu nome é MAX. Você é um assistente pessoal "
    "inteligente, amigável, objetivo e natural. Converse em "
    "português brasileiro. Ajude o usuário com o PCP, "
    "programação, tecnologia, organização e ideias. Não afirme "
    "que executou ações que não realizou. Antes você se chamava "
    "SEXTA-FEIRA; mensagens antigas do histórico podem usar esse "
    "nome, mas agora você é o MAX."
)

DIAS_SEMANA = [
    "segunda-feira", "terça-feira", "quarta-feira",
    "quinta-feira", "sexta-feira", "sábado", "domingo",
]

MESES = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def data_hora_atual():
    """Data e hora do relógio do computador, por extenso."""
    agora = datetime.now()
    return (
        f"{DIAS_SEMANA[agora.weekday()]}, {agora.day} de "
        f"{MESES[agora.month - 1]} de {agora.year}, "
        f"{agora:%H:%M}"
    )


def _log(texto):
    print(f"[MAX] {texto}", flush=True)


def buscar_memorias(pergunta, memorias, limite=5):
    """Escolhe as memórias que têm palavras em comum com a pergunta."""
    palavras = {
        palavra.casefold().strip(".,!?;:()[]{}\"'")
        for palavra in pergunta.split()
        if len(palavra.strip(".,!?;:()[]{}\"'")) >= 3
    }

    resultados = []
    for item in memorias:
        texto = (item["categoria"] + " " + item["conteudo"]).casefold()
        pontuacao = sum(1 for palavra in palavras if palavra in texto)
        if pontuacao > 0:
            resultados.append((pontuacao, item))

    resultados.sort(key=lambda resultado: resultado[0], reverse=True)
    return [item for _, item in resultados[:limite]]


# ============================================================
# CLASSE PRINCIPAL
# ============================================================

# Qual Max está respondendo nesta thread. As ferramentas de PCP avisam
# todos os Max registrados quando leem a planilha; com várias pessoas
# usando o servidor ao mesmo tempo, só quem fez a pergunta deve reagir.
_atual = threading.local()


class Max:

    def __init__(self, pasta=None, nome_usuario=None, modo_web=False):
        """pasta: onde ficam historico.json e memoria.json desta pessoa
        (padrão: a pasta do projeto, como na versão de uma pessoa só).
        nome_usuario: nome de quem está conversando (vai para o prompt).
        modo_web: True quando o MAX roda no servidor (servidor.py)."""
        pasta = Path(pasta) if pasta else BASE_DIR
        pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo_historico = pasta / "historico.json"
        self.arquivo_memoria = pasta / "memoria.json"
        self.nome_usuario = nome_usuario
        self.modo_web = modo_web

        chave = os.getenv("GEMINI_API_KEY")
        self.client = (
            genai.Client(
                api_key=chave,
                http_options=types.HttpOptions(timeout=60000),
            )
            if chave
            else None
        )

        # Só mensagens "user" e "assistant"; as instruções vão no prompt.
        self.historico = []
        self.memoria = []
        self._trava = threading.Lock()

        # A interface pode definir esta função para saber, na hora,
        # quando uma ferramenta está lendo a planilha.
        self.ao_mudar_estado = None
        ferramentas_pcp.ao_consultar(self._avisar_consulta)

        self.carregar_memoria()
        self.carregar_historico()

    @property
    def configurada(self):
        return self.client is not None

    def _avisar_consulta(self, descricao):
        if getattr(_atual, "max", None) is not self:
            return
        if self.ao_mudar_estado is not None:
            self.ao_mudar_estado("consultando")

    # ========================================================
    # CONVERSA
    # ========================================================

    def responder(self, mensagem):
        """Responde à mensagem e devolve o texto do MAX.

        Fica esperando o Gemini, então deve rodar fora da thread da
        interface. Se algo der errado, levanta a exceção para a
        interface mostrar; o erro não é gravado no histórico.
        """
        mensagem = str(mensagem).strip()
        if not mensagem:
            raise ValueError("Digite uma mensagem.")
        if self.client is None:
            raise RuntimeError("Não encontrei GEMINI_API_KEY no arquivo .env.")

        with self._trava:
            self.historico.append({"role": "user", "content": mensagem})
            self.salvar_historico()
            recente = [item.copy() for item in self.historico[-12:]]
            memoria = [item.copy() for item in self.memoria]

        _log(f"Chamando modelo {MODELO}...")
        _atual.max = self
        try:
            texto = self._consultar_gemini(recente, memoria)
        except Exception as erro:
            _log(f"ERRO: {erro!r}")
            raise
        finally:
            _atual.max = None
        _log("Resposta recebida!")

        with self._trava:
            self.historico.append({"role": "assistant", "content": texto})
            self.salvar_historico()

        # A memória é consolidada em paralelo, sem atrasar a resposta.
        mensagens_usuario = [
            item["content"] for item in recente if item["role"] == "user"
        ]
        threading.Thread(
            target=self.atualizar_memoria,
            args=(mensagens_usuario,),
            daemon=True,
        ).start()

        return texto

    def _consultar_gemini(self, recente, memoria):
        pergunta_atual = next(
            (
                item["content"]
                for item in reversed(recente)
                if item["role"] == "user"
            ),
            "",
        )

        memoria_texto = "\n".join(
            f"- [{item['categoria']}] {item['conteudo']}"
            for item in buscar_memorias(pergunta_atual, memoria)
        )

        conversa = "\n".join(
            f"{'Você' if item['role'] == 'user' else 'MAX'}: "
            f"{item['content']}"
            for item in recente
        )

        extras = ""
        if self.nome_usuario:
            extras += f"Você está conversando com {self.nome_usuario}. "
        if self.modo_web:
            extras += (
                "Você roda num servidor da empresa e cada pessoa abre "
                "pelo navegador. Quando exportar um plano de ação, não "
                "cite o caminho do arquivo: diga que o botão para baixar "
                "aparece logo abaixo da resposta. "
            )

        entrada = (
            f"{INSTRUCOES}\n\n"
            f"{extras + chr(10) + chr(10) if extras else ''}"
            f"Data e hora atuais: {data_hora_atual()}. "
            "Esta é a sua única fonte de data e hora; use-a "
            "quando o usuário perguntar.\n\n"
            "Ferramentas de planilha: você tem acesso a TODAS as abas "
            "da planilha ANÁLISE DIÁRIA DE PROGRAMAÇÃO e das outras "
            "planilhas da pasta dados. Nunca invente números: sempre "
            "consulte as ferramentas.\n"
            "- DOH, cobertura, prioridade (crítica, alta, média), "
            "necessidade de produção e plano de ação: use resumo_pcp, "
            "listar_produtos_pcp, buscar_produto_pcp e "
            "exportar_plano_pcp. Nessas análises as quantidades estão "
            "em caixas e o PET fica de fora.\n"
            "- Qualquer outra informação, de qualquer aba (solicitações "
            "de compra, prioridades, apontamentos, base de vendas, "
            "fornecedores e lead time, estoque e carteira, insumos, "
            "bobinas, cores, trocas, colunas das abas de análise etc.): "
            "use listar_abas_planilha para ver as colunas da aba, "
            "consultar_aba para ver linhas e resumir_aba para somas, "
            "médias, contagens e rankings. Para achar um código ou "
            "descrição sem saber a aba, use buscar_na_planilha.\n"
            "Se uma ferramenta devolver erro com a lista de abas ou "
            "colunas, corrija o nome e tente de novo antes de responder. "
            "Diga de qual aba veio a informação. Se a pergunta servir "
            "para mais de uma aba e não der para escolher, pergunte. "
            f"{contexto_pcp()}\n\n"
            "Responda em texto simples, sem markdown, tabelas ou "
            "asteriscos, porque a janela não formata. Em listas de "
            "produtos, use uma linha por produto.\n\n"
            "Memórias de longo prazo sobre o usuário:\n"
            f"{memoria_texto or 'Nenhuma memória relevante.'}\n\n"
            "Use as memórias somente quando forem relevantes. "
            "Considere o histórico recente e priorize a última "
            "pergunta do usuário.\n\n"
            "Histórico recente da conversa:\n"
            f"{conversa}"
            "\n\nResponda à última mensagem do usuário."
        )

        # As ferramentas de PCP vão junto na consulta: o Gemini decide
        # se precisa delas e o SDK executa as funções Python sozinho
        # (function calling automático).
        resposta = self.client.models.generate_content(
            model=MODELO,
            contents=entrada,
            config=types.GenerateContentConfig(
                tools=FERRAMENTAS_PCP,
                automatic_function_calling=(
                    types.AutomaticFunctionCallingConfig(
                        maximum_remote_calls=10,
                    )
                ),
            ),
        )

        if resposta.function_calls:
            # Chegou ao limite de consultas sem fechar a resposta.
            return (
                "Não consegui fechar a resposta: precisei consultar "
                "a planilha mais vezes do que o limite. Tente "
                "perguntar de forma mais específica, citando a aba."
            )

        return resposta.text or "Não recebi uma resposta em texto."

    # ========================================================
    # MEMÓRIA
    # ========================================================

    def carregar_memoria(self):
        if not self.arquivo_memoria.exists():
            self.memoria = []
            self.salvar_memoria()
            _log("Arquivo memoria.json criado.")
            return

        try:
            dados = json.loads(self.arquivo_memoria.read_text(encoding="utf-8"))

            if not isinstance(dados, list):
                raise ValueError("O arquivo de memória deve conter uma lista.")

            self.memoria = [
                item for item in dados
                if isinstance(item, dict)
                and isinstance(item.get("categoria"), str)
                and isinstance(item.get("conteudo"), str)
            ]
            _log(f"{len(self.memoria)} memórias carregadas.")

        except (OSError, json.JSONDecodeError, ValueError) as erro:
            _log(f"Erro ao carregar memória: {erro}")
            self.memoria = []

    def salvar_memoria(self):
        try:
            self.arquivo_memoria.write_text(
                json.dumps(self.memoria, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _log("Memória salva com sucesso.")
        except OSError as erro:
            _log(f"Erro ao salvar memória: {erro}")

    def atualizar_memoria(self, mensagens_usuario):
        if not mensagens_usuario or self.client is None:
            return

        # Trabalha com uma cópia para preservar a memória atual
        # caso a API falhe ou devolva conteúdo inválido.
        with self._trava:
            memoria_atual = [item.copy() for item in self.memoria]

        try:
            prompt = (
                "Você é o módulo de memória do MAX.\n"
                "Consolide memórias de longo prazo.\n\n"
                "Regras:\n"
                "1. Preserve fatos úteis e ainda válidos.\n"
                "2. Adicione fatos novos úteis no futuro.\n"
                "3. Corrija fatos quando o usuário corrigir "
                "claramente uma informação anterior.\n"
                "4. Não misture projetos diferentes.\n"
                "5. Não remova memórias apenas por não serem "
                "mencionadas nas mensagens recentes.\n"
                "6. Não invente fatos.\n"
                "7. Não registre senhas, chaves de API ou dados "
                "pessoais sensíveis.\n"
                "8. Evite duplicatas e contradições.\n"
                "9. Não registre a data ou a hora atual, nem fatos "
                "que só valem para hoje (como 'hoje é...'); a data "
                "atual é informada à parte em cada conversa.\n\n"
                "Responda SOMENTE com uma lista JSON válida, "
                "sem markdown, contendo a lista completa "
                "e consolidada de memórias.\n"
                'Formato: [{"categoria":"projeto",'
                '"conteudo":"Descrição objetiva do fato"}]\n'
                "Se não houver memórias, responda [].\n\n"
                "Memórias atuais:\n"
                f"{json.dumps(memoria_atual, ensure_ascii=False)}\n\n"
                "Mensagens recentes do usuário:\n"
                + "\n".join(mensagens_usuario[-6:])
            )

            resposta = self.client.interactions.create(
                model=MODELO,
                input=prompt,
            )

            conteudo = (resposta.output_text or "").strip()
            conteudo = conteudo.replace("```json", "")
            conteudo = conteudo.replace("```", "").strip()

            novas_memorias = json.loads(conteudo)

            if not isinstance(novas_memorias, list):
                raise ValueError("A resposta da memória não é uma lista JSON.")

            memoria_consolidada = []
            vistos = set()

            for item in novas_memorias:
                if not isinstance(item, dict):
                    continue

                categoria = item.get("categoria")
                texto = item.get("conteudo")

                if not isinstance(categoria, str) or not isinstance(texto, str):
                    continue

                categoria = categoria.strip()
                texto = texto.strip()

                if not categoria or not texto:
                    continue

                chave = (categoria.casefold(), texto.casefold())
                if chave in vistos:
                    continue
                vistos.add(chave)

                memoria_consolidada.append({
                    "categoria": categoria,
                    "conteudo": texto,
                })

            # Não apaga uma memória existente se o modelo retornar
            # uma lista vazia inesperadamente.
            if memoria_atual and not memoria_consolidada:
                _log("Memória preservada: a consolidação retornou vazia.")
                return

            with self._trava:
                self.memoria = memoria_consolidada
                self.salvar_memoria()
            _log("Memória consolidada com sucesso.")

        except Exception as erro:
            _log(f"Não foi possível atualizar a memória: {erro}")

    # ========================================================
    # HISTÓRICO
    # ========================================================

    def salvar_historico(self):
        try:
            self.arquivo_historico.write_text(
                json.dumps(self.historico, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as erro:
            _log(f"Erro ao salvar histórico: {erro}")

    def carregar_historico(self):
        if not self.arquivo_historico.exists():
            return

        try:
            mensagens = json.loads(self.arquivo_historico.read_text(encoding="utf-8"))

            if not isinstance(mensagens, list):
                raise ValueError("Formato do histórico inválido.")

            self.historico = [
                item for item in mensagens
                if isinstance(item, dict)
                and item.get("role") in ("user", "assistant")
                and isinstance(item.get("content"), str)
            ]
            _log(f"{len(self.historico)} mensagens carregadas.")

        except (OSError, json.JSONDecodeError, ValueError) as erro:
            _log(f"Erro ao carregar histórico: {erro}")
