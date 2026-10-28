import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

chave = os.getenv("GEMINI_API_KEY")

if not chave:
    print("ERRO: chave GEMINI_API_KEY não encontrada no .env")
    raise SystemExit(1)

try:
    cliente = genai.Client(
        api_key=chave,
        http_options=types.HttpOptions(timeout=60000),
    )

    print("Testando conexão com o Gemini...")

    resposta = cliente.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents="Responda somente: Olá, Kevin! Estou funcionando.",
    )

    print("\nRESPOSTA:")
    print(resposta.text)

except Exception as erro:
    print("\nERRO NO TESTE:")
    print(repr(erro))