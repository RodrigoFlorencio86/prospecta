# Prospecta: encontre clientes para o seu serviço perto de você

Ferramenta gratuita e de código aberto para **profissionais autônomos e pequenas empresas de
serviço**. Diga o que você faz e de onde quer partir, e ela procura no Google Maps, num raio de
alguns quilômetros, as empresas que podem contratar você: padarias para quem conserta freezer,
clínicas para quem limpa ar-condicionado, restaurantes para quem faz dedetização, e assim por diante.

Tudo roda **no seu computador**. Não precisa de conta, assinatura ou chave de API, e os dados não saem
da sua máquina.

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

## Como usar: entregue o link ao seu agente de IA

O jeito mais fácil é pedir a um **agente de IA que roda no seu computador** para fazer tudo por você.
Ele instala, faz as perguntas certas, roda a busca e mostra o resultado. Funciona com:

- **Claude Code**: no terminal ou na aba "Code" do app Claude para desktop
- **Codex**, o agente do ChatGPT: no app do Codex, no terminal ou no VS Code
- **Cursor**, **Gemini CLI** ou outro agente que execute comandos no seu computador

> O ChatGPT e o Claude **comuns, no navegador**, não conseguem rodar programas no seu computador.
> Use um dos agentes acima.

Abra o agente numa pasta qualquer e cole a mensagem abaixo, trocando o que está entre colchetes:

```text
Clone https://github.com/RodrigoFlorencio86/AI-Stuff e siga o arquivo prospecta-bot/AGENTS.md
para instalar e me ajudar a encontrar clientes. Eu trabalho com [seu serviço, ex.: manutenção de
ar-condicionado] e minha empresa fica em [endereço ou CEP]. Quero procurar num raio de [3] km.
Meu nome e empresa para as mensagens: [Seu Nome | Sua Empresa].
```

O agente lê o [`AGENTS.md`](AGENTS.md), que tem o passo a passo e as regras: uma busca por vez,
nada de envio automático de mensagens, dados só no seu computador. O Claude Code também carrega a
skill `prospectar` desta pasta.

## Como usar sem agente

Precisa de **Python 3.9+** ([download](https://www.python.org/downloads/); no Windows, marque
"Add python.exe to PATH") e, de preferência, do Google Chrome. No Windows, troque `python3` por `py`.

```bash
git clone https://github.com/RodrigoFlorencio86/AI-Stuff.git
cd AI-Stuff/prospecta-bot
python3 -m prospecta instalar          # baixa o motor de busca e confere tudo (uma vez)
python3 -m prospecta perfis            # serviços prontos

python3 -m prospecta buscar "Rua Exemplo, 100, Campinas SP" --raio 3 --perfil climatizacao \
    --empresa "Ana Souza | Clima Bom"
```

Serviço que não está na lista? Diga o que procurar:

```bash
python3 -m prospecta buscar "13010-001" --raio 2 --alvos "padaria, pizzaria, hotel" \
    --servico "Manutenção de fornos" --sinais "forno, queimado" --empresa "João | Forno Certo"
```

O resultado fica em `resultados/<data>_<serviço>_<local>/`. Abra o `relatorio.html` no navegador.

### Opções da busca

| Opção | Para quê |
|---|---|
| `--raio 3` | Raio em km (padrão 3). De 1 a 5 km costuma ser o ideal |
| `--perfil limpeza` | Usa um serviço pronto (lista: `python3 -m prospecta perfis`) |
| `--alvos "a, b, c"` | Tipos de negócio a procurar, como você digitaria no Google Maps |
| `--servico "..."` | Nome do seu serviço, quando usar `--alvos` |
| `--sinais "a, b"` | Palavras nas avaliações que indicam necessidade (ex.: "calor", "barata") |
| `--mensagem "..."` | Sua mensagem de WhatsApp, com `{prospect}`, `{bairro}`, `{meu_nome}` e `{minha_empresa}` |
| `--empresa "Nome \| Empresa"` | Quem assina a mensagem |
| `--base "endereço"` | Ponto de partida das rotas, se for diferente do centro da busca |
| `--modo completo` | Mais resultados e leitura das avaliações, mas várias vezes mais lento |
| `--so-novos` | Esconde empresas que já apareceram em buscas anteriores |
| `--rota 10` | Quantas das melhores entram na rota sugerida (0 para nenhuma) |

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

## Para desenvolvedores

```bash
python3 -m unittest discover -s tests -t .    # testes sem internet (motor e Telegram simulados)
```

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
  bot.py, telegram.py   bot de Telegram opcional
  perfis.json   serviços prontos
```
