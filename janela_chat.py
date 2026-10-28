
import os
import json
import logging
import threading
from datetime import datetime
import tkinter as tk
from tkinter import scrolledtext, messagebox

from dotenv import load_dotenv
from google import genai
from google.genai import types

from modulos.ferramentas_pcp import FERRAMENTAS_PCP, contexto_pcp

# O SDK avisa no terminal que prefere function calling pelo chats.create;
# aqui o histórico já é montado à mão, então o aviso só polui a tela.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)


# ============================================================
# CONFIGURAÇÕES
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ARQUIVO_HISTORICO = os.path.join(BASE_DIR, "historico.json")
ARQUIVO_MEMORIA = os.path.join(BASE_DIR, "memoria.json")

load_dotenv(os.path.join(BASE_DIR, ".env"))

api_key = os.getenv("GEMINI_API_KEY")

client = (
    genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=60000),
    )
    if api_key
    else None
)

MODELO = "gemini-3.5-flash-lite"

INSTRUCOES = (
    "Seu nome é Max. Você é um assistente pessoal "
    "inteligente, amigável, objetiva e natural. Converse em "
    "português brasileiro. Ajude o usuário com o PCP, "
    "programação, tecnologia, organização e ideias. Não afirme "
    "que executou ações que não realizou."
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


# ============================================================
# CLASSE PRINCIPAL
# ============================================================

class SextaFeiraChat:

    def __init__(self, janela):
        self.janela = janela
        self.janela.title("Max | Assistente Pessoal")
        self.janela.geometry("850x650")
        self.janela.minsize(600, 450)
        self.janela.configure(bg="#101827")

        self.historico = [
            {
                "role": "system",
                "content": INSTRUCOES,
            }
        ]

        self.memoria = []

        self.carregar_memoria()
        self.carregar_historico()
        self.criar_interface()

    # ========================================================
    # MEMÓRIA
    # ========================================================

    def buscar_memorias(self, pergunta, limite=5):
        if not self.memoria or not pergunta.strip():
            return []

        palavras = {
            palavra.casefold().strip(".,!?;:()[]{}\"'")
            for palavra in pergunta.split()
            if len(
                palavra.strip(".,!?;:()[]{}\"'")
            ) >= 3
        }

        resultados = []

        for item in self.memoria:
            texto = (
                item["categoria"] + " " + item["conteudo"]
            ).casefold()

            pontuacao = sum(
                1 for palavra in palavras
                if palavra in texto
            )

            if pontuacao > 0:
                resultados.append((pontuacao, item))

        resultados.sort(
            key=lambda resultado: resultado[0],
            reverse=True,
        )

        return [
            item for pontuacao, item in resultados[:limite]
        ]

    def carregar_memoria(self):
        if not os.path.exists(ARQUIVO_MEMORIA):
            self.memoria = []
            self.salvar_memoria()
            print("[Max] Arquivo memoria.json criado.")
            return

        try:
            with open(
                ARQUIVO_MEMORIA, "r", encoding="utf-8"
            ) as arquivo:
                dados = json.load(arquivo)

            if not isinstance(dados, list):
                raise ValueError(
                    "O arquivo de memória deve conter uma lista."
                )

            self.memoria = [
                item for item in dados
                if isinstance(item, dict)
                and isinstance(item.get("categoria"), str)
                and isinstance(item.get("conteudo"), str)
            ]

            print(
                f"[Max] {len(self.memoria)} "
                "memórias carregadas.",
                flush=True,
            )

        except (OSError, json.JSONDecodeError, ValueError) as erro:
            print(
                f"[Max] Erro ao carregar memória: {erro}",
                flush=True,
            )
            self.memoria = []

    def salvar_memoria(self):
        try:
            with open(
                ARQUIVO_MEMORIA, "w", encoding="utf-8"
            ) as arquivo:
                json.dump(
                    self.memoria,
                    arquivo,
                    ensure_ascii=False,
                    indent=2,
                )

            print(
                "[Max] Memória salva com sucesso.",
                flush=True,
            )

        except OSError as erro:
            print(
                f"[Max] Erro ao salvar memória: {erro}",
                flush=True,
            )

    def atualizar_memoria(self, mensagens_usuario):
        if not mensagens_usuario or client is None:
            return

        # Trabalha com uma cópia para preservar a memória atual
        # caso a API falhe ou devolva conteúdo inválido.
        memoria_atual = [item.copy() for item in self.memoria]

        try:
            prompt = (
                "Você é o módulo de memória da Max.\n"
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

            resposta = client.interactions.create(
                model=MODELO,
                input=prompt,
            )

            conteudo = (resposta.output_text or "").strip()
            conteudo = conteudo.replace("```json", "")
            conteudo = conteudo.replace("```", "").strip()

            novas_memorias = json.loads(conteudo)

            if not isinstance(novas_memorias, list):
                raise ValueError(
                    "A resposta da memória não é uma lista JSON."
                )

            memoria_consolidada = []
            vistos = set()

            for item in novas_memorias:
                if not isinstance(item, dict):
                    continue

                categoria = item.get("categoria")
                texto = item.get("conteudo")

                if not isinstance(categoria, str):
                    continue

                if not isinstance(texto, str):
                    continue

                categoria = categoria.strip()
                texto = texto.strip()

                if not categoria or not texto:
                    continue

                chave = (
                    categoria.casefold(),
                    texto.casefold(),
                )

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
                print(
                    "[Max] Memória preservada: "
                    "a consolidação retornou vazia.",
                    flush=True,
                )
                return

            # A atualização da interface e a gravação em disco
            # são feitas pela thread principal do Tkinter.
            self.janela.after(
                0,
                self.aplicar_memoria,
                memoria_consolidada,
            )

        except Exception as erro:
            print(
                "[Max] Não foi possível atualizar "
                f"a memória: {erro}",
                flush=True,
            )

    def aplicar_memoria(self, nova_memoria):
        self.memoria = nova_memoria
        self.salvar_memoria()

        print(
            "[Max] Memória consolidada com sucesso.",
            flush=True,
        )

    # ========================================================
    # HISTÓRICO
    # ========================================================

    def salvar_historico(self):
        try:
            with open(
                ARQUIVO_HISTORICO, "w", encoding="utf-8"
            ) as arquivo:
                json.dump(
                    self.historico[1:],
                    arquivo,
                    ensure_ascii=False,
                    indent=2,
                )

        except OSError as erro:
            print(
                f"[Max] Erro ao salvar histórico: {erro}",
                flush=True,
            )

    def carregar_historico(self):
        if not os.path.exists(ARQUIVO_HISTORICO):
            return

        try:
            with open(
                ARQUIVO_HISTORICO, "r", encoding="utf-8"
            ) as arquivo:
                mensagens = json.load(arquivo)

            if not isinstance(mensagens, list):
                raise ValueError("Formato do histórico inválido.")

            mensagens_validas = [
                item for item in mensagens
                if isinstance(item, dict)
                and item.get("role") in ("user", "assistant")
                and isinstance(item.get("content"), str)
            ]

            self.historico.extend(mensagens_validas)

            print(
                f"[Max] {len(mensagens_validas)} "
                "mensagens carregadas.",
                flush=True,
            )

        except (OSError, json.JSONDecodeError, ValueError) as erro:
            print(
                f"[Max] Erro ao carregar histórico: {erro}",
                flush=True,
            )

    # ========================================================
    # INTERFACE
    # ========================================================

    def criar_interface(self):
        topo = tk.Frame(
            self.janela,
            bg="#172554",
            pady=15,
        )
        topo.pack(fill="x")

        tk.Label(
            topo,
            text="✦ Max",
            font=("Segoe UI", 20, "bold"),
            fg="#93C5FD",
            bg="#172554",
        ).pack()

        tk.Label(
            topo,
            text="SUA ASSISTENTE PESSOAL",
            font=("Segoe UI", 9),
            fg="#CBD5E1",
            bg="#172554",
        ).pack(pady=(4, 0))

        self.chat = scrolledtext.ScrolledText(
            self.janela,
            wrap=tk.WORD,
            font=("Segoe UI", 11),
            bg="#111827",
            fg="#F3F4F6",
            insertbackground="white",
            relief="flat",
            padx=15,
            pady=15,
            state="disabled",
        )
        self.chat.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=15,
        )

        self.chat.tag_config(
            "usuario",
            foreground="#93C5FD",
            font=("Segoe UI", 11, "bold"),
        )
        self.chat.tag_config(
            "sexta",
            foreground="#6EE7B7",
            font=("Segoe UI", 11, "bold"),
        )
        self.chat.tag_config(
            "texto",
            foreground="#F3F4F6",
            font=("Segoe UI", 11),
        )

        rodape = tk.Frame(
            self.janela,
            bg="#101827",
            padx=15,
            pady=10,
        )
        rodape.pack(fill="x")

        self.entrada = tk.Entry(
            rodape,
            font=("Segoe UI", 12),
            bg="#1F2937",
            fg="white",
            insertbackground="white",
            relief="flat",
        )
        self.entrada.pack(
            side="left",
            fill="x",
            expand=True,
            ipady=12,
            padx=(0, 10),
        )
        self.entrada.bind("<Return>", self.enviar)

        self.botao = tk.Button(
            rodape,
            text="Enviar",
            font=("Segoe UI", 11, "bold"),
            bg="#2563EB",
            fg="white",
            activebackground="#1D4ED8",
            activeforeground="white",
            relief="flat",
            padx=20,
            pady=10,
            command=self.enviar,
        )
        self.botao.pack(side="right")

        self.status = tk.Label(
            self.janela,
            text="Pronta para conversar",
            font=("Segoe UI", 9),
            fg="#9CA3AF",
            bg="#101827",
            anchor="w",
            padx=18,
            pady=5,
        )
        self.status.pack(fill="x")

        self.entrada.focus_set()

    def exibir_mensagem(self, autor, mensagem):
        self.chat.configure(state="normal")

        tag = "usuario" if autor == "Você" else "sexta"

        self.chat.insert(tk.END, f"{autor}\n", tag)
        self.chat.insert(tk.END, f"{mensagem}\n\n", "texto")

        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    # ========================================================
    # ENVIO E CONSULTA AO GEMINI
    # ========================================================

    def enviar(self, evento=None):
        mensagem = self.entrada.get().strip()

        if not mensagem:
            return

        if client is None:
            messagebox.showerror(
                "Configuração necessária",
                "Não encontrei GEMINI_API_KEY no arquivo .env.",
            )
            return

        self.entrada.delete(0, tk.END)
        self.exibir_mensagem("Você", mensagem)

        self.historico.append({
            "role": "user",
            "content": mensagem,
        })

        self.salvar_historico()

        self.botao.configure(state="disabled")
        self.entrada.configure(state="disabled")
        self.status.configure(text="Max está pensando...")

        # Copia o histórico para a thread trabalhar com um
        # contexto consistente.
        historico_copia = [
            item.copy() for item in self.historico
        ]
        memoria_copia = [
            item.copy() for item in self.memoria
        ]

        threading.Thread(
            target=self.consultar_gemini,
            args=(historico_copia, memoria_copia),
            daemon=True,
        ).start()

    def consultar_gemini(self, historico, memoria):
        try:
            print(
                f"[Max] Chamando modelo {MODELO}...",
                flush=True,
            )

            historico_recente = historico[1:][-12:]

            pergunta_atual = next(
                (
                    item["content"]
                    for item in reversed(historico_recente)
                    if item["role"] == "user"
                ),
                "",
            )

            # Seleciona memórias relevantes sem acessar a interface
            # a partir da thread de consulta.
            palavras = {
                palavra.casefold().strip(".,!?;:()[]{}\"'")
                for palavra in pergunta_atual.split()
                if len(
                    palavra.strip(".,!?;:()[]{}\"'")
                ) >= 3
            }

            memorias_relevantes = []

            for item in memoria:
                texto_memoria = (
                    item["categoria"] + " " + item["conteudo"]
                ).casefold()

                pontuacao = sum(
                    1 for palavra in palavras
                    if palavra in texto_memoria
                )

                if pontuacao > 0:
                    memorias_relevantes.append((pontuacao, item))

            memorias_relevantes.sort(
                key=lambda resultado: resultado[0],
                reverse=True,
            )

            memorias_relevantes = [
                item for pontuacao, item
                in memorias_relevantes[:5]
            ]

            memoria_texto = "\n".join(
                f"- [{item['categoria']}] {item['conteudo']}"
                for item in memorias_relevantes
            )

            conversa = []

            for item in historico_recente:
                autor = (
                    "Você"
                    if item["role"] == "user"
                    else "Max"
                )

                conversa.append(
                    f"{autor}: {item['content']}"
                )

            entrada = (
                f"{INSTRUCOES}\n\n"
                f"Data e hora atuais: {data_hora_atual()}. "
                "Esta é a sua única fonte de data e hora; use-a "
                "quando o usuário perguntar.\n\n"
                "Ferramentas de PCP: para perguntas sobre estoque, DOH, "
                "prioridades, necessidade, produtos ou plano de ação, "
                "use as ferramentas, que leem a planilha ANÁLISE DIÁRIA "
                "DE PROGRAMAÇÃO. Nunca invente números da planilha. Se "
                "não ficar claro de qual aba o usuário está falando, "
                "pergunte. As quantidades estão em caixas e o PET fica "
                "fora das análises. "
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
                + "\n".join(conversa)
                + "\n\nResponda à última mensagem do usuário."
            )

            # As ferramentas de PCP vão junto na consulta: o Gemini
            # decide se precisa delas e o SDK executa as funções
            # Python sozinho (function calling automático).
            resposta = client.models.generate_content(
                model=MODELO,
                contents=entrada,
                config=types.GenerateContentConfig(
                    tools=FERRAMENTAS_PCP,
                    automatic_function_calling=(
                        types.AutomaticFunctionCallingConfig(
                            maximum_remote_calls=6,
                        )
                    ),
                ),
            )

            if resposta.function_calls:
                # Chegou ao limite de consultas sem fechar a resposta.
                texto = (
                    "Não consegui fechar a resposta: precisei consultar "
                    "a planilha mais vezes do que o limite. Tente "
                    "perguntar de forma mais específica, citando a aba."
                )
            else:
                texto = (
                    resposta.text
                    or "Não recebi uma resposta em texto."
                )

            mensagens_usuario = [
                item["content"]
                for item in historico_recente
                if item["role"] == "user"
            ]

            print(
                "[Max] Resposta recebida!",
                flush=True,
            )

            # A resposta aparece sem esperar a consolidação
            # da memória.
            self.janela.after(
                0,
                self.finalizar_resposta,
                texto,
            )

            # A memória continua sendo atualizada em paralelo.
            threading.Thread(
                target=self.atualizar_memoria,
                args=(mensagens_usuario,),
                daemon=True,
            ).start()

        except Exception as erro:
            print(
                f"[Max] ERRO: {erro!r}",
                flush=True,
            )

            self.janela.after(
                0,
                self.finalizar_resposta,
                f"Não consegui responder agora.\nDetalhes: {erro}",
            )

    # ========================================================
    # FINALIZAÇÃO DA RESPOSTA
    # ========================================================

    def finalizar_resposta(self, texto):
        self.exibir_mensagem("Max", texto)

        self.historico.append({
            "role": "assistant",
            "content": texto,
        })

        self.salvar_historico()

        self.botao.configure(state="normal")
        self.entrada.configure(state="normal")
        self.entrada.focus_set()
        self.status.configure(text="Pronta para conversar")


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == "__main__":
    janela = tk.Tk()
    app = SextaFeiraChat(janela)

    print(
        "Método finalizar_resposta encontrado:",
        hasattr(app, "finalizar_resposta"),
    )
    print(
        "Método atualizar_memoria encontrado:",
        hasattr(app, "atualizar_memoria"),
    )

    janela.mainloop()
