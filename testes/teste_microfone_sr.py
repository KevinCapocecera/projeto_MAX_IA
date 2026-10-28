
import sys
import speech_recognition as sr

print("Python utilizado:", sys.executable)
print("Versão SpeechRecognition:", sr.__version__)

try:
    with sr.Microphone(device_index=1) as fonte:
        print("Microfone aberto! Fale por 5 segundos.")
        audio = sr.Recognizer().record(fonte, duration=5)
        print("Áudio capturado:", len(audio.frame_data), "bytes")

except Exception as erro:
    print(f"{type(erro).__name__}: {erro}")
