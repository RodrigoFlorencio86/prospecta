"""conectar claude-desktop: preserva o que já existe, faz cópia, recusa JSON quebrado, remove."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from prospecta import __main__ as cli, desktop


class DesktopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = self.tmp / "Claude" / "claude_desktop_config.json"

    def test_adiciona_preservando_o_resto(self):
        self.cfg.parent.mkdir(parents=True)
        original = {"mcpServers": {"outro": {"command": "npx", "args": ["x"]}}, "preferencia": True}
        self.cfg.write_text(json.dumps(original), encoding="utf-8")
        r = desktop.conectar([self.cfg], python="/usr/bin/python3", lancador="/opt/prospecta/mcp.py")
        self.assertEqual(r, [(self.cfg, "adicionado")])
        d = json.loads(self.cfg.read_text(encoding="utf-8"))
        self.assertEqual(d["mcpServers"]["outro"], original["mcpServers"]["outro"])
        self.assertTrue(d["preferencia"])
        self.assertEqual(d["mcpServers"]["prospecta"]["args"], [str(Path("/opt/prospecta/mcp.py").resolve())])
        copias = list(self.cfg.parent.glob("claude_desktop_config.json.bak-*"))
        self.assertEqual(len(copias), 1)
        self.assertEqual(json.loads(copias[0].read_text()), original)
        # de novo: nada muda, nenhuma cópia nova
        self.assertEqual(desktop.conectar([self.cfg], python="/usr/bin/python3", lancador="/opt/prospecta/mcp.py"),
                         [(self.cfg, "igual")])
        self.assertEqual(len(list(self.cfg.parent.glob("*.bak-*"))), 1)

    def test_cria_quando_nao_existe(self):
        r = desktop.conectar([self.cfg])
        self.assertEqual(r[0][1], "adicionado")
        e = json.loads(self.cfg.read_text())["mcpServers"]["prospecta"]
        self.assertTrue(Path(e["command"]).is_absolute() and e["args"][0].endswith("mcp.py"))

    def test_recusa_json_quebrado(self):
        self.cfg.parent.mkdir(parents=True)
        self.cfg.write_text("{ isto não é json", encoding="utf-8")
        with self.assertRaises(desktop.ErroDesktop):
            desktop.conectar([self.cfg])
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), "{ isto não é json")

    def test_remover(self):
        desktop.conectar([self.cfg])
        self.assertEqual(desktop.desconectar([self.cfg]), [(self.cfg, "removido")])
        self.assertEqual(json.loads(self.cfg.read_text())["mcpServers"], {})
        self.assertEqual(desktop.desconectar([self.cfg]), [])

    def test_escolha_entre_varios_caminhos(self):
        a, b = self.tmp / "a" / "c.json", self.tmp / "b" / "c.json"
        b.parent.mkdir()
        self.assertEqual(desktop.escolher_config([a, b]), [b])  # só existe a pasta do segundo
        b.write_text("{}")
        a.parent.mkdir()
        a.write_text("{}")
        self.assertEqual(desktop.escolher_config([a, b]), [a, b])  # os dois arquivos existem

    def test_comando_e_servidor_de_verdade(self):
        """Faz o que o Claude Desktop faz: lê o arquivo, inicia o comando gravado de outra pasta e conversa."""
        saida = io.StringIO()
        with mock.patch.object(desktop, "caminhos_config", lambda: [self.cfg]), redirect_stdout(saida):
            self.assertEqual(cli.main(["conectar", "claude-desktop"]), 0)
        self.assertIn("Prospecta adicionado", saida.getvalue())
        e = json.loads(self.cfg.read_text())["mcpServers"]["prospecta"]
        msgs = "\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "claude-ai", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n"
        env = dict(os.environ, PASTA_DADOS=str(self.tmp / "dados"))
        r = subprocess.run([e["command"], *e["args"]], input=msgs, capture_output=True, text=True, cwd=str(self.tmp),
                           env=env, timeout=60)
        linhas = [json.loads(x) for x in r.stdout.splitlines()]
        self.assertEqual(linhas[0]["result"]["serverInfo"]["name"], "prospecta", r.stderr)
        self.assertGreaterEqual(len(linhas[1]["result"]["tools"]), 15)
        with mock.patch.object(desktop, "caminhos_config", lambda: [self.cfg]), redirect_stdout(io.StringIO()):
            cli.main(["conectar", "claude-desktop", "--remover"])
        self.assertNotIn("prospecta", json.loads(self.cfg.read_text())["mcpServers"])

    def test_caminhos_por_sistema(self):
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertIn("Library/Application Support/Claude", desktop.caminhos_config()[0].as_posix())
        with mock.patch.object(sys, "platform", "linux"), mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": "/x"}):
            self.assertTrue(desktop.caminhos_config()[0].as_posix().endswith("/x/Claude/claude_desktop_config.json"))
        with mock.patch.object(sys, "platform", "win32"), mock.patch.dict(os.environ, {"APPDATA": "/ap"}):
            self.assertTrue(desktop.caminhos_config()[0].as_posix().endswith("/ap/Claude/claude_desktop_config.json"))


if __name__ == "__main__":
    unittest.main()
