
import pyaudio

audio = pyaudio.PyAudio()

dispositivos = [1, 5, 9, 14]
frequencias = [44100, 48000]

try:
    for indice in dispositivos:
        try:
            info = audio.get_device_info_by_index(indice)

            if info["maxInputChannels"] <= 0:
                continue

            print(f"\nTestando: {info['name']} | Índice {indice}")

            for frequencia in frequencias:
                for canais in [1, 2]:
                    try:
                        fluxo = audio.open(
                            format=pyaudio.paInt16,
                            channels=canais,
                            rate=frequencia,
                            input=True,
                            input_device_index=indice,
                            frames_per_buffer=1024
                        )

                        print(
                            f"SUCESSO: {frequencia} Hz, "
                            f"{canais} canal(is)"
                        )

                        fluxo.close()

                    except Exception as erro:
                        print(
                            f"Falhou: {frequencia} Hz, "
                            f"{canais} canal(is) - {erro}"
                        )

        except Exception as erro:
            print(f"Erro no dispositivo {indice}: {erro}")

finally:
    audio.terminate()
