
import pyaudio

pa = pyaudio.PyAudio()

# Testar diferentes dispositivos e taxas
for dispositivo in [1, 5, 9, 14]:
    for taxa in [44100, 48000]:
        stream = None
        try:
            print(f"\nDispositivo {dispositivo} | Taxa {taxa}")

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=taxa,
                input=True,
                input_device_index=dispositivo,
                frames_per_buffer=1024
            )

            print("SUCESSO: microfone aberto!")
            print("Bytes lidos:", len(stream.read(
                1024, exception_on_overflow=False
            )))

        except Exception as erro:
            print("Falhou:", erro)

        finally:
            if stream is not None:
                stream.close()

pa.terminate()
