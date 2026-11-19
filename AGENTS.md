# Instruções para o agente de IA (Claude Code, Codex, Cursor, Gemini CLI…)

Você está ajudando um **profissional autônomo brasileiro**, em geral sem conhecimento técnico, a
encontrar empresas que podem contratar o serviço dele (prospecção B2B) perto de um endereço. Tudo roda
no computador dele. Fale em **português simples**, sem jargão, e faça você os passos técnicos.

Todos os comandos abaixo rodam **dentro desta pasta** (`prospecta-bot/`). No Windows, troque
`python3` por `py`.

## 0. Se você tem as ferramentas MCP `prospecta`

Se o seu ambiente já mostra as ferramentas do servidor MCP `prospecta` (`iniciar_busca`,
`estado_busca`, `consultar_prospects`, `planejar_rota`, `mensagem_whatsapp`, `marcar_prospect`,
`exportar`…), **use-as em vez dos comandos abaixo**. As regras deste arquivo continuam valendo. Para
o usuário ver tudo com mapa e botões, ofereça também o painel: `python3 -m prospecta painel`.

## 1. Instalação (uma vez)

```bash
python3 --version              # precisa ser 3.9 ou mais novo
python3 -m prospecta instalar --sem-painel   # baixa o motor de busca, liga e confere
```

Depois da instalação, ofereça ao usuário três jeitos de seguir:

- **Painel no navegador**: `python3 -m prospecta painel` (deixa o terminal ocupado; rode em segundo
  plano se puder). Tem busca, mapa, contatos e um assistente que usa o plano do ChatGPT dele.
- **Ferramentas MCP no Claude Code ou no Codex**: `python3 -m prospecta conectar claude` (ou
  `codex`). Depois, reinicie o agente.
- **Você mesmo roda as buscas**, pelos comandos abaixo.

- Sem Python: oriente a instalar em https://www.python.org/downloads/ (no Windows, marcar "Add
  python.exe to PATH") e tente de novo.
- O `instalar` usa o Chrome do computador. Sem Chrome, o motor baixa um (~100 MB) na primeira vez.
- `openpyxl` é opcional (planilha .xlsx). Sem ele, a planilha sai em .csv. Para instalar:
  `python3 -m pip install openpyxl`.
- Porta 8080 ocupada: crie ou edite o `.env` com `MOTOR_URL=http://localhost:8081` e rode de novo.
- Peça um e-mail ao usuário e coloque em `CONTATO_GEOCODER` no `.env`. O serviço público de mapas
  (OpenStreetMap) pede um contato de quem usa.

## 2. Entender o que o usuário precisa

Pergunte só o que faltar, de uma vez:

1. **Qual serviço ele presta** e para que tipo de cliente.
2. **De onde partir**: o endereço da empresa dele ou a região que quer cobrir (rua e número com
   cidade, CEP ou "latitude, longitude").
3. **Raio**: padrão 3 km. Sugira de 1 a 5 km. Raio maior demora mais e aumenta o risco de bloqueio.
4. **Nome e empresa** para assinar a mensagem de WhatsApp (opcional).

Depois, monte a busca:

- Rode `python3 -m prospecta perfis --json` e veja se algum **perfil pronto** serve (refrigeração,
  climatização, limpeza, dedetização, extintores, segurança, TI, contabilidade, marketing,
  manutenção predial, coifas, lavanderia). Se servir, use `--perfil <chave>`.
- Se nenhum servir, **monte um sob medida**:
  - `--alvos`: 5 a 12 tipos de negócio, escritos como alguém digitaria no Google Maps, em português,
    no singular. Ex.: "padaria, hotel, academia". Menos tipos deixam a busca mais rápida.
  - `--servico`: o nome do serviço dele.
  - `--sinais`: palavras que, nas avaliações do Google, indicam que o lugar precisa do serviço. Ex.:
    para manutenção de fornos, "forno, queimado, cru, demora".
  - `--mensagem`: uma abordagem curta e educada para WhatsApp, usando `{prospect}`, `{bairro}`,
    `{meu_nome}` e `{minha_empresa}`. Sem promessas que ele não possa cumprir. Mostre ao usuário
    antes de usar.
- Se ele quiser reaproveitar o perfil sob medida, adicione um bloco em `prospecta/perfis.json`,
  seguindo o formato dos outros.

## 3. Rodar a busca

```bash
python3 -m prospecta buscar "Rua Exemplo, 100, Campinas SP" --raio 3 --perfil limpeza \
    --empresa "Ana Souza | Brilho Limpeza"
python3 -m prospecta buscar "13010-001" --raio 2 --alvos "padaria, pizzaria, hotel" \
    --servico "Manutenção de fornos" --sinais "forno, queimado" --empresa "João | Forno Certo"
```

Outras opções:

- `--base "endereço da empresa"`: ponto de partida das rotas, quando ele é diferente do centro da busca.
- `--modo completo`: mais resultados e leitura das avaliações (sinais), mas várias vezes mais lento.
- `--so-novos`: esconde quem já apareceu em buscas anteriores. Bom para repetir a busca todo mês.

**Antes de rodar**, diga ao usuário a estimativa de tempo que o comando imprime (em geral, de 5 a
30 minutos). Rode em segundo plano se o seu ambiente permitir e avise quando terminar. **Uma busca
por vez**, e no máximo umas 10 por dia: o Google bloqueia temporariamente quem busca demais.

## 4. Mostrar o resultado

O comando cria uma pasta em `resultados/<data>_<serviço>_<local>_<n>/` com:

| Arquivo | Para quê |
|---|---|
| `resumo.md` | **Mostre este ao usuário**: totais, top 15 com link de WhatsApp e a rota sugerida |
| `relatorio.html` | Página para abrir no navegador: filtros, botões de WhatsApp, rota e Waze, mapa, status de contato |
| `prospects.xlsx` | Planilha completa, com colunas para acompanhar os contatos |
| `prospects.kml` | Mapa para importar em mymaps.google.com |
| `prospects.json` | Os mesmos dados, para outros programas |

- Mostre o `resumo.md`. Não despeje todas as linhas no chat.
- Ofereça abrir o relatório: `open relatorio.html` (Mac), `start relatorio.html` (Windows) ou
  `xdg-open relatorio.html` (Linux).
- Explique a **nota** (0 a 100, prioridade A/B/C). Ela soma:
  - distância;
  - forma de contato: WhatsApp confirmado, celular, fixo, e-mail;
  - porte, estimado pelas avaliações;
  - sinais de necessidade nas avaliações.
- Explique o **WhatsApp**:
  - "provável": é celular;
  - "possível": é fixo, que pode ter WhatsApp Business;
  - "confirmado": o site da empresa tem link de WhatsApp.
- Sugira próximos passos: começar pelos A mais próximos, fazer a rota de visitas, repetir com
  `--so-novos` no mês seguinte.

## Regras (não negocie)

- **Não envie mensagens** pelo usuário nem automatize disparos de WhatsApp, e-mail ou SMS. Os links só
  abrem a conversa; quem envia é ele, uma por uma. Disparo em massa leva ao banimento do número.
- **Os dados ficam no computador dele.** Não envie os resultados para serviços externos sem pedido
  explícito.
- **LGPD:** são dados públicos de empresas, para contato comercial B2B. Oriente o usuário a se
  identificar, dizer de onde veio o contato se perguntarem e atender quem pedir para não ser mais
  procurado.
- Busque só negócios no Google Maps. Não raspe Instagram, Facebook ou outras redes.
- Não aumente limites (raio, buscas por dia) para "ir mais rápido". Se o Google bloquear, espere
  algumas horas.
- Nunca leia, mostre ou copie as credenciais do ChatGPT (`~/.config/prospecta/contas.json`).

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `motor de busca … não responde` | `python3 -m prospecta motor ligar`; veja `motor status` |
| `endereço não encontrado` | Peça o CEP, ou passe as coordenadas "lat, lon" (dá para copiar do Google Maps clicando com o botão direito no lugar) |
| `serviço de mapas não respondeu` | Espere um minuto e repita; confira `CONTATO_GEOCODER` no `.env` |
| `unusual traffic` / "O Google limitou" | Pare e tente de novo em algumas horas, com raio menor |
| Poucos resultados | Aumente o raio, use `--modo completo` ou ajuste `--alvos` (termos mais comuns) |
| Busca demorada demais | Menos `--alvos`, raio menor, modo rápido |

## Referência

```
python3 -m prospecta instalar [--sem-painel] | verificar | perfis [--json]
python3 -m prospecta painel [--porta N] [--nao-abrir]
python3 -m prospecta conectar claude|codex     # registra o servidor MCP
python3 -m prospecta chatgpt status|sair       # conta do ChatGPT do assistente do painel
python3 -m prospecta motor ligar|desligar|status|reiniciar
python3 -m prospecta buscar ENDEREÇO [--raio KM] (--perfil CHAVE | --alvos "a, b") [--servico ...]
        [--sinais "a, b"] [--mensagem "..."] [--empresa "Nome | Empresa"] [--base ENDEREÇO]
        [--modo rapido|completo] [--so-novos] [--top N] [--saida PASTA]
python3 -m prospecta bot      # opcional: o mesmo pelo Telegram (veja README)
```

Para atualizar o projeto: `git pull` na pasta do repositório. O motor de busca fica em
`motor/google-maps-scraper-kit` e pode ser apagado; o `instalar` baixa de novo.
