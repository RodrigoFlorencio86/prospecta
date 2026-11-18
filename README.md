# Prospecta: prospecção B2B por raio, pelo Telegram

O prestador de serviço manda um **endereço**, um **CEP** ou a **localização** para um bot no Telegram.
O bot procura no Google Maps, dentro do raio escolhido, os negócios que podem contratar o serviço dele
e devolve:

- **Lista priorizada** (nota de 0 a 100, prioridade A/B/C), 10 por página
- **Ficha de cada prospect**: telefone (celular ou fixo), WhatsApp, e-mail, site, Instagram, nota e
  avaliações no Google, horário, distância e sinais de necessidade encontrados nas avaliações
- **Botão de WhatsApp** que abre a conversa com uma mensagem de abordagem já escrita, com o nome do
  prospect, o bairro, o seu nome e a sua empresa
- **Rota otimizada de visitas** saindo da sua empresa, aberta direto no Google Maps (em trechos de até
  9 paradas), além de link de rota e Waze para cada prospect
- **Planilha (XLSX)** com todos os dados, links clicáveis e colunas para acompanhar os contatos
- **Mapa (KML)** para importar no Google My Maps, com cores por prioridade
- **Mini-CRM**: marque cada prospect como interessado, contatado, visitar, cliente ou sem interesse, e
  anote observações. O comando /funil mostra o resumo.
- **Só prospects novos**: o modo /novos esconde o que você já recebeu em buscas anteriores

Os dados vêm do motor do [google-maps-scraper-kit](https://github.com/mahanaicoach/google-maps-scraper-kit),
que roda no seu computador ou servidor. Não usa API paga nem chave do Google.

## Para quais serviços

Funciona para qualquer prestador B2B. Há 12 perfis prontos em [`prospecta/perfis.json`](prospecta/perfis.json):

| Perfil | Procura por (exemplos) |
|---|---|
| Refrigeração comercial | padarias, sorveterias, açougues, mercados, distribuidoras de bebidas |
| Ar-condicionado e climatização | clínicas, consultórios, academias, escritórios, escolas |
| Limpeza e conservação | escritórios, clínicas, condomínios, coworkings, hotéis |
| Dedetização e controle de pragas | restaurantes, padarias, escolas, creches, condomínios |
| Prevenção de incêndio | restaurantes, postos, oficinas, galpões, casas de festas |
| Segurança eletrônica | lojas, farmácias, postos, óticas, condomínios |
| Suporte de TI e redes | escritórios de contabilidade e advocacia, clínicas, imobiliárias |
| Contabilidade e BPO financeiro | salões, pet shops, lojas, restaurantes, academias |
| Marketing digital | restaurantes, salões, clínicas de estética, imobiliárias |
| Manutenção predial | condomínios, escolas, clínicas, hotéis, galpões |
| Coifas e cozinhas industriais | restaurantes, pizzarias, churrascarias, buffets |
| Lavanderia e enxoval | hotéis, pousadas, motéis, salões, spas |

Nenhum serve? No bot, use `/alvos padaria, hotel, academia` (até 20 tipos). Para criar um perfil
permanente, copie um bloco do `perfis.json`. Cada perfil tem quatro partes:

- `alvos`: tipos de negócio a procurar, como você digitaria no Google Maps
- `sinais`: palavras nas avaliações que indicam necessidade (ex.: "freezer", "calor", "barata")
- `mensagem`: a abordagem sugerida, com `{prospect}`, `{bairro}`, `{meu_nome}` e `{minha_empresa}`
- `nome` e `descricao`: como o perfil aparece no bot

## Como a busca funciona

1. O endereço vira coordenadas: CEP pelo ViaCEP e endereços pelo OpenStreetMap (Nominatim).
2. O círculo do raio é coberto por uma malha de pontos de busca. É isso que passa do limite de
   ~120 resultados por busca do Google e mantém a busca dentro do raio.
3. Em cada ponto, o motor procura todos os tipos de negócio do perfil, em português e com o Google
   configurado para o Brasil.
4. Os resultados são juntados sem repetição. Saem quem está fora do raio e quem está fechado
   definitivamente.
5. Os sites das empresas são lidos para achar links de WhatsApp. "Sites" que são só Instagram ou
   wa.me contam como "sem site próprio".
6. Cada prospect recebe uma nota:

   | Critério | Pontos |
   |---|---|
   | Distância da base | até 35 |
   | Contato: WhatsApp confirmado 20, celular 18, fixo 10, +5 com e-mail ou Instagram | até 25 |
   | Porte: número de avaliações no Google | até 20 |
   | Sinais de necessidade nas avaliações (modo completo) | até 20 |

**Modos de busca** (comando /modo):

- **rápido**: ~20 lugares por tipo em cada ponto, sem ler avaliações.
- **completo**: ~60 lugares por tipo, pontos mais próximos e 3 avaliações por lugar. Encontra mais e
  detecta sinais de necessidade, mas leva várias vezes mais tempo.

Antes de começar, o bot mostra quantas áreas vai pesquisar e o tempo estimado. Menos tipos de
negócio e raio menor deixam a busca mais rápida.

## Instalação

### 1. Crie o bot no Telegram

Fale com o [@BotFather](https://t.me/BotFather), mande `/newbot`, escolha nome e usuário e copie o token.

### 2. Configure

```bash
cd prospecta-bot
cp .env.example .env
# edite o .env: TELEGRAM_TOKEN, USUARIOS_PERMITIDOS e CONTATO_GEOCODER
```

O bot é privado: só responde aos IDs em `USUARIOS_PERMITIDOS`. Não sabe o seu ID? Ligue o bot,
mande /start, e ele responde com o ID. Coloque-o no `.env` e reinicie.

### 3a. Rodar com Docker (recomendado para servidor ou VPS)

```bash
docker compose up -d --build
docker compose logs -f bot
```

Isso sobe o motor de busca (Chrome sem janela) e o bot. Nada fica exposto na internet: o bot usa
long polling, então não precisa de IP público nem de porta aberta. Uma VPS pequena (2 GB de RAM)
dá conta.

### 3b. Rodar sem Docker (no seu computador)

Precisa de Python 3.9+ e Google Chrome.

```bash
git clone https://github.com/mahanaicoach/google-maps-scraper-kit.git
python3 google-maps-scraper-kit/scripts/engine.py start      # motor em localhost:8080

cd prospecta-bot
pip install -r requirements.txt        # opcional: sem isso a planilha sai em CSV
python3 -m prospecta verificar         # testa motor, mapas e Telegram
python3 -m prospecta bot
```

### Sem Telegram, pela linha de comando

```bash
python3 -m prospecta perfis
python3 -m prospecta buscar "Av. Brasil, 1000, Campinas" --raio 3 --perfil dedetizacao \
    --empresa "Ana | Casa Limpa" --saida resultados
python3 -m prospecta buscar "13010-001" --alvos "padaria, sorveteria" --modo completo
```

## Comandos do bot

| Comando | O que faz |
|---|---|
| *endereço, CEP ou 📎 localização* | Mostra o resumo da busca (serviço, raio, tempo estimado) e pede confirmação |
| `/perfil` | Escolhe o serviço que você presta |
| `/alvos padaria, hotel` | Procura tipos de negócio específicos (`/alvos limpar` volta ao padrão) |
| `/raio 3` | Raio em km. Também dá para trocar por botões na confirmação |
| `/modo` | Rápido ou completo |
| `/empresa Ana \| Frio Total` | Seu nome e empresa, usados na mensagem de WhatsApp |
| `/base Rua X, 100, Cidade` | Endereço da sua empresa, ponto de partida das rotas |
| `/lista`, `/rota 8`, `/planilha` | Lista, rota e arquivos da última busca |
| `/funil` | Resumo do mini-CRM |
| `/novos` | Liga ou desliga o modo "só o que eu ainda não recebi" |
| `/config`, `/cancelar` | Ver configurações e cancelar a busca em andamento |

## Limites e cuidados

- **Bloqueio do Google**: raspar o Google Maps vai contra os termos de uso do Google e, em excesso,
  leva a bloqueio temporário do IP. O bot limita as buscas por dia (`BUSCAS_POR_DIA`) e faz uma
  busca por vez. Se o Google bloquear, a busca para e entrega o que já encontrou.
- **WhatsApp**: "provável" quer dizer celular, "possível" quer dizer fixo (pode ter WhatsApp
  Business) e "confirmado" quer dizer que o site tem link de WhatsApp. Mande mensagens
  personalizadas e em pequena quantidade. Disparo em massa leva ao banimento do número.
- **LGPD**: são dados públicos de empresas, usados para oferta B2B (base legal: legítimo interesse).
  Identifique-se na mensagem, explique de onde veio o contato se perguntarem, e atenda na hora quem
  pedir para não ser mais contatado (marque como "sem interesse").
- **Rotas**: sem `OSRM_URL`, distância e tempo são estimativas (linha reta × 1,35 a 22 km/h). O
  trajeto real é calculado pelo Google Maps quando você abre o link.
- **Geocodificação**: o Nominatim público aceita 1 pedido por segundo e pede um e-mail de contato
  (`CONTATO_GEOCODER`). Se o endereço não for achado, mande a localização pelo Telegram.

## Testes

```bash
python3 -m unittest discover -s tests -t .
```

Os testes usam um motor, um geocodificador e um Telegram falsos, então não precisam de internet.

## Estrutura

```
prospecta/
  bot.py        bot do Telegram: comandos, botões, fila de buscas, mini-CRM
  busca.py      orquestra a busca: cobertura do raio, junção, filtros, enriquecimento, nota
  motor.py      cliente da API do google-maps-scraper-kit
  geo.py        distância, malha de cobertura, geocodificação (ViaCEP + Nominatim)
  telefone.py   telefones brasileiros, celular x fixo, links wa.me
  sites.py      leitura dos sites para achar WhatsApp (bloqueia endereços de rede interna)
  qualifica.py  nota de prioridade
  rotas.py      rota otimizada, links Google Maps / Waze, OSRM opcional
  exporta.py    planilha XLSX/CSV e mapa KML
  banco.py      SQLite: preferências, buscas e status dos prospects
  perfis.json   serviços prontos (edite à vontade)
```
