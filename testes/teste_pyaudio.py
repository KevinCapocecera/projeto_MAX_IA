
import pyaudio

pa = pyaudio.PyAudio()
stream = None

try:
    print("Testando microfone Realtek...")

    info = pa.get_device_info_by_index(1)
    print("Dispositivo:", info["name"])
    print("Entradas disponíveis:", info["maxInputChannels"])
    print("Taxa padrão:", info["defaultSampleRate"])

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=48000,
        input=True,
        input_device_index=1,
        frames_per_buffer=1024
    )

    print("Microfone aberto! Fale por 5 segundos.")

    for _ in range(0, int(48000 / 1024 * 5)):
        dados = stream.read(1024, exception_on_overflow=False)

    print("Áudio capturado com sucesso!")

except Exception as erro:
    print(f"Erro: {type(erro).__name__}: {erro}")

finally:
    if stream is not None:
        stream.stop_stream()
        stream.close()

    pa.terminate()
