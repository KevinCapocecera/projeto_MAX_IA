
import speech_recognition as sr

INDICE_MICROFONE = 9

reconhecedor = sr.Recognizer()

try:
    microfone = sr.Microphone(
        device_index=INDICE_MICROFONE
    )

    print("Abrindo o microfone...")

    with microfone as fonte:
        reconhecedor.adjust_for_ambient_noise(
            fonte,
            duration=1
        )

        print("Pode falar agora!")

        audio = reconhecedor.listen(
            fonte,
            timeout=10,
            phrase_time_limit=8
        )

    print("Convertendo fala em texto...")

    texto = reconhecedor.recognize_google(
        audio,
        language="pt-BR"
    )

    print("Você disse:", texto)

except Exception as erro:
    print(f"Erro: {type(erro).__name__}: {erro}")
