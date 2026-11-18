---
name: prospectar
description: Encontra empresas (prospects B2B) perto de um endereço para um prestador de serviço autônomo, com telefone, WhatsApp, e-mail, nota de prioridade, rota de visitas, planilha e relatório HTML, rodando localmente sobre o Google Maps. Use quando o usuário quiser achar clientes, leads ou prospects na região dele, "empresas perto de mim que precisam de X", ou montar uma lista para visitar ou chamar no WhatsApp.
---

# Prospectar

Siga o passo a passo de [AGENTS.md](../../../AGENTS.md):

1. Instale uma vez: `python3 -m prospecta instalar`.
2. Entenda o serviço, o endereço, o raio e a assinatura da mensagem.
3. Escolha um perfil (`python3 -m prospecta perfis --json`) ou monte `--alvos`, `--sinais` e
   `--mensagem` sob medida.
4. Rode `python3 -m prospecta buscar …`, uma busca por vez.
5. Mostre o `resumo.md` e ofereça abrir o `relatorio.html`.

Nunca envie mensagens pelo usuário nem automatize disparos. Os dados ficam no computador dele.
