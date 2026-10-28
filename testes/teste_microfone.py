
import soundcard as sc
import time

print("Buscando microfone...", flush=True)

mic = sc.default_microphone()
print("Microfone selecionado:", mic.name, flush=True)

try:
    print("Gravando por 3 segundos. Fale alguma coisa!", flush=True)

    inicio = time.time()
    audio = mic.record(samplerate=48000, numframes=144000)

    print("Gravação concluída!", flush=True)
    print("Tempo:", round(time.time() - inicio, 2), "segundos")
    print("Formato:", audio.shape)
    print("Amplitude máxima:", abs(audio).max())

except Exception as erro:
    print("Erro durante a gravação:", repr(erro))
