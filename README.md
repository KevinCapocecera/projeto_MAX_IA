# MAX — Assistente de PCP

A MAX é uma assistente de conversa para o PCP (Planejamento e Controle da Produção). Ela responde em português, com os dados reais da planilha **ANÁLISE DIÁRIA DE PROGRAMAÇÃO**: estoque, DOH, prioridades de produção, solicitações de compra, apontamentos, vendas, fornecedores e qualquer outra aba.

Quem conversa é o Gemini, do Google. Os números vêm sempre do Python, que lê a planilha e faz as contas. Por isso a MAX não inventa quantidades.

A mesma conversa funciona de quatro jeitos:

| Jeito | Arquivo | Para quem |
|---|---|---|
| **Site na rede da empresa** | `servidor.py` | Várias pessoas, pelo navegador, sem instalar nada |
| Janela no PC | `max.py` | Uma pessoa, no próprio computador |
| Janela antiga | `janela_chat.py` | Reserva da janela (Tkinter) |
| Menu no terminal | `main.py` | Consultas rápidas e exportação do plano, sem o Gemini |

---

## Sumário

- [O que a MAX faz](#o-que-a-max-faz)
- [Como funciona](#como-funciona)
- [Instalação](#instalação)
- [Como usar](#como-usar)
- [Perguntas de exemplo](#perguntas-de-exemplo)
- [Regras da análise de DOH](#regras-da-análise-de-doh)
- [Como a planilha é lida](#como-a-planilha-é-lida)
- [Ferramentas que o Gemini usa](#ferramentas-que-o-gemini-usa)
- [Histórico e memória](#histórico-e-memória)
- [A interface](#a-interface)
- [Estrutura do projeto](#estrutura-do-projeto)
- [API do servidor](#api-do-servidor)
- [Testes](#testes)
- [Problemas comuns](#problemas-comuns)
- [Segurança e privacidade](#segurança-e-privacidade)

---

## O que a MAX faz

- **Análise de DOH por aba** (Fiesta, Talher, Prato, Copo BCO-TRP, Copo colorido): quantos produtos estão abaixo da meta de 45 dias, quais são os mais críticos e quanto falta produzir.
- **Consulta qualquer aba** da planilha, incluindo as ocultas: filtra, ordena, soma, tira média, conta e agrupa.
- **Procura um código ou descrição** em todas as abas de uma vez.
- **Exporta para Excel** o plano de ação de DOH e também qualquer consulta ou resumo de qualquer aba. No site, aparece um botão **Baixar** embaixo da resposta.
- **Lê o ERP Bellocopo:** baixa sozinho o estoque atual e as quatro previsões (produtos, insumos, produtos de festa e insumos de festa) e responde coisas como "o que vai zerar nas próximas 3 semanas e em que dia". Também consulta **pedidos**: o que tem num pedido e se algum item pode faltar, e quais pedidos têm um produto, por status. Só lê; nunca altera nada no ERP.
- **Abre links da internet:** mande o endereço na conversa e a MAX lê a página para resumir ou responder. Se o link for de uma planilha (Excel, CSV ou Google Planilhas pública), ele baixa e analisa como se fosse uma planilha anexada.
- **Lê planilhas anexadas no chat** (`.xlsx`, `.xlsm` ou `.csv`, até 30 MB): clique no clipe ao lado da caixa de mensagem ou arraste o arquivo para a janela. A MAX responde com as abas e colunas que encontrou, e dá para pedir análises, somas, rankings e exportações como em qualquer outra aba. Cada pessoa só vê as próprias planilhas anexadas.
- **Quadro "Estoque por aba"**, com a situação de cada aba em cores de andon (crítica, alta, média, na meta, sem demanda).
- **Lembra de cada pessoa:** histórico da conversa e memória de longo prazo separados por usuário.

---

## Como funciona

```
 Navegador / janela
        │  pergunta
        ▼
 servidor.py ou max.py ──► modulos/nucleo.py (Max)
                                │  monta o prompt: instruções, data e hora,
                                │  abas disponíveis, memórias e histórico
                                ▼
                           Gemini (google-genai)
                                │  decide se precisa da planilha e chama
                                ▼  as ferramentas (function calling)
                     modulos/ferramentas_pcp.py
                       │                      │
             análise de DOH            qualquer aba
       (base_dados + plano_acao)      (planilhas.py)
                       │                      │
                       └────► dados/*.xlsm / *.xlsx ◄────┘
```

1. A pessoa pergunta, por exemplo "Quais os 5 produtos mais críticos do Talher?".
2. O `nucleo.py` envia ao Gemini a pergunta, as últimas 12 mensagens, as memórias relevantes e a lista de abas.
3. O Gemini chama uma ferramenta, por exemplo `listar_produtos_pcp(aba="talher", filtro="critica", limite=5)`.
4. O Python lê a planilha, calcula e devolve os dados ao Gemini.
5. O Gemini escreve a resposta em texto simples.
6. Em paralelo, a MAX atualiza a memória de longo prazo daquela pessoa.

Enquanto a planilha está sendo lida, o painel de LED da interface mostra **"Consultando a planilha…"**.

---

## Instalação

Requisitos: **Windows** com **Python 3.12** e uma **chave da API do Gemini** (crie em https://aistudio.google.com/apikey).

Os comandos abaixo são para o **Git Bash** ou o **PowerShell**, dentro da pasta do projeto.

```bash
# 1. Ambiente virtual
python -m venv .venv

# 2. Dependências
.venv/Scripts/python -m pip install -r requirements.txt
```

Os pacotes de voz (`PyAudio`, `sounddevice`, `soundcard`, `SpeechRecognition`) só são usados pelos testes de microfone. Se algum deles der erro na instalação, pode remover essas linhas do `requirements.txt`: o resto funciona sem eles.

### 3. Chave do Gemini

Crie o arquivo **`.env`** na pasta do projeto:

```
GEMINI_API_KEY=sua_chave_aqui

# Opcional: troca os modelos sem mexer no código
GEMINI_MODELO=gemini-3.5-flash-lite
GEMINI_MODELO_RESERVA=gemini-3.5-flash

# Opcional: quantas perguntas o site responde ao mesmo tempo (padrão 32)
MAX_SIMULTANEAS=32

# Opcional: ERP Bellocopo (veja "ERP Bellocopo" mais abaixo)
ERP_EMAIL=seu_email_do_erp
ERP_SENHA=sua_senha_do_erp
ERP_USUARIOS=Kevin Pereira
```

Depois de mudar o `.env`, feche e abra o servidor de novo.

Quando o Google devolve um erro passageiro (503 de modelo sobrecarregado, 429 de limite por minuto, 500, 502 ou 504), a MAX faz até 3 tentativas no modelo principal, esperando 2 e depois 5 segundos entre elas. Se não der, faz mais 2 tentativas no **modelo reserva**. Só depois disso ele mostra uma mensagem explicando o problema. Para não usar o modelo reserva, deixe `GEMINI_MODELO_RESERVA=` vazio.

O `.env` está no `.gitignore` e **nunca** deve ir para o GitHub.

### 4. Planilhas

Coloque na pasta **`dados/`**:

- `ANÁLISE DIÁRIA DE PROGRAMAÇÃO.xlsm` (ou `.xlsx`). É obrigatória para a análise de DOH e o quadro de estoque.
- Qualquer outra planilha `.xlsx` ou `.xlsm`. A MAX também consegue consultar, por exemplo, a `Previsão de Estoque dos Produtos de Festa.xlsx`.

**Planilhas em outra pasta (por exemplo, na rede):** coloque o caminho no `.env` e reinicie o servidor. A MAX passa a ler de lá, e não mais da pasta `dados/`:

```
MAX_PASTA_DADOS=O:\copos\16 - PRODUÇÃO\05 - PCP BELLO\BD_MAX
```

- **Ao ligar o servidor:** a janela mostra de qual pasta a MAX está lendo, ou avisa se não conseguiu abri-la.
- **Rede fora do ar:** se a rede cair ou a unidade `O:` desconectar, a MAX responde que não conseguiu abrir a pasta e volta a funcionar sozinha quando a rede voltar.
- **Unidade não conectada ao ligar:** se o servidor ligar junto com o Windows, a unidade `O:` às vezes ainda não conectou. Nesse caso, dá para usar o endereço de rede no lugar da letra: `\\172.25.4.75\Setor$\copos\16 - PRODUÇÃO\05 - PCP BELLO\BD_MAX`.
- **Só leitura:** a MAX só lê essa pasta. Os planos e consultas exportados continuam em `relatorios/`, e os usuários e senhas continuam em `usuarios/`, na pasta do projeto.
- **Excel aberto:** quem atualiza a planilha pode deixá-la aberta no Excel. A MAX lê a última versão **salva**.

---

## Como usar

### Site na rede da empresa (várias pessoas)

Dê dois cliques em **`iniciar_servidor.bat`**, ou rode:

```bash
.venv/Scripts/python servidor.py              # porta 8000
.venv/Scripts/python servidor.py --porta 8080  # outra porta
```

A janela mostra os endereços de acesso:

```
MAX no ar. Para acessar:
  Neste computador:   http://localhost:8000
  Nos outros da rede: http://nome-do-pc:8000
           ou então:  http://192.168.x.x:8000
```

- Cada pessoa abre o endereço no Chrome ou no Edge e digita o próprio nome (não tem senha).
- O computador não entra em suspensão enquanto a janela do servidor estiver aberta.
- É preciso liberar a porta 8000 no firewall do Windows uma vez.

O passo a passo completo (firewall, tipo de rede, notebook, ligar junto com o Windows) está em **[LEIA-ME_SERVIDOR.md](LEIA-ME_SERVIDOR.md)**.

### Janela no próprio PC

```bash
.venv/Scripts/python max.py           # janela da MAX
.venv/Scripts/python max.py --debug   # com as ferramentas de desenvolvedor
```

Abre o `interface/index.html` numa janela do Windows (pywebview). O histórico fica em `historico.json` e `memoria.json`, na raiz do projeto.

### Janela antiga (reserva)

```bash
.venv/Scripts/python janela_chat.py
```

É a mesma conversa, numa janela Tkinter mais simples.

### Menu no terminal (sem o Gemini)

```bash
.venv/Scripts/python main.py
```

Escolha uma aba de análise e depois uma opção: ver os 20 primeiros registros, buscar um produto, ver o resumo numérico ou exportar o plano de ação para Excel.

---

## Perguntas de exemplo

**Análise de DOH**

- Como está a Fiesta?
- Quais os 5 produtos mais críticos do Talher?
- Procura o canudo rosa.
- Quanto precisa produzir de prato para chegar na meta?
- Exporta o plano de ação do Copo colorido.

**Qualquer aba**

- Quantas solicitações de compra estão aguardando e de quais fornecedores?
- Qual fornecedor tem a maior quantidade solicitada?
- O que foi apontado de produção nos últimos 7 dias?
- Qual o lead time dos itens do fornecedor Sonho Encantado?
- Quanto vendemos de talher em setembro, por cor?
- Quais os 5 produtos com o estoque mais negativo no BD.ESTOQUE CARTEIRA?
- Qual é a prioridade de produção número 1?
- Me fala tudo o que a planilha tem sobre o código TCCFRB-10.
- Exporta em Excel as velas com status COMPRAR na análise de itens de compra.
- Me manda em Excel a quantidade solicitada por fornecedor.
- Qual a carteira do segmento PET na análise da Fiesta?

Dicas para perguntar:

- **Cite a aba quando souber.** Se a pergunta servir para mais de uma aba (por exemplo, "copo"), a MAX pergunta qual delas você quer.
- **Pode usar datas relativas.** A MAX recebe a data e a hora do computador a cada pergunta, então entende "ontem" e "últimos 7 dias".
- **Pode pedir a origem.** A MAX diz de qual aba veio a informação.

---

## Regras da análise de DOH

Valem para as abas de análise (`ANALISE FIESTA`, `TALHER`, `PRATO`, `COPO BCO-TRP`, `COPO COLORIDO`) e estão em `modulos/plano_acao.py`.

- **Meta:** 45 dias de cobertura (`META_DOH` em `ferramentas_pcp.py`).
- **Unidade:** caixas.
- **PET fica de fora** da análise de DOH. Ele é reconhecido pela coluna `REF` ou `Segmento` igual a "PET". A busca ainda encontra produtos PET, mas eles vêm marcados como "fora da análise".

**Cálculo da necessidade:**

```
Estoque alvo         = Carteira + (Demanda ÷ 21) × 45
Necessidade estimada = Estoque alvo − Estoque     (arredondada para cima; nunca negativa)
```

**Prioridade (pela coluna DOH TT):**

| Prioridade | Regra |
|---|---|
| CRÍTICA | DOH ≤ 0 |
| ALTA | 0 < DOH < 15 dias |
| MÉDIA | 15 ≤ DOH < 45 dias |
| DENTRO DA META | DOH ≥ 45 dias |
| SEM DEMANDA | Demanda ≤ 0 (vale acima das outras) |

O plano é ordenado da prioridade mais urgente para a menos urgente e, dentro de cada uma, do menor DOH para o maior. Ao exportar, ele vira um Excel em `relatorios/` com duas abas: **Plano de Acao** e **Resumo**.

As exportações de qualquer aba (`Consulta_*.xlsx` e `Resumo_*.xlsx`) mantêm números e datas como números e datas. Elas vêm com o cabeçalho fixo e com filtro, e trazem uma planilha **Sobre** com a aba de origem, os filtros usados e a data de geração.

---

## Como a planilha é lida

A MAX lê a **última versão salva** de cada planilha. Se alguém estiver editando no Excel, as mudanças aparecem para a MAX depois de salvar.

- **Cache:** cada planilha só é lida de novo quando o arquivo muda (pela data da última gravação). Trocar a planilha na pasta `dados/`, com o mesmo nome, basta: não precisa reiniciar.
- **Cabeçalho automático:** em cada aba, o cabeçalho é a linha, entre as primeiras, com mais textos e datas. Datas no cabeçalho viram texto, como `08/2025` (mês) ou `28/10/2026`.
- **Abas de análise:** viram duas tabelas. A de produtos começa na linha **Cod Prodt**. O quadro do topo vira a tabela à parte **`<ABA> - RESUMO POR SEGMENTO`**, com as unidades no nome da coluna, por exemplo `Carteira (Cxs)`.
- **Limpeza:** linhas e colunas totalmente vazias são descartadas. Colunas sem nome viram `Coluna A`, `Coluna B`... Nomes repetidos ganham `(2)`.
- **Abas formatadas até o fim da planilha:** a leitura para depois de 500 linhas vazias seguidas, para não percorrer 1 milhão de linhas em branco.
- **Abas ocultas:** também são lidas, e aparecem marcadas como "oculta".
- **Fórmulas:** a MAX lê o valor calculado que o Excel salvou, não a fórmula.

---

## Ferramentas que o Gemini usa

Ficam em `modulos/ferramentas_pcp.py`. O Gemini escolhe sozinho qual chamar, até 10 chamadas por pergunta.

| Ferramenta | Para quê |
|---|---|
| `resumo_pcp(aba)` | Quantos produtos em cada prioridade e a necessidade total da aba |
| `listar_produtos_pcp(aba, filtro, limite)` | Produtos por urgência. Filtros: `abaixo_da_meta`, `menos_de_15_dias`, `critica`, `alta`, `media`, `dentro_da_meta`, `sem_demanda`, `todas` |
| `buscar_produto_pcp(termo)` | Procura um produto nas abas de análise (código, segmento, REF e cor) |
| `exportar_plano_pcp(aba)` | Gera o plano de ação em Excel |
| `listar_abas_planilha(parte_do_nome)` | Lista as abas, com as colunas e o número de linhas |
| `consultar_aba(aba, filtros, colunas, ordenar_por, limite)` | Linhas de qualquer aba, com filtro e ordenação (até 100 linhas) |
| `resumir_aba(aba, filtros, agrupar_por, calculos)` | Soma, média, contagem, máximo, mínimo e valores distintos, com ou sem agrupamento |
| `buscar_na_planilha(termo)` | Procura um texto em todas as abas |
| `exportar_consulta_excel(aba, filtros, colunas, ordenar_por)` | Excel com **todas** as linhas da consulta, com todas as colunas se `colunas` vier vazio. Gera `relatorios/Consulta_<ABA>_<data>.xlsx` |
| `exportar_resumo_excel(aba, filtros, agrupar_por, calculos)` | Excel com os totais por grupo, sem o limite de 60 grupos da conversa. Gera `relatorios/Resumo_<ABA>_<data>.xlsx` |
| `consultar_pedido_erp(numero)` | Itens de um pedido no ERP (tela Consulta por Pedido): data programada, código, produto, quantidade, estoque na data programada e estoque hoje. Aceita o número com ou sem os zeros do começo |
| `consultar_pedidos_produto_erp(codigo)` | Pedidos de um produto no ERP (tela Consulta por Produto): data programada, pedido, status e quantidade, com totais por status |
| `consultar_erp(relatorio)` | Baixa do ERP Bellocopo o `estoque` ou uma previsão (`previsao_produtos`, `previsao_insumos`, `previsao_produtos_festa`, `previsao_insumos_festa`) e devolve o nome da aba (`ERP - ...`) para ler com `consultar_aba` e `resumir_aba` |
| `ler_link(url, parte)` | Abre um link da internet (`modulos/links.py`). Página: devolve o texto, em partes de 15 mil caracteres. Planilha (`.xlsx`, `.xlsm`, `.csv`, Google Planilhas pública ou arquivo do Google Drive): baixa e guarda como planilha anexada da pessoa |

**Links:** a MAX se apresenta aos sites como `MAX-PCP/1.0`. Por isso, sites que não aceitam leitura automática (a Wikipédia, por exemplo) e páginas que pedem login respondem "acesso recusado", e a MAX explica isso ao usuário. Páginas montadas por JavaScript chegam com pouco texto. PDFs ainda não são lidos. Por segurança, links para a rede interna (`localhost`, `192.168...`, `10...`, o nome de outros PCs da empresa) são recusados, para o servidor não servir de ponte até outros computadores. O limite é de 20 segundos por link, 5 MB por página e 30 MB por planilha.

**Formato dos filtros** (em `consultar_aba` e `resumir_aba`), com as condições separadas por `;`:

```
Status = AGUARDANDO; Quantidade > 100
Descrição contém COPO 200
Data entre 01/10/2026 e 31/10/2026
Data de Entrega vazio
Código começa com PBLIS
```

Os operadores aceitos são `=`, `!=`, `>`, `>=`, `<`, `<=`, `contém`, `não contém`, `começa com`, `termina com`, `entre`, `vazio` e `não vazio`. Maiúsculas e acentos não importam. Números com vírgula (`12,5`) e com ponto de milhar (`1.234,5`) são entendidos.

**Formato dos cálculos:** `contagem`, `soma de Quantidade`, `media de Estoque`, `maximo de Data`, `distintos de Fornecedor`.

Os nomes de aba e de coluna podem ser parciais, por exemplo "solicitações", "fiesta" ou "Lead Time (Meses)". Se o nome combinar com mais de uma aba ou coluna, a ferramenta devolve as opções e o Gemini tenta de novo.

**Regras das funções expostas ao Gemini:** parâmetros simples (`str` ou `int`), sem valor padrão e com a docstring explicando o uso. O retorno é sempre um dicionário, e os erros voltam como `{"erro": ...}` para o modelo explicar ao usuário. O `google-genai` 2.31 quebra com `Literal` e com valores padrão.

---

## ERP Bellocopo

A MAX entra no ERP (`sistema-erp.herokuapp.com`) com o login do `.env` e baixa os mesmos arquivos Excel dos downloads do menu **Inventário**. Fica em `modulos/erp.py`.

| Relatório | De onde vem no ERP | O que tem |
|---|---|---|
| `estoque` | Baixar Estoque Atual | Código, Nome, Segmento, Marca, GTIN-13 e Quantidade |
| `previsao_produtos` | Previsão de Produtos | Código, Produto, Média 4m, Carteira, Pedidos, Separado e o estoque previsto de cada dia |
| `previsao_insumos` | Previsão de Insumos | Código, Insumo, Média 4m, Carteira e o estoque previsto de cada dia |
| `previsao_produtos_festa` | Previsão de Produtos de Festa | Igual à de produtos |
| `previsao_insumos_festa` | Previsão de Insumos de Festa | Igual à de insumos |

**Pedidos:** a MAX também faz as buscas das telas **Consulta por Pedido** (pelo número; `130101` e `00130101` funcionam) e **Consulta por Produto** (pelo código exato; se a pessoa disser o nome, a MAX acha o código no estoque do ERP antes). Ele lê a tabela do resultado, sem a linha de total, e soma os pedidos por status. Segundo o ERP, o **Estoque na Data Programada** considera as caixas reservadas, e o **Estoque Hoje** é o estoque do início do dia; quando o estoque na data programada é negativo, a MAX avisa que o item pode faltar.

- **Só leitura:** as únicas chamadas ao ERP são o login, esses 5 downloads e as 2 buscas de pedidos. A lista fica em `CHAMADAS_PERMITIDAS`, em `modulos/erp.py`, e qualquer outra é recusada pelo próprio código. A MAX nunca usa "Atualizar previsão", "Atualizar Estoques" nem telas que gravem algo.
- **Previsões:** baixadas com 1 dia anterior e 30 dias para prever, o máximo que o ERP aceita. A MAX acrescenta as colunas **Estoque hoje**, **Estoque em 7, 15 e 30 dias**, **Menor estoque previsto**, **Zera em** (primeiro dia com estoque previsto zero ou negativo) e **Dias até zerar**. Nos produtos, traz também **Segmento** e **Marca** do relatório de estoque.
- **Números:** o ERP usa ponto decimal (`92.25`); a MAX converte na leitura, para não confundir com o ponto de milhar das planilhas da empresa.
- **Atualização:** cada relatório é baixado quando alguém pergunta e vale por 10 minutos. Os arquivos ficam em `erp/` (fora do Git). Se a sessão do ERP expirar, a MAX entra de novo sozinha.
- **Quem pode usar:** só os nomes em `ERP_USUARIOS`, separados por vírgula: o mesmo nome com que a pessoa entra na MAX (maiúsculas, acentos, hífens e apóstrofos não importam; o nome da pasta, como `kevin_pereira`, também serve), e, por padrão, **só em perguntas feitas no próprio PC que roda a MAX** (`ERP_SO_NESTE_PC=1`), porque a MAX entra no ERP com o login de uma pessoa. Para liberar os colegas da lista em outros PCs: peça a quem administra o ERP um usuário só de leitura para a MAX, coloque-o em `ERP_EMAIL` e `ERP_SENHA` e use `ERP_SO_NESTE_PC=0`. Como cada pessoa entra na MAX com a própria senha, ninguém consegue usar o nome de outra. A janela do `max.py` sempre pode.

---

## Histórico e memória

| | Site (`servidor.py`) | Janela (`max.py`, `janela_chat.py`) |
|---|---|---|
| Histórico da conversa | `usuarios/<nome>/historico.json` | `historico.json` |
| Memória de longo prazo | `usuarios/<nome>/memoria.json` | `memoria.json` |
| Planilhas anexadas | `usuarios/<nome>/anexos/` | (não tem) |
| Senha (só o resumo) | `usuarios/<nome>/senha.json` | (não tem) |

- **Histórico:** o Gemini recebe as últimas 12 mensagens. No site, ao entrar, a pessoa vê as últimas 30.
- **Memória:** depois de cada resposta, o Gemini consolida fatos úteis sobre a pessoa e os projetos, numa lista JSON de `{categoria, conteudo}`. Senhas, chaves e a data do dia não são guardadas. Se a consolidação falhar ou vier vazia, a memória anterior é mantida. A cada pergunta, entram no prompt até 5 memórias com palavras em comum com a pergunta.
- **Nome da pasta:** o nome digitado vira a pasta, sem acentos, em minúsculas e com `_` no lugar dos espaços. "João Silva" vira `usuarios/joao_silva/`.
- **Senha:** cada pessoa entra com nome e senha, criada no primeiro acesso (pelo menos 6 caracteres). Fica em `usuarios/<nome>/senha.json` só como um resumo `scrypt` com sal, que não dá para desfazer. A sessão é um cookie assinado com a chave de `usuarios/.chave_sessao` (criada sozinha) e vale 30 dias; trocar a senha derruba as sessões abertas em outros PCs. Depois de 5 senhas erradas seguidas, o nome fica bloqueado por 5 minutos. **Esqueceu a senha?** Apague o `senha.json` da pessoa; ela cria outra no próximo acesso, e o histórico continua.
- **Levar o histórico da janela para o site:** copie `historico.json` e `memoria.json` para `usuarios/<seu_nome>/` antes de entrar pela primeira vez.
- **Planilhas anexadas:** ficam guardadas até a pessoa clicar no **×** ao lado do nome, acima da caixa de mensagem. Anexar de novo um arquivo com o mesmo nome troca a versão antiga; se o arquivo novo não abrir, a antiga continua. Na conversa, as abas aparecem com o nome do arquivo no começo (`Estoque outubro - Planilha1`). Um `.csv` vira uma aba só, com o separador (`;`, `,` ou tabulação) e as datas `dd/mm/aaaa` reconhecidos sozinhos. Arquivos `.xls` (Excel antigo) precisam ser salvos como `.xlsx` antes.

---

## A interface

Fica em `interface/index.html`, num arquivo só, com HTML, CSS e JavaScript.

- **Painel de LED (72 × 17)** mostra o estado da MAX: *Iniciando* (o nome MAX acende), *Pronta* (o nome MAX fica aceso, com um brilho passando devagar pelas letras), *Pensando*, *Consultando a planilha*, *Respondendo* e *Erro*. Cada nível de brilho é desenhado uma vez só e copiado, e só os LEDs que mudaram são redesenhados. Assim ele roda a 60 quadros por segundo mesmo em PCs fracos, e cai sozinho para 30 se o PC não der conta.
- **Quadro "Estoque por aba"** mostra os dados reais da planilha e é atualizado a cada resposta e a cada 2 minutos. Clicar numa aba faz a pergunta sobre ela.
- **Ícone da aba:** um "M" aceso num pedaço do painel de LED. Ele está embutido no `index.html`, então aparece também na janela e no modo demonstração. Os arquivos ficam em `interface/icone.*`.
- **Voz:** o botão de alto-falante no topo faz a MAX ler cada resposta em voz alta assim que ela chega. Ele começa desligado, e cada navegador lembra a escolha. O botão **Ouvir** de cada resposta lê só aquela, mesmo com a voz desligada, e vira **Parar** enquanto fala. A voz é a do próprio navegador (grátis, sem gastar o Gemini), em português do Brasil e de preferência feminina: Francisca no Edge, Google português no Chrome ou Maria no Windows. A fala é dividida frase por frase, sem os links. Enquanto a MAX fala, o painel de LED fica no estado *Falando*, e uma pergunta nova interrompe a fala.
- **Tema claro e escuro:** segue o Windows, com um botão para trocar.
- **Celular:** a página se ajusta à tela.
- **Medidor de desempenho:** abra o endereço com `?fps` no fim (`http://nome-do-pc:8000/?fps`) para ver quadros por segundo e o tempo de desenho de cada quadro.
- **Modo demonstração:** aberto direto do arquivo, sem servidor nem pywebview, o `index.html` responde só a algumas perguntas de exemplo, com os números de 19/10.
- **Botão do microfone:** está desativado, porque falar com a MAX por voz é uma etapa futura (veja os testes de áudio).

---

## Estrutura do projeto

```
projeto_MAX_IA/
├── servidor.py               Site na rede (Flask + waitress)
├── iniciar_servidor.bat      Atalho para ligar o servidor no Windows
├── max.py                    Janela no PC (pywebview)
├── janela_chat.py            Janela antiga (Tkinter)
├── main.py                   Menu no terminal
├── requirements.txt          Dependências com versões fixas
├── LEIA-ME_SERVIDOR.md       Passo a passo do servidor na rede
├── .env                      GEMINI_API_KEY (não vai para o Git)
├── historico.json            Histórico da janela (max.py)
├── memoria.json              Memória da janela (max.py)
├── memoria_backup.json       Cópia antiga da memória
│
├── modulos/
│   ├── nucleo.py             Classe Max: prompt, Gemini, histórico e memória
│   ├── ferramentas_pcp.py    Ferramentas do Gemini e o quadro "Estoque por aba"
│   ├── planilhas.py          Leitura, filtros e resumos de qualquer aba
│   ├── links.py              Leitura de links: páginas e planilhas online
│   ├── erp.py                Login e downloads do ERP Bellocopo (estoque e previsões)
│   ├── base_dados.py         Leitura das abas de análise e filtro do PET
│   ├── plano_acao.py         Cálculo da prioridade e da necessidade; Excel do plano
│   ├── assistente.py         Respostas por regras (versão antiga, sem Gemini)
│   └── analise_estoque.py    Análise da planilha de previsão (versão antiga)
│
├── interface/
│   ├── index.html            Interface atual (painel de LED, chat e quadro)
│   ├── icone.svg             Ícone da MAX ("M" no painel de LED)
│   ├── icone.ico             Mesmo ícone para o Windows (16 a 256 px)
│   ├── icone-180.png         Ícone para a tela inicial do celular
│   └── interface.css         Estilos antigos (o index.html não usa)
│
├── dados/                    Planilhas lidas pela MAX
├── relatorios/               Planos de ação exportados
├── usuarios/                 Histórico, memória e planilhas anexadas de cada pessoa (criada pelo servidor)
└── testes/                   Testes do Gemini, das planilhas e do microfone
```

---

## API do servidor

Usada pela página. Cada pessoa é identificada pela sessão (cookie `max_sessao`, aberto em `/api/entrar` ou `/api/criar-senha`). Tudo abaixo de `/api/` e `/relatorios/`, menos as rotas de entrada, responde **401** sem sessão.

| Método | Caminho | O que faz |
|---|---|---|
| GET | `/` | A página (marca `window.MAX_SERVIDOR = true`) |
| POST | `/api/entrar` | `{"nome", "senha"}` → `{"nome"}` e abre a sessão; `{"criar_senha": true}` se o nome ainda não tem senha; 401 com senha errada; 429 depois de 5 erradas |
| POST | `/api/criar-senha` | `{"nome", "senha"}` → primeiro acesso: cria a senha e abre a sessão (409 se o nome já tem senha) |
| POST | `/api/trocar-senha` | `{"atual", "nova"}` → troca a senha; as sessões de outros PCs caem |
| POST | `/api/sair` | Fecha a sessão |
| GET | `/api/eu` | `{"nome"}` de quem está na sessão |
| POST | `/api/perguntar` | `{"texto": "..."}` → `{"texto": resposta, "arquivos": [{"nome", "url"}]}` |
| GET | `/api/estado` | `{"estado": "consultando"}` enquanto a planilha é lida |
| GET | `/api/historico` | Últimas 30 mensagens da pessoa |
| GET | `/api/painel` | Resumo das abas para o quadro "Estoque por aba" |
| GET | `/relatorios/<arquivo>` | Baixa um arquivo exportado (só `Plano_Acao_PCP*.xlsx`, `Consulta*.xlsx` e `Resumo*.xlsx`) |
| GET | `/favicon.ico`, `/icones/<arquivo>` | Ícones da MAX (`icone.svg`, `icone.ico`, `icone-180.png`) |

**Limites:**

- **Tamanho da pergunta:** até 4.000 caracteres.
- **Perguntas ao mesmo tempo:** até **32** (`MAX_SIMULTANEAS` no `.env`, ou `--simultaneas 50` ao ligar).
- **Fila:** as perguntas que chegam com tudo ocupado esperam numa fila do mesmo tamanho, por até 90 s. Com a fila cheia, a pessoa recebe na hora a mensagem "A MAX está respondendo muitas perguntas ao mesmo tempo. Tente de novo em alguns segundos."
- **Página:** o servidor reserva 8 linhas de atendimento só para as chamadas rápidas (página, LED, quadro e histórico). Assim a página continua respondendo mesmo com tudo ocupado.
- **Limite do Gemini:** a chave também tem um limite de pedidos por minuto, definido pelo Google conforme o plano. Se ele for atingido, a MAX tenta de novo e usa o modelo reserva (erro 429).

---

## Testes

| Arquivo | O que testa |
|---|---|
| `testes/teste_perguntas_planilha.py` | 10 perguntas reais ao Gemini, mostrando quais abas foram consultadas e as respostas |
| `testes/teste_gemini.py` | Se a chave do Gemini funciona |
| `testes/teste_microfone*.py`, `teste_pyaudio*.py`, `teste_sounddevice.py`, `teste_voz.py`, `diagnostico_audio.py` | Microfone e reconhecimento de voz (etapa futura) |

```bash
.venv/Scripts/python testes/teste_perguntas_planilha.py        # todas as perguntas
.venv/Scripts/python testes/teste_perguntas_planilha.py 1 5 8  # só algumas
```

O teste de perguntas gasta um pouco da cota do Gemini. Ele não mexe no histórico nem na memória de ninguém.

---

## Problemas comuns

| Sintoma | Causa provável e solução |
|---|---|
| `iniciar_servidor.bat` diz "O sistema não pode encontrar o caminho especificado" | O `.bat` foi aberto fora da pasta do projeto, ou a `.venv` não existe. Abra o `.bat` de dentro de `projeto_MAX_IA`. |
| Funciona no `localhost`, mas os colegas não conseguem abrir | Firewall ou rede marcada como "Pública" no Windows. Veja o [LEIA-ME_SERVIDOR.md](LEIA-ME_SERVIDOR.md). |
| "O Gemini está sobrecarregado agora (erro 503 do Google)" | O modelo do Google está com muita procura. A MAX já tentou de novo e usou o modelo reserva. Costuma passar em minutos: pergunte de novo. |
| "O limite de uso do Gemini foi atingido (erro 429)" | Muitas perguntas por minuto, ou a cota do dia acabou. Espere um pouco. Se acontecer sempre, veja a cota no Google AI Studio. |
| "Não encontrei GEMINI_API_KEY no arquivo .env" | Crie o `.env` na raiz do projeto com `GEMINI_API_KEY=...`. |
| "Coloque a planilha ANÁLISE DIÁRIA DE PROGRAMAÇÃO na pasta dados" | O nome do arquivo precisa ser exatamente esse, com os acentos, em `.xlsm` ou `.xlsx`. |
| A MAX não vê uma mudança recente na planilha | Salve a planilha no Excel. A MAX lê a última versão salva. |
| Mudei um arquivo `.py` e nada mudou | Reinicie o servidor. Mudanças só no `index.html` aparecem ao recarregar a página com Ctrl+F5. |
| Animação travando num PC | Abra `/?fps` e veja os números. Confira também se a aceleração de hardware do navegador está ligada. |
| "Erro ao salvar histórico" | O OneDrive pode estar segurando o arquivo durante a sincronização. Uma opção é mover o projeto para fora do OneDrive (ex.: `C:\MAX`). |
| `git checkout` reclama de "untracked working tree files" | Há arquivos soltos com o mesmo nome dos do branch. Mova esses arquivos para outra pasta e troque de branch de novo. |

---

## Segurança e privacidade

- **Chave do Gemini:** a `GEMINI_API_KEY` fica só no `.env` do computador que roda a MAX. Quem acessa pelo navegador não tem como vê-la. Se a chave vazar, gere outra no Google AI Studio.
- **Senha:** cada pessoa entra com a própria senha, guardada só como resumo `scrypt`. Até alguém criar a senha, quem digitar o nome dela cria a senha no lugar, então peça aos colegas para criarem logo. O site é `http://`, sem criptografia: dentro da rede da empresa isso costuma bastar, mas a senha passa pela rede como texto.
- **Login do ERP:** `ERP_EMAIL` e `ERP_SENHA` ficam só no `.env`. Para o ERP, os acessos da MAX aparecem como seus. Por padrão, o ERP só é consultado em perguntas feitas no próprio PC que roda a MAX (veja "ERP Bellocopo").
- **Só rede interna:** o servidor é feito para a rede interna. Não libere a porta 8000 para a internet.
- **Consumo compartilhado:** todas as perguntas usam a mesma chave do Gemini, então o consumo de todo mundo é somado.
- **O que vai para o Gemini:** o conteúdo das conversas e os dados que as ferramentas devolvem (linhas da planilha) são enviados ao Google para gerar as respostas.
- **Repositório:** se o repositório do GitHub for público, as planilhas em `dados/`, os planos em `relatorios/` e os arquivos `historico.json` e `memoria.json` ficam visíveis para qualquer pessoa. Para manter esses arquivos só no seu PC, coloque-os no `.gitignore` e tire-os do Git com `git rm --cached <arquivo>`. Outra opção é deixar o repositório privado.
