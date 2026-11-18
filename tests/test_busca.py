import csv
import json
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prospecta import busca, exporta, geo, motor, perfis, rotas, sites
from tests.apoio import CENTRO, MotorFalso, linha


def perto(m_norte, m_leste=0.0):
    return geo.deslocar(CENTRO.lat, CENTRO.lon, m_norte, m_leste)


class BuscaTest(unittest.TestCase):
    def setUp(self):
        self.perfil = perfis.carregar()["refrigeracao"]

    def test_juntar_filtra_e_deduplica(self):
        rows = [
            linha("Perto", *perto(300)),
            linha("Perto", *perto(300), input_id="sorveteria"),            # mesmo place_id: junta os alvos
            linha("Longe", *perto(5000)),                                  # fora do raio
            linha("Fechada", *perto(100), status="Permanently closed"),
            linha("SemCoord", "", ""),
            linha("Fechada temp", *perto(200), status="Fechado temporariamente"),
        ]
        ps = busca.juntar(rows, CENTRO, 3000)
        self.assertEqual(sorted(p.nome for p in ps), ["Fechada temp", "Perto"])
        self.assertEqual(next(p for p in ps if p.nome == "Perto").alvo, "padaria, sorveteria")

    def test_prospectar_ponta_a_ponta(self):
        rows = [
            linha("A Celular Perto", *perto(200), phone="+55 19 99999-1111", review_count="400",
                  user_reviews=json.dumps([{"Description": "freezer quebrado, cerveja quente"}])),
            linha("B Fixo Longe", *perto(2500), phone="(19) 3333-2222", review_count="3"),
            linha("C Sem Fone", *perto(1500), website="https://instagram.com/padaria_c"),
        ]
        m = MotorFalso([rows, rows[:1]])
        vistos = []
        res = busca.prospectar(m, CENTRO, 3000, self.perfil, "rapido",
                               progresso=lambda f, t, n: vistos.append((f, t, n)), ler_sites=True)
        self.assertEqual(res.pontos_total, len(m.criados))
        self.assertEqual(m.criados[0]["palavras"], self.perfil.alvos)
        self.assertEqual([p.nome for p in res.prospects][0], "A Celular Perto")
        a = res.prospects[0]
        self.assertEqual((a.whatsapp, a.whatsapp_status, a.prioridade), ("19999991111", "provável", "A"))
        self.assertEqual(a.sinais, ["freezer", "quente"])
        self.assertEqual(a.bairro, "Cambuí")
        c = next(p for p in res.prospects if p.nome == "C Sem Fone")
        self.assertEqual(c.instagram, "https://instagram.com/padaria_c")
        self.assertFalse(c.site_proprio)
        self.assertTrue(vistos)

    def test_bloqueio_para_a_busca(self):
        m = MotorFalso([[linha("X", *perto(10))]] * 5, aviso="Google showed the unusual traffic page")
        res = busca.prospectar(m, CENTRO, 3000, self.perfil, "rapido", ler_sites=False)
        self.assertEqual(len(m.criados), 1)
        self.assertEqual(res.pontos_feitos, 1)
        self.assertTrue(any("limitou" in a for a in res.avisos))

    def test_falha_de_uma_area_nao_derruba(self):
        class Instavel(MotorFalso):
            def executar(self, jid, **k):
                if jid == "2":
                    raise motor.ErroMotor("caiu")
                return super().executar(jid, **k)

        m = Instavel([[linha("X", *perto(10))]])
        res = busca.prospectar(m, CENTRO, 3000, self.perfil, "rapido", ler_sites=False)
        self.assertEqual([p.nome for p in res.prospects], ["X"])
        self.assertTrue(any("área 2 falhou" in a for a in res.avisos))

    def test_tudo_falhando_vira_erro(self):
        class Quebrado(MotorFalso):
            def executar(self, jid, **k):
                raise motor.ErroMotor("sem rede")

        m = Quebrado()
        with self.assertRaises(motor.ErroMotor):
            busca.prospectar(m, CENTRO, 3000, self.perfil, "rapido", ler_sites=False)
        self.assertEqual(len(m.criados), 2)

    def test_cancelar(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(motor.Cancelado):
            busca.prospectar(MotorFalso(), CENTRO, 3000, self.perfil, "rapido", cancelar=ev)

    def test_estimativa(self):
        min_r, n_r = busca.estimar_minutos(3000, "rapido", 10)
        min_c, n_c = busca.estimar_minutos(3000, "completo", 10)
        self.assertLess(min_r, min_c)
        self.assertLessEqual(n_c, busca.MAX_PONTOS)


class ExportaTest(unittest.TestCase):
    def setUp(self):
        rows = [linha("=HYPERLINK(1)", *perto(100), phone="19 99999-1111"), linha("Bar & Cia <b>", *perto(900))]
        self.ps = busca.juntar(rows, CENTRO, 3000)
        busca.pontuar(self.ps, perfis.carregar()["limpeza"], 3000)
        self.dados = exporta.linhas(self.ps, CENTRO, perfis.carregar()["limpeza"], "Ana", "Brilho")
        self.tmp = Path(tempfile.mkdtemp())

    def test_linhas(self):
        d = next(x for x in self.dados if x["Telefone"])
        self.assertTrue(d["Abrir WhatsApp com mensagem"].startswith("https://wa.me/5519999991111?text="))
        self.assertIn("origin=-22.905600,-47.060800", d["Rota da base"])
        self.assertEqual(set(d), set(exporta.COLUNAS))

    def test_csv_protege_formulas(self):
        caminho = exporta.salvar_csv(self.tmp / "p.csv", self.dados)
        with caminho.open(encoding="utf-8-sig") as f:
            nomes = [r["Nome"] for r in csv.DictReader(f, delimiter=";")]
        self.assertIn("'=HYPERLINK(1)", nomes)

    def test_xlsx(self):
        from openpyxl import load_workbook
        rota = rotas.planejar(CENTRO, self.ps)
        caminho = exporta.salvar_xlsx(self.tmp / "p.xlsx", self.dados, {"Raio": 3}, rota)
        wb = load_workbook(caminho)
        self.assertEqual(wb.sheetnames, ["Prospects", "Rota", "Resumo"])
        ws = wb["Prospects"]
        self.assertEqual(ws.max_row, 3)
        self.assertEqual([c.value for c in ws[1]], exporta.COLUNAS)

    def test_kml_valido(self):
        caminho = exporta.salvar_kml(self.tmp / "p.kml", self.ps, CENTRO)
        raiz = ET.parse(caminho).getroot()
        marcas = raiz.findall(".//{http://www.opengis.net/kml/2.2}Placemark")
        self.assertEqual(len(marcas), 3)


class SitesTest(unittest.TestCase):
    def test_rede_social_nao_e_site(self):
        self.assertEqual(sites.analisar_site("https://wa.me/5519999998888"),
                         {"whatsapp": ["19999998888"], "site_proprio": False})
        self.assertFalse(sites.analisar_site("instagram.com/x")["site_proprio"])

    def test_recusa_rede_interna(self):
        self.assertEqual(sites.baixar("http://127.0.0.1:1/"), "")
        self.assertEqual(sites.baixar("http://10.0.0.1/"), "")
        self.assertEqual(sites.baixar("file:///etc/passwd"), "")


class MotorHTTPTest(unittest.TestCase):
    """Um servidor falso com o contrato do motor do kit, incluindo a checagem de Host."""

    def setUp(self):
        estado = self.estado = {"polls": 0, "hosts": set(), "corpo": None}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                estado["hosts"].add(self.headers["Host"])
                estado["corpo"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self._json(201, {"id": "job-1"})

            def do_GET(self):
                estado["hosts"].add(self.headers["Host"])
                if self.path == "/api/v1/jobs/job-1":
                    estado["polls"] += 1
                    st = "ok" if estado["polls"] >= 2 else "working"
                    return self._json(200, {"Status": st, "Error": "", "Progress": {"percent": 50, "places": 7}})
                if self.path.startswith("/api/v1/jobs/job-1/download"):
                    return self._json(200, [linha("Z", -22.9, -47.06)])
                self._json(200, None)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_fluxo(self):
        m = motor.Motor(self.url, intervalo=0.01)
        self.assertTrue(m.saude())
        jid = m.criar("t", ["padaria"], -22.9, -47.06, 15, 2, avaliacoes=3)
        prog = []
        rows, aviso = m.executar(jid, progresso=lambda *a: prog.append(a))
        self.assertEqual(([r["title"] for r in rows], aviso), (["Z"], ""))
        self.assertEqual(self.estado["hosts"], {f"localhost:{self.srv.server_address[1]}"})
        c = self.estado["corpo"]
        self.assertEqual((c["lang"], c["country"], c["depth"], c["reviews_max"], c["email"]), ("pt", "br", 2, 3, True))
        self.assertTrue(prog)

    def test_motor_desligado(self):
        with self.assertRaises(motor.ErroMotor):
            motor.Motor("http://127.0.0.1:9").saude()


if __name__ == "__main__":
    unittest.main()
