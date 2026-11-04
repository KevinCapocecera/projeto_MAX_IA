# MAX na rede da empresa (rodando no seu PC)

O seu PC fica com o MAX ligado e as outras pessoas abrem pelo navegador (Chrome ou Edge), sem instalar nada. O MAX só funciona enquanto o seu PC estiver ligado, conectado à rede da empresa e com a janela do MAX aberta.

## 1. Preparar (uma vez só)

1. Na pasta do projeto, instale os dois pacotes novos na `.venv` que você já tem:
   ```
   .venv\Scripts\python -m pip install flask==3.1.3 waitress==3.0.2
   ```
   O `.env` com a chave do Gemini e a planilha em `dados\` já estão no seu PC; não precisa mexer neles.

2. Libere a porta 8000 no firewall do Windows. Abra o terminal **como administrador** e rode:
   ```
   netsh advfirewall firewall add rule name="MAX" dir=in action=allow protocol=TCP localport=8000 profile=domain,private
   ```
   Se o notebook da empresa não deixar abrir como administrador, peça esse comando para a TI.

3. Confira se o Windows trata a rede da empresa como **rede privada ou de domínio**. Vá em Configurações > Rede e Internet e veja o tipo da rede conectada. Se aparecer **Pública**, o Windows bloqueia quem tenta acessar o MAX. Troque para **Privada** ou peça para a TI.

4. Para levar o seu histórico atual para o modo rede, copie `historico.json` e `memoria.json` da pasta do projeto para `usuarios\<seu_nome>\` antes de entrar pela primeira vez. O nome da pasta é o seu nome sem acentos, em minúsculas e com _ no lugar dos espaços: "João Silva" vira `usuarios\joao_silva\`.

## 2. Ligar o MAX

Dê dois cliques em **`iniciar_servidor.bat`**. A janela mostra os endereços:

```
Neste computador:   http://localhost:8000
Nos outros da rede: http://laptop-xxxx:8000
         ou então:  http://192.168.0.50:8000
```

Mande para as pessoas o endereço com o **nome do PC**. Ele continua valendo mesmo que o IP do notebook mude de um dia para o outro. Se não abrir para alguém, use o endereço com o número.

Você mesmo usa pelo `http://localhost:8000`.

## 3. Cuidados por ser um notebook

- **Suspensão:** com a janela do MAX aberta, o Windows não suspende sozinho. A tela pode apagar normalmente.
- **Tampa:** fechar a tampa ainda suspende o notebook e derruba o MAX. Para trabalhar com a tampa fechada, vá em Painel de Controle > Opções de Energia > "Escolher a função de fechamento da tampa" e marque "Nada a fazer" quando estiver na tomada.
- **Rede:** se você sair da empresa ou desconectar do Wi-Fi/cabo, ninguém mais acessa. Ao voltar, o MAX volta a funcionar sozinho, sem precisar reiniciar.
- **Ligar junto com o Windows (opcional):** aperte Win+R, digite `shell:startup` e coloque ali um atalho para o `iniciar_servidor.bat`.

## 4. Atualizar a planilha

Salve a nova versão em `dados\ANÁLISE DIÁRIA DE PROGRAMAÇÃO.xlsm` (mesmo nome). O MAX percebe sozinho, sem reiniciar.

## Como funciona

- Cada pessoa entra com **nome e senha**. No primeiro acesso, ela digita o nome, deixa a senha em branco e cria a senha dela (pelo menos 6 caracteres). Isso vale também para quem já usava o MAX antes: o histórico continua o mesmo. Peça para cada colega criar a senha logo, porque, até lá, quem digitar o nome dele cria a senha no lugar dele.
- Histórico e memória ficam separados em `usuarios\<nome>\`. O navegador fica conectado por 30 dias. Clicando no nome, no canto de cima, dá para **trocar a senha** ou **sair**.
- **Esqueceu a senha?** Apague o arquivo `usuarios\<nome>\senha.json` da pessoa. No próximo acesso ela cria uma senha nova; o histórico não se perde.
- Depois de 5 senhas erradas seguidas, aquele nome fica bloqueado por 5 minutos.
- A senha não fica guardada em lugar nenhum: o `senha.json` tem só um resumo dela, que não dá para desfazer.
- A chave do Gemini fica só no seu PC. Quem acessa não tem como vê-la, mas todas as perguntas usam essa chave, então o consumo de todo mundo é somado.
- Os planos de ação exportados aparecem como um botão **Baixar** embaixo da resposta.
- Para o MAX analisar uma planilha que não está na pasta `dados\`, clique no **clipe** ao lado da caixa de mensagem (ou arraste o arquivo para a janela). Aceita `.xlsx`, `.xlsm` e `.csv` de até 30 MB. A planilha fica em `usuarios\<nome>\anexos\` e só quem anexou consegue perguntar sobre ela. Para tirar, clique no **×** ao lado do nome do arquivo.
- O `max.py` (a janela) continua funcionando e pode ficar aberto junto com o servidor. Ele usa o histórico antigo da pasta do projeto, separado do histórico do modo rede.
- O MAX é só para a rede interna. Não abra a porta 8000 para a internet.

Se um dia o MAX for para um PC ou servidor da empresa que fique sempre ligado, os passos são os mesmos. Nesse PC é preciso também instalar o Python 3.12, criar a `.venv` com `pip install -r requirements.txt` e copiar o `.env`.
