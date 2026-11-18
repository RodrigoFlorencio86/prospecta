"""Uso local (o que o agente de IA roda): instalação do kit, CLI de busca e relatório HTML."""
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from prospecta import __main__ as cli, busca, geo, kit, perfis, relatorio
from tests.apoio import CENTRO, linha


def zip_de(arquivos):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return buf.getvalue()


class KitTest(unittest.TestCase):
    def test_extrai_zip_do_github(self):
        destino = Path(tempfile.mkdtemp()) / "kit"
        kit.extrair_zip(zip_de({"kit-abc/scripts/engine.py": "x", "kit-abc/engine/serve.py": "y"}), destino)
        self.assertTrue(kit.instalado(destino))

    def test_recusa_zip_malicioso(self):
        destino = Path(tempfile.mkdtemp()) / "kit"
        with self.assertRaises(kit.ErroKit):
            kit.extrair_zip(zip_de({"kit-abc/../../fora.txt": "x", "kit-abc/scripts/engine.py": "x"}), destino)
        self.assertFalse((destino.parent.parent / "fora.txt").exists())

    def test_recusa_zip_errado(self):
        with self.assertRaises(kit.ErroKit):
            kit.extrair_zip(zip_de({"outro/README.md": "x"}), Path(tempfile.mkdtemp()) / "kit")

    def test_motor_remoto_nao_e_ligado(self):
        self.assertTrue(kit.local("http://localhost:8080"))
        self.assertFalse(kit.local("http://motor:8080"))


class RelatorioTest(unittest.TestCase):
    def test_html_seguro(self):
        rows = [linha('Bar </script><script>alert(1)</script>', *geo.deslocar(CENTRO.lat, CENTRO.lon, 100, 0),
                      phone="19 99999-0000", website="javascript:alert(1)")]
        ps = busca.juntar(rows, CENTRO, 1000)
        busca.pontuar(ps, perfis.carregar()["ti"], 1000)
        caminho = relatorio.gerar(Path(tempfile.mkdtemp()) / "r.html", ps, CENTRO, perfis.carregar()["ti"], 1000)
        html = caminho.read_text(encoding="utf-8")
        self.assertEqual(html.count("</script>"), 3)  # os três <script> do modelo, nenhum vindo dos dados
        dados = json.loads(html.split('type="application/json">')[1].split("</script>")[0].replace("<\\/", "</"))
        item = dados["itens"][0]
        self.assertTrue(item["wa_link"].startswith("https://wa.me/5519999990000?text="))
        self.assertEqual(item["site"], "")  # javascript: nunca vira link


class CLITest(unittest.TestCase):
    """buscar de ponta a ponta contra um motor HTTP falso, sem internet."""

    def setUp(self):
        rows = [linha(f"Lugar {i}", *geo.deslocar(CENTRO.lat, CENTRO.lon, 200 * i, 50), phone=f"19 99999-10{i:02d}")
                for i in range(6)]

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self._json({"id": "j1"}, 201)

            def do_GET(self):
                if self.path.startswith("/api/v1/jobs/j1/download"):
                    return self._json(rows)
                if self.path == "/api/v1/jobs/j1":
                    return self._json({"Status": "ok", "Error": "", "Progress": {}})
                self._json(None)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"MOTOR_URL": f"http://127.0.0.1:{self.srv.server_address[1]}",
                                                "PASTA_DADOS": str(self.tmp / "dados")})
        self.env.start()
        achar = lambda _self, texto: geo.Local(CENTRO.lat, CENTRO.lon, f"End {texto}", "Centro", "Campinas")  # noqa: E731
        self.geo = mock.patch.object(geo.Geocodificador, "buscar", achar)
        self.geo.start()

    def tearDown(self):
        self.geo.stop()
        self.env.stop()
        self.srv.shutdown()
        self.srv.server_close()

    def rodar(self, *args):
        saida = io.StringIO()
        with redirect_stdout(saida):
            codigo = cli.main(["buscar", "Rua A, 1", "--raio", "1.5", "--saida", str(self.tmp / "res"),
                               "--sem-sites", *args])
        return codigo, saida.getvalue()

    def test_busca_gera_arquivos(self):
        codigo, saida = self.rodar("--alvos", "padaria, hotel", "--servico", "Manutenção de fornos",
                                   "--sinais", "forno", "--empresa", "Ana | Forno Bom")
        self.assertEqual(codigo, 0)
        self.assertIn("6 prospects", saida)
        pasta = next((self.tmp / "res").iterdir())
        nomes = sorted(p.name for p in pasta.iterdir())
        self.assertEqual(nomes, ["prospects.json", "prospects.kml", "prospects.xlsx", "relatorio.html", "resumo.md"])
        resumo = (pasta / "resumo.md").read_text(encoding="utf-8")
        self.assertIn("Manutenção de fornos", resumo)
        self.assertIn("Forno%20Bom", resumo)
        self.assertIn("Rota sugerida", resumo)

    def test_so_novos(self):
        self.rodar("--perfil", "limpeza")
        codigo, saida = self.rodar("--perfil", "limpeza", "--so-novos")
        self.assertIn("0 prospects", saida)
        self.assertIn("6 já recebidos", saida)

    def test_perfil_invalido(self):
        with self.assertRaises(SystemExit):
            self.rodar("--perfil", "nao-existe")
        with self.assertRaises(SystemExit):
            self.rodar()

    def test_perfis_json(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            cli.main(["perfis", "--json"])
        self.assertIn("refrigeracao", json.loads(saida.getvalue()))


if __name__ == "__main__":
    unittest.main()
