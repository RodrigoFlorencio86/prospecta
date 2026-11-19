# Prospecta: encontre clientes para o seu serviço perto de você

Ferramenta gratuita e de código aberto para **profissionais autônomos e pequenas empresas de
serviço**. Diga o que você faz e de onde quer partir, e ela procura no Google Maps, num raio de
alguns quilômetros, as empresas que podem contratar você: padarias para quem conserta freezer,
clínicas para quem limpa ar-condicionado, restaurantes para quem faz dedetização, e assim por diante.

Tudo roda **no seu computador**. Não precisa de conta, assinatura ou chave de API, e os dados ficam na
sua máquina. Se quiser, conecte o seu ChatGPT (ou use o Claude Code) para conversar com um assistente
que faz as buscas e organiza os contatos por você.

## O que você recebe

- **Lista priorizada** com nota de 0 a 100 e prioridade A, B ou C.
- **Contato de cada empresa**: telefone (celular ou fixo), WhatsApp, e-mail, Instagram, site, nota e
  avaliações no Google, horário e distância.
- **Botão de WhatsApp** que abre a conversa com uma mensagem de apresentação já escrita, com o nome da
  empresa, o bairro, o seu nome e a sua empresa. Quem envia é você.
- **Rota de visitas otimizada** saindo da sua empresa, aberta direto no Google Maps, além de link de
  rota e Waze para cada empresa.
- **Relatório para abrir no navegador** (`relatorio.html`), com mapa, filtros e um campo de status
  de cada contato: interessado, contatado, visitar, cliente ou sem interesse.
- **Planilha** (`prospects.xlsx`) com tudo e colunas para acompanhar os contatos, e **mapa**
  (`prospects.kml`) para o Google My Maps.
- **Só os novos**: na busca do mês seguinte, `--so-novos` mostra só as empresas que você ainda não
  tinha.

## Jeito mais fácil: extensão do app Claude (sem instalar Python)

Para quem assina o Claude e usa o app para computador (Mac ou Windows):

1. Baixe o arquivo `prospecta-<versão>.mcpb`. Para gerá-lo, rode
   `python3 -m prospecta empacotar-extensao`; ele fica na pasta `dist/`.
2. No app Claude, vá em **Configurações → Extensões → Configurações avançadas → Instalar extensão…** e
   escolha o arquivo. Dois cliques no arquivo também costumam funcionar.
3. Na tela da extensão, escolha (se quiser) a pasta dos resultados e informe seu e-mail para o serviço
   de mapas. Ative a extensão.
4. Converse: *"Trabalho com manutenção de ar-condicionado. Procure clínicas e escritórios num raio de
   2 km da Rua X, 100, Campinas"*.

O próprio app instala o Python e o que mais for preciso. Na primeira busca, o Prospecta baixa o motor
de busca, o que leva alguns minutos. Seus dados ficam na pasta `Prospecta`, dentro da sua pasta de
usuário, e os relatórios e planilhas em **Documentos → Prospecta**. Atualizar ou remover a extensão
não apaga nada disso. Para ver o mapa e os botões, peça ao Claude: *"abra o painel"*.

## Outros jeitos de usar

Instale uma vez (precisa de **Python 3.9+** — [download](https://www.python.org/downloads/); no
Windows, marque "Add python.exe to PATH" e troque `python3` por `py` nos comandos):

```bash
git clone https://github.com/RodrigoFlorencio86/AI-Stuff.git
cd AI-Stuff/prospecta-bot
python3 -m prospecta instalar          # baixa o motor de busca, confere tudo e abre o painel
```

### 1. Painel no navegador (com assistente do ChatGPT)

```bash
python3 -m prospecta painel
```

Abre `http://127.0.0.1:8765` no seu navegador, servido pelo seu próprio computador:

- **Nova busca**: endereço ou CEP, o seu serviço (ou os tipos de negócio que você digitar), raio e
  modo. A busca roda em segundo plano, com barra de progresso, e continua mesmo se você fechar a
  página.
- **Resultados**:
  - mapa, filtros e a lista com botões de WhatsApp, rota, Waze e Maps;
  - status de cada contato e anotações;
  - rota otimizada e exportação da planilha, do relatório e do mapa.
- **Assistente**: clique em **Continuar com ChatGPT**, entre com a sua conta e converse em
  português. Exemplos de pedidos:
  - "procure academias e clínicas num raio de 2 km da minha empresa"
  - "quais têm WhatsApp e mais de 100 avaliações?"
  - "monte a rota de amanhã com os 8 melhores"
  - "marque a Padaria X como interessada"

  O assistente usa o **seu plano do ChatGPT** (Go, Plus, Pro ou Business), pelo recurso oficial
  "Sign in with ChatGPT" da OpenAI para apps de código aberto. O Prospecta não cobra nada. Você
  acompanha e limita o uso em [ChatGPT → Configurações → Uso](https://chatgpt.com/settings/usage).
  Sem conta do ChatGPT, o painel funciona igual, só sem o assistente.

### 2. No app do Claude, no Claude Code ou no Codex (MCP)

O Prospecta vira um conjunto de ferramentas dentro do aplicativo de IA que você já usa, com a sua
assinatura:

```bash
python3 -m prospecta conectar claude-desktop   # app Claude para desktop (Mac e Windows)
python3 -m prospecta conectar claude           # Claude Code
python3 -m prospecta conectar codex            # Codex
```

**App Claude para desktop:** depois do comando, feche o Claude por completo (no Mac, Claude → Sair; no
Windows, clique com o botão direito no ícone perto do relógio → Sair) e abra de novo. Para conferir,
clique em **+** no chat → **Conectores**: o `prospecta` deve aparecer. O comando acrescenta o
Prospecta ao `claude_desktop_config.json` sem mexer nos outros servidores e guarda uma cópia do
arquivo original. Para tirar: `python3 -m prospecta conectar claude-desktop --remover`.

Depois é só conversar, por exemplo: *"procure escritórios e clínicas num raio de 2 km da Rua X, 100,
Campinas e me mostre os 10 melhores com WhatsApp"*. O Claude usa as mesmas ferramentas do painel:
buscar, acompanhar, filtrar, marcar status, montar rota e mensagem, exportar. As buscas feitas por
ele aparecem também no painel.

Abrindo o Claude Code dentro desta pasta, o arquivo `.mcp.json` já oferece o servidor `prospecta`
(o Claude Code pede para você aprovar na primeira vez).

### 3. Pedir a um agente que instale e use para você

Não quer digitar comando nenhum? Abra o Claude Code, o Codex, o Cursor ou o Gemini CLI numa pasta
qualquer e cole, trocando o que está entre colchetes:

```text
Clone https://github.com/RodrigoFlorencio86/AI-Stuff e siga o arquivo prospecta-bot/AGENTS.md
para instalar e me ajudar a encontrar clientes. Eu trabalho com [seu serviço, ex.: manutenção de
ar-condicionado] e minha empresa fica em [endereço ou CEP]. Quero procurar num raio de [3] km.
Meu nome e empresa para as mensagens: [Seu Nome | Sua Empresa].
```

> O ChatGPT e o Claude **comuns, no navegador**, não rodam programas no seu computador. Para isso
> use um agente (os citados acima) ou o painel.

### Pela linha de comando

```bash
python3 -m prospecta perfis            # serviços prontos
python3 -m prospecta buscar "Rua Exemplo, 100, Campinas SP" --raio 3 --perfil climatizacao \
    --empresa "Ana Souza | Clima Bom"
python3 -m prospecta buscar "13010-001" --raio 2 --alvos "padaria, pizzaria, hotel" \
    --servico "Manutenção de fornos" --sinais "forno, queimado" --empresa "João | Forno Certo"
```

O resultado fica em `resultados/<data>_<serviço>_<local>_<n>/`. Abra o `relatorio.html` no navegador.

### Opções da busca

| Opção | Para quê |
|---|---|
| `--raio 3` | Raio em km (padrão 3). De 1 a 5 km costuma ser o ideal |
| `--perfil limpeza` | Usa um serviço pronto (lista: `python3 -m prospecta perfis`) |
| `--alvos "a, b, c"` | Tipos de negócio a procurar, como você digitaria no Google Maps |
| `--servico "..."` | Nome do seu serviço, quando usar `--alvos` |
| `--sinais "a, b"` | Palavras nas avaliações que indicam necessidade (ex.: "calor", "barata") |
| `--mensagem "..."` | Sua mensagem de WhatsApp, com `{prospect}`, `{bairro}`, `{meu_nome}` e `{minha_empresa}` |
| `--empresa "Nome \| Empresa"` | Quem assina a mensagem (fica salvo) |
| `--base "endereço"` | Ponto de partida das rotas, se for diferente do centro da busca (fica salvo) |
| `--modo completo` | Mais resultados e leitura das avaliações, mas várias vezes mais lento |
| `--so-novos` | Esconde empresas que já apareceram em buscas anteriores |
| `--top 15` | Quantas empresas aparecem no `resumo.md` |

## Serviços prontos

| Perfil | Procura por (exemplos) |
|---|---|
| `refrigeracao`: Refrigeração comercial | padarias, sorveterias, açougues, mercados, distribuidoras de bebidas |
| `climatizacao`: Ar-condicionado | clínicas, consultórios, academias, escritórios, escolas |
| `limpeza`: Limpeza e conservação | escritórios, clínicas, condomínios, coworkings, hotéis |
| `dedetizacao`: Controle de pragas | restaurantes, padarias, escolas, creches, condomínios |
| `extintores`: Prevenção de incêndio | restaurantes, postos, oficinas, galpões, casas de festas |
| `seguranca`: Segurança eletrônica | lojas, farmácias, postos, óticas, condomínios |
| `ti`: Suporte de TI e redes | escritórios de contabilidade e advocacia, clínicas, imobiliárias |
| `contabilidade`: Contabilidade | salões, pet shops, lojas, restaurantes, academias |
| `marketing`: Marketing digital | restaurantes, salões, clínicas de estética, imobiliárias |
| `manutencao_predial`: Manutenção predial | condomínios, escolas, clínicas, hotéis, galpões |
| `coifas`: Coifas e cozinhas industriais | restaurantes, pizzarias, churrascarias, buffets |
| `lavanderia`: Lavanderia e enxoval | hotéis, pousadas, motéis, salões, spas |

Para criar o seu de vez, copie um bloco de [`prospecta/perfis.json`](prospecta/perfis.json) e ajuste
os `alvos`, os `sinais` e a `mensagem`. Ou peça ao seu agente para fazer isso.

## Como funciona

1. O endereço vira coordenadas: CEP pelo ViaCEP e endereços pelo OpenStreetMap.
2. O raio é coberto por vários pontos de busca no Google Maps. Isso passa do limite de ~120
   resultados por busca e mantém tudo dentro do raio. As buscas usam o
   [google-maps-scraper-kit](https://github.com/mahanaicoach/google-maps-scraper-kit), que roda no seu
   computador com o Chrome, sem janela.
3. Repetidos, empresas fora do raio e empresas fechadas definitivamente são descartados.
4. Os sites são lidos para achar links de WhatsApp. "Sites" que são só Instagram ou WhatsApp contam
   como "sem site próprio".
5. Cada empresa recebe uma nota:

   | Critério | Pontos |
   |---|---|
   | Distância | até 35 |
   | Contato: WhatsApp confirmado 20, celular 18, fixo 10, +5 com e-mail ou Instagram | até 25 |
   | Porte: número de avaliações no Google | até 20 |
   | Sinais de necessidade nas avaliações (`--modo completo`) | até 20 |

Antes de começar, a busca mostra a estimativa de tempo. Em geral, leva de 5 a 30 minutos: menos
tipos de negócio e raio menor deixam mais rápido.

## Privacidade e segurança

- **Dados:** as buscas, os resultados e os status ficam no seu computador (`dados/` e `resultados/`).
- **Login do ChatGPT:**
  - fica em `~/.config/prospecta/` (no Windows, `%APPDATA%\prospecta`), num arquivo que só o seu
    usuário lê;
  - o Prospecta nunca vê a sua senha e não tem acesso às suas conversas do ChatGPT;
  - em "sair", a sessão é encerrada na OpenAI;
  - para cortar o acesso de vez, desconecte o Prospecta nas configurações do ChatGPT.
- **O que vai para a OpenAI:** só o que você conversa com o assistente e os dados que ele consulta
  para responder (nomes, bairros e contatos públicos das empresas).
- **O painel** só atende o próprio computador (127.0.0.1) e recusa pedidos de outros sites.

## Cuidados

- **Use com moderação.** Raspar o Google Maps vai contra os termos de uso do Google. Quem busca
  demais fica temporariamente bloqueado (por horas, não na sua conta Google). Faça uma busca por vez,
  algumas por dia.
- **WhatsApp:** "provável" quer dizer celular, "possível" quer dizer fixo (pode ter WhatsApp
  Business) e "confirmado" quer dizer que o site tem link de WhatsApp. Mande mensagens
  personalizadas, uma por uma. Disparo em massa leva ao banimento do número.
- **LGPD:** são dados públicos de empresas, usados para oferta de serviço B2B. Identifique-se, diga de
  onde veio o contato se perguntarem e atenda na hora quem pedir para não ser mais procurado.
- **Rotas:** distância e tempo são estimativas. O trajeto real é calculado pelo Google Maps quando
  você abre o link.

## Opcional: usar pelo celular, com Telegram

O mesmo sistema pode virar um bot privado de Telegram. Você manda um endereço ou a localização e
recebe a lista, as fichas com botão de WhatsApp, a rota, a planilha, o mapa e um mini-CRM (/funil).
O computador ou servidor onde ele roda precisa ficar ligado.

1. No Telegram, fale com o [@BotFather](https://t.me/BotFather), mande `/newbot` e copie o token
   para `TELEGRAM_TOKEN` no `.env`.
2. Rode `python3 -m prospecta bot` e mande `/start` ao seu bot. Ele responde com o seu ID. Coloque o
   ID em `USUARIOS_PERMITIDOS` no `.env` e reinicie o bot.
3. Num servidor (VPS), `docker compose up -d --build` sobe o motor e o bot juntos. O bot não precisa
   de IP público nem de porta aberta.

Comandos do bot:

| Comando | O que faz |
|---|---|
| `/perfil` | Escolhe o serviço que você presta |
| `/alvos padaria, hotel` | Procura tipos de negócio específicos |
| `/raio 3` | Raio em km |
| `/modo` | Rápido ou completo |
| `/empresa Ana \| Frio Total` | Quem assina a mensagem |
| `/base Rua X, 100` | Ponto de partida das rotas |
| `/lista`, `/rota 8`, `/planilha` | Lista, rota e arquivos da última busca |
| `/funil` | Resumo dos contatos que você marcou |
| `/novos` | Mostra só empresas que você ainda não recebeu |
| `/config`, `/cancelar` | Ver configurações e cancelar a busca em andamento |

## Autor

**Rodrigo Florencio** é especialista em Inteligência Artificial pelo PECE-USP, professor convidado no MBA
de Inteligência Artificial Aplicada a Negócios da FAAP e fundador da [GenSearch Me](https://www.gensearch.me/),
startup de monitoramento e visibilidade de produtos e marcas de saúde nas IAs.

- LinkedIn: [rodrigoflorencio](https://www.linkedin.com/in/rodrigoflorencio/)

### Crédito ao usar

O Prospecta é gratuito. Se ele for útil no seu trabalho, ou se você criar algo a partir dele, por favor
**dê crédito ao autor**: cite o Rodrigo Florencio e o link deste repositório no seu README, site ou
aplicação. O motor de busca usado por baixo é o
[google-maps-scraper-kit](https://github.com/mahanaicoach/google-maps-scraper-kit) (licença MIT).

## Para desenvolvedores

```bash
python3 -m unittest discover -s tests -t .    # testes sem internet (motor, OpenAI e Telegram simulados)
python3 -m prospecta empacotar-extensao       # gera dist/prospecta-<versão>.mcpb (extensão do Claude Desktop)
```

A extensão segue o formato [MCP Bundle](https://github.com/modelcontextprotocol/mcpb), versão 0.4 do
manifesto, com o tipo `uv`. Os arquivos-fonte ficam em `prospecta/extensao.py` e `extensao/icon.png`.

```
prospecta/
  __main__.py   linha de comando (instalar, buscar, motor, perfis, verificar, bot)
  kit.py        baixa e liga o motor do google-maps-scraper-kit
  busca.py      cobertura do raio, junção, filtros, enriquecimento e nota
  motor.py      cliente da API do motor
  geo.py        distância, malha de cobertura, geocodificação (ViaCEP + Nominatim)
  telefone.py   telefones brasileiros, celular x fixo, links wa.me
  sites.py      lê os sites atrás de WhatsApp (bloqueia endereços de rede interna)
  qualifica.py  nota de prioridade
  rotas.py      rota otimizada e links Google Maps / Waze
  relatorio.py  relatório HTML
  exporta.py    planilha XLSX/CSV e mapa KML
  banco.py      histórico e status dos contatos (SQLite)
  ferramentas.py  operações usadas pelo painel, chat e MCP; buscas em processo próprio
  painel.py, painel.html  painel local no navegador
  chatgpt.py    "Sign in with ChatGPT": OAuth PKCE, validação RS256, renovação e revogação
  chat.py       assistente: API Responses (streaming) com as ferramentas do Prospecta
  mcp_servidor.py  servidor MCP (stdio) para Claude Code, Claude Desktop e Codex
  extensao.py   gera a extensão do Claude Desktop (.mcpb)
  desktop.py    registra o servidor no claude_desktop_config.json (conectar claude-desktop)
  bot.py, telegram.py   bot de Telegram opcional
  perfis.json   serviços prontos
```
