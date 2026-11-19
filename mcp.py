"""Lançador do servidor MCP do Prospecta: funciona de qualquer pasta.

Claude Code:  claude mcp add --scope user prospecta -- python3 /caminho/para/prospecta-bot/mcp.py
Codex:        codex mcp add prospecta -- python3 /caminho/para/prospecta-bot/mcp.py
(ou simplesmente: python3 -m prospecta conectar claude|codex)"""
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
os.chdir(AQUI)

from prospecta.__main__ import main  # noqa: E402

sys.exit(main(["mcp"]))
