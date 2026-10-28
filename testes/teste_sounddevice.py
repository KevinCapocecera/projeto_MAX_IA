
import sounddevice as sd

dispositivo = 9  # Microfone Realtek - Windows WASAPI

try:
    info = sd.query_devices(dispositivo)
    print("Dispositivo:", info["name"])
    print("Taxa padrão:", info["default_samplerate"])

    wasapi = sd.WasapiSettings(exclusive=False)

    with sd.InputStream(
        device=dispositivo,
        samplerate=int(info["default_samplerate"]),
        channels=1,
        dtype="int16",
        extra_settings=wasapi
    ) as stream:
        print("Microfone aberto! Fale por 5 segundos.")

        for _ in range(50):
            stream.read(4800)

        print("Teste concluído!")

except Exception as erro:
    print(f"Erro: {type(erro).__name__}: {erro}")
