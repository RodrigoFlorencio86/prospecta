"""Extensão do Claude Desktop (.mcpb): conteúdo do pacote, regras do validador oficial e o servidor rodando
de dentro do pacote extraído, como o Claude Desktop faria."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from prospecta import __version__, extensao
from prospecta.ferramentas import FERRAMENTAS


class ExtensaoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.pacote = extensao.empacotar(cls.tmp / "prospecta.mcpb")
        cls.zip = zipfile.ZipFile(cls.pacote)
        cls.nomes = set(cls.zip.namelist())
        cls.man = json.loads(cls.zip.read("manifest.json"))

    @classmethod
    def tearDownClass(cls):
        cls.zip.close()

    def test_conteudo(self):
        for f in ("manifest.json", "pyproject.toml", "icon.png", "server/mcp.py", "server/prospecta/__main__.py",
                  "server/prospecta/painel.html", "server/prospecta/perfis.json", "server/prospecta/mcp_servidor.py"):
            self.assertIn(f, self.nomes)
        self.assertFalse([n for n in self.nomes if "__pycache__" in n or n.endswith(".pyc")])
        self.assertFalse([n for n in self.nomes if n.startswith(("tests/", "dados/", "resultados/", "motor/")) or ".env" == n])
        self.assertTrue(self.zip.read("icon.png").startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertLess(self.pacote.stat().st_size, 1_000_000)

    def test_manifesto(self):
        m = self.man
        self.assertEqual((m["manifest_version"], m["name"], m["version"]), ("0.4", "prospecta", __version__))
        self.assertEqual(m["server"]["type"], "uv")
        self.assertIn(m["server"]["entry_point"], self.nomes)
        self.assertEqual(m["author"]["name"], "Rodrigo Florencio")
        self.assertEqual([t["name"] for t in m["tools"]], [f["nome"] for f in FERRAMENTAS])
        # regra do validador oficial (mcpb validate): só estas variáveis no mcp_config
        cfg = m["server"]["mcp_config"]
        textos = [cfg["command"], *cfg["args"], *cfg["env"].values()]
        for t in textos:
            for var in re.findall(r"\$\{[^}]+\}", t):
                self.assertRegex(var, extensao.VARIAVEL_VALIDA)
                if var.startswith("${user_config."):
                    self.assertIn(var[len("${user_config."):-1], m["user_config"])
        self.assertIn('requires-python = ">=3.10"', self.zip.read("pyproject.toml").decode())

    def test_reproduzivel(self):
        outro = extensao.empacotar(self.tmp / "de-novo.mcpb")
        self.assertEqual(outro.read_bytes(), self.pacote.read_bytes())

    def test_servidor_de_dentro_do_pacote(self):
        """Extrai o .mcpb e inicia o servidor como a extensão (PROSPECTA_EXTENSAO=1, HOME isolado)."""
        pasta = self.tmp / "instalada"
        self.zip.extractall(pasta)
        casa = self.tmp / "casa"
        casa.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PASTA_", "PROSPECTA_"))}
        env.update(HOME=str(casa), USERPROFILE=str(casa), PROSPECTA_EXTENSAO="1",
                   PASTA_RESULTADOS="${user_config.pasta_resultados}",  # campo vazio chegando sem substituição
                   CONTATO_GEOCODER="${user_config.email_contato}")
        msgs = "\n".join(json.dumps(x) for x in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "ver_configuracao", "arguments": {}}},
        ]) + "\n"
        r = subprocess.run([sys.executable, str(pasta / "server" / "mcp.py")], input=msgs, capture_output=True,
                           text=True, cwd=str(self.tmp), env=env, timeout=60)
        linhas = [json.loads(x) for x in r.stdout.splitlines()]
        self.assertEqual(linhas[0]["result"]["serverInfo"]["version"], __version__, r.stderr)
        self.assertIn("abrir_painel", {t["name"] for t in linhas[1]["result"]["tools"]})
        self.assertFalse(linhas[2]["result"]["isError"])
        self.assertTrue((casa / "Prospecta" / "dados" / "prospecta-local.db").is_file())  # dados fora da extensão
        self.assertFalse((pasta / "server" / "dados").exists())


if __name__ == "__main__":
    unittest.main()
