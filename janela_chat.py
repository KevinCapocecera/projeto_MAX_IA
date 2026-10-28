
"""Janela antiga (Tkinter) do MAX.

A interface nova é o max.py. Esta continua aqui como reserva e
usa o mesmo cérebro (modulos/nucleo.py), então responde do mesmo jeito.

Para rodar:  .venv/Scripts/python janela_chat.py
"""

import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox

from modulos.nucleo import Max


# ============================================================
# CLASSE PRINCIPAL
# ============================================================

class MaxChat:

    def __init__(self, janela):
        self.janela = janela
        self.janela.title("MAX | Assistente Pessoal")
        self.janela.geometry("850x650")
        self.janela.minsize(600, 450)
        self.janela.configure(bg="#101827")

        self.assistente = Max()
        # As ferramentas rodam em outra thread; a mudança de texto do
        # status é feita pela thread do Tkinter.
        self.assistente.ao_mudar_estado = (
            lambda estado: self.janela.after(0, self.mostrar_estado, estado)
        )

        self.criar_interface()

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
            text="✦ MAX",
            font=("Segoe UI", 20, "bold"),
            fg="#93C5FD",
            bg="#172554",
        ).pack()

        tk.Label(
            topo,
            text="SEU ASSISTENTE PESSOAL",
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
            "max",
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
            text="Pronto para conversar",
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

        tag = "usuario" if autor == "Você" else "max"

        self.chat.insert(tk.END, f"{autor}\n", tag)
        self.chat.insert(tk.END, f"{mensagem}\n\n", "texto")

        self.chat.configure(state="disabled")
        self.chat.see(tk.END)

    def mostrar_estado(self, estado):
        if estado == "consultando":
            self.status.configure(
                text="MAX está consultando a planilha..."
            )

    # ========================================================
    # ENVIO
    # ========================================================

    def enviar(self, evento=None):
        mensagem = self.entrada.get().strip()

        if not mensagem:
            return

        if not self.assistente.configurada:
            messagebox.showerror(
                "Configuração necessária",
                "Não encontrei GEMINI_API_KEY no arquivo .env.",
            )
            return

        self.entrada.delete(0, tk.END)
        self.exibir_mensagem("Você", mensagem)

        self.botao.configure(state="disabled")
        self.entrada.configure(state="disabled")
        self.status.configure(text="MAX está pensando...")

        threading.Thread(
            target=self.responder,
            args=(mensagem,),
            daemon=True,
        ).start()

    def responder(self, mensagem):
        try:
            texto = self.assistente.responder(mensagem)
        except Exception as erro:
            texto = f"Não consegui responder agora.\nDetalhes: {erro}"

        self.janela.after(0, self.finalizar_resposta, texto)

    def finalizar_resposta(self, texto):
        self.exibir_mensagem("MAX", texto)

        self.botao.configure(state="normal")
        self.entrada.configure(state="normal")
        self.entrada.focus_set()
        self.status.configure(text="Pronto para conversar")


# ============================================================
# INICIALIZAÇÃO
# ============================================================

if __name__ == "__main__":
    janela = tk.Tk()
    MaxChat(janela)
    janela.mainloop()
