"""Servidor MCP (Model Context Protocol) por stdio, só com a biblioteca padrão.

Dá ao Claude Code, ao Codex ou a outro cliente MCP as mesmas ferramentas do painel: buscar prospects,
acompanhar a busca, filtrar, marcar status, montar rota e mensagem, exportar. As buscas rodam num
processo próprio, então continuam mesmo se o cliente for fechado.

O stdout é exclusivo do protocolo (JSON-RPC, uma mensagem por linha); todo o resto vai para o stderr."""
import json
import sys

from . import __version__
from .ferramentas import FERRAMENTAS, Prospecta, chamar, schema

VERSOES = ("2025-06-18", "2025-03-26", "2024-11-05")
SOMENTE_LEITURA = {"listar_perfis", "ver_configuracao", "estado_busca", "listar_tarefas", "listar_buscas",
                   "consultar_prospects", "detalhar_prospect", "mensagem_whatsapp", "planejar_rota", "resumo_funil"}
INSTRUCOES = (
    "Prospecta encontra empresas (prospects B2B) num raio em volta de um endereço, para um prestador de serviço "
    "autônomo brasileiro. Fale em português simples. Antes de iniciar_busca, confirme endereço, raio (1 a 5 km) "
    "e o que procurar (um perfil de listar_perfis ou alvos sob medida). Buscas levam de 5 a 30 minutos e rodam "
    "em segundo plano: informe a estimativa e use estado_busca para acompanhar. Uma busca por vez. Mostre "
    "resultados resumidos (consultar_prospects) e ofereça rota, mensagens e exportar (relatório HTML e planilha). "
    "Nunca envie mensagens pelo usuário: os links de WhatsApp só abrem a conversa.")


def ferramentas_mcp():
    saida = []
    for f in FERRAMENTAS:
        t = {"name": f["nome"], "description": f["descricao"], "inputSchema": schema(f)}
        t["annotations"] = {"readOnlyHint": f["nome"] in SOMENTE_LEITURA, "openWorldHint": f["nome"] == "iniciar_busca"}
        saida.append(t)
    return saida


class ServidorMCP:
    def __init__(self, app):
        self.app = app

    def tratar(self, msg):
        """Uma mensagem JSON-RPC -> resposta (dict) ou None para notificações."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _erro(None, -32600, "requisição inválida")
        metodo, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
        notificacao = "id" not in msg
        if metodo == "initialize":
            pedida = params.get("protocolVersion")
            return _ok(mid, {"protocolVersion": pedida if pedida in VERSOES else VERSOES[0],
                             "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": {"name": "prospecta", "title": "Prospecta", "version": __version__},
                             "instructions": INSTRUCOES})
        if notificacao:
            return None  # notifications/initialized, cancelled, etc.
        if metodo == "ping":
            return _ok(mid, {})
        if metodo == "tools/list":
            return _ok(mid, {"tools": ferramentas_mcp()})
        if metodo == "tools/call":
            nome, args = params.get("name"), params.get("arguments") or {}
            resultado, erro = chamar(self.app, nome, args)
            texto = json.dumps(resultado, ensure_ascii=False, indent=1, default=str)
            corpo = {"content": [{"type": "text", "text": texto}], "isError": erro}
            if isinstance(resultado, dict) and not erro:
                corpo["structuredContent"] = json.loads(json.dumps(resultado, default=str))
            return _ok(mid, corpo)
        return _erro(mid, -32601, f"método não suportado: {metodo}")


def _ok(mid, resultado):
    return {"jsonrpc": "2.0", "id": mid, "result": resultado}


def _erro(mid, codigo, mensagem):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": codigo, "message": mensagem}}


def servir(cfg, entrada=None, saida=None):
    entrada = entrada or sys.stdin
    protocolo = saida or sys.stdout
    sys.stdout = sys.stderr  # qualquer print perdido vai para o stderr, nunca para o protocolo
    app = Prospecta(cfg, log=lambda *a: print(*a, file=sys.stderr))
    srv = ServidorMCP(app)
    for linha in entrada:
        linha = linha.strip()
        if not linha:
            continue
        try:
            msg = json.loads(linha)
        except ValueError:
            resposta = _erro(None, -32700, "JSON inválido")
        else:
            if isinstance(msg, list):  # lote (versões antigas do protocolo)
                resposta = [r for r in (srv.tratar(m) for m in msg) if r is not None] or None
            else:
                try:
                    resposta = srv.tratar(msg)
                except Exception as ex:  # nunca derrubar o servidor por uma chamada
                    print(f"erro tratando {msg.get('method')}: {ex!r}", file=sys.stderr)
                    resposta = _erro(msg.get("id"), -32603, f"erro interno: {ex}")
        if resposta is not None:
            protocolo.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            protocolo.flush()
    return 0
