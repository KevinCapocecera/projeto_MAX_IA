# MAX na rede da empresa

Um computador da empresa (o **servidor**) fica com o MAX ligado. As outras pessoas abrem pelo navegador (Chrome ou Edge), sem instalar nada.

## 1. Preparar o servidor (uma vez só)

1. Instale o **Python 3.12** no servidor (em python.org, marque "Add Python to PATH").
2. Copie a pasta `projeto_MAX_IA` para o servidor, **sem** a pasta `.venv`.
3. Abra o terminal dentro da pasta e rode:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
   Os pacotes de voz (PyAudio, sounddevice, soundcard) não são usados pelo servidor. Se algum deles der erro na instalação, pode apagar essas linhas do `requirements.txt`.
4. Crie o arquivo `.env` na pasta com a chave do Gemini:
   ```
   GEMINI_API_KEY=sua_chave_aqui
   ```
5. Libere a porta 8000 no firewall do Windows. Abra o terminal **como administrador** e rode:
   ```
   netsh advfirewall firewall add rule name="MAX" dir=in action=allow protocol=TCP localport=8000 profile=domain,private
   ```

## 2. Ligar o MAX

Dê dois cliques em **`iniciar_servidor.bat`**. A janela mostra o endereço, por exemplo:

```
Nos outros da rede: http://192.168.0.50:8000
```

Mande esse endereço para as pessoas. Enquanto essa janela estiver aberta, o MAX funciona.

**Dica para a TI:** dê um IP fixo ao servidor, para o endereço não mudar. Para o MAX ligar sozinho quando o computador reiniciar, crie uma tarefa no Agendador de Tarefas do Windows que rode o `iniciar_servidor.bat` "Ao iniciar o sistema".

## 3. Atualizar a planilha

Substitua o arquivo em `dados\ANÁLISE DIÁRIA DE PROGRAMAÇÃO.xlsm` (mesmo nome). O MAX percebe a nova versão sozinho, sem precisar reiniciar. Também dá para colocar o caminho de uma pasta compartilhada da rede; peça ao Claude se quiser isso.

## Como funciona

- Cada pessoa digita o nome ao entrar. Histórico e memória ficam separados em `usuarios\<nome>\`. O navegador lembra o nome; para trocar, é só clicar no nome no canto de cima.
- Não tem senha: quem estiver na rede da empresa e souber o nome de outra pessoa consegue ver o histórico dela. Para a rede interna isso costuma bastar. Se precisar de senha, dá para acrescentar depois.
- A chave do Gemini fica só no servidor. Quem acessa não tem como vê-la.
- Todas as perguntas usam a mesma chave do Gemini, então o consumo é somado.
- Os planos de ação exportados aparecem como um botão **Baixar** embaixo da resposta.
- O `max.py` (a janela no seu PC) continua funcionando como antes.
- O servidor é só para a rede interna. Não abra a porta 8000 para a internet.

Para levar o seu histórico atual para o servidor, copie `historico.json` e `memoria.json` para `usuarios\<seu_nome>\` (o nome sem acentos, em minúsculas e com _ no lugar dos espaços; "João Silva" vira `usuarios\joao_silva\`) antes de entrar pela primeira vez.
