import math
import unittest

from prospecta import geo, perfis, qualifica, rotas, telefone


class TelefoneTest(unittest.TestCase):
    def test_formatos(self):
        casos = {
            "+55 19 99999-8888": ("19999998888", "celular", "(19) 99999-8888"),
            "(19) 3333-4444": ("1933334444", "fixo", "(19) 3333-4444"),
            "019 3333-4444": ("1933334444", "fixo", "(19) 3333-4444"),
            "0 21 19 99999 8888": ("19999998888", "celular", "(19) 99999-8888"),
            "0800 123 4567": ("08001234567", "0800", "0800 123 4567"),
            "4004-1234": ("40041234", "capitais", "4004-1234"),
            "(11) 8765-4321": ("11987654321", "celular", "(11) 98765-4321"),
        }
        for entrada, (nac, tipo, fmt) in casos.items():
            t = telefone.normalizar(entrada)
            self.assertEqual((t.nacional, t.tipo, t.formatado), (nac, tipo, fmt), entrada)

    def test_invalidos(self):
        self.assertIsNone(telefone.normalizar(""))
        self.assertEqual(telefone.normalizar("(00) 1234-5678").tipo, "desconhecido")

    def test_whatsapp(self):
        self.assertEqual(telefone.normalizar("19 99999-8888").whatsapp, "provável")
        self.assertEqual(telefone.normalizar("19 3333-4444").whatsapp, "possível")
        self.assertEqual(telefone.link_whatsapp("19999998888", "Olá, tudo bem?"),
                         "https://wa.me/5519999998888?text=Ol%C3%A1%2C%20tudo%20bem%3F")
        html = ('<a href="https://wa.me/5519988887777">zap</a> <a href="https://api.whatsapp.com/send?'
                'text=oi&phone=551933334444">x</a> https://wa.me/5519988887777')
        self.assertEqual(telefone.numeros_whatsapp(html), ["19988887777", "1933334444"])


class GeoTest(unittest.TestCase):
    def test_distancia(self):
        # 1 grau de latitude ~ 111,2 km
        self.assertAlmostEqual(geo.distancia_m(0, 0, 1, 0) / 1000, 111.19, places=1)
        lat, lon = geo.deslocar(-23.0, -47.0, 1000, 1000)
        self.assertAlmostEqual(geo.distancia_m(-23.0, -47.0, lat, lon), math.hypot(1000, 1000), delta=2)

    def test_cobertura(self):
        c = (-22.9, -47.06)
        um = geo.pontos_cobertura(*c, 800, 1500)
        self.assertEqual(len(um), 1)
        pts = geo.pontos_cobertura(*c, 3000, 1500)
        self.assertGreater(len(pts), 7)
        self.assertEqual((pts[0]["lat"], pts[0]["lon"]), (round(c[0], 6), round(c[1], 6)))
        for p in pts:
            self.assertLessEqual(geo.distancia_m(*c, p["lat"], p["lon"]), 3002)
            self.assertTrue(12 <= p["zoom"] <= 17)
        # todo ponto do círculo fica a menos de um espaçamento de algum centro
        for ang in range(0, 360, 15):
            for frac in (0.3, 0.7, 1.0):
                lat, lon = geo.deslocar(*c, 3000 * frac * math.cos(math.radians(ang)),
                                        3000 * frac * math.sin(math.radians(ang)))
                perto = min(geo.distancia_m(lat, lon, p["lat"], p["lon"]) for p in pts)
                self.assertLess(perto, 1500)

    def test_zoom(self):
        self.assertGreater(geo.zoom_para(1000, -23), geo.zoom_para(8000, -23))

    def test_coords_e_cep(self):
        self.assertTrue(geo.COORDS.match("-22.9, -47.06"))
        self.assertTrue(geo.CEP.match("13010-001"))
        self.assertFalse(geo.CEP.match("Rua 13010"))


class PerfisTest(unittest.TestCase):
    def test_carrega_todos(self):
        todos = perfis.carregar()
        self.assertGreaterEqual(len(todos), 10)
        for p in todos.values():
            self.assertTrue(p.alvos and p.nome)
            msg = perfis.montar_mensagem(p.mensagem, prospect="Padaria X", meu_nome="Ana", minha_empresa="Frio Total",
                                         bairro="Cambuí")
            self.assertIn("Padaria X", msg)
            self.assertNotIn("{", msg)

    def test_mensagem_sem_dados(self):
        msg = perfis.montar_mensagem("Oi {prospect}, sou {meu_nome} {inexistente} de {bairro}", prospect="Bar")
        self.assertEqual(msg, "Oi Bar, sou [seu nome] de sua região")

    def test_separar(self):
        self.assertEqual(perfis.separar_alvos("padaria, Padaria; mercado\n hotel  fazenda ,"),
                         ["padaria", "mercado", "hotel fazenda"])


class RotasTest(unittest.TestCase):
    def test_ordem_em_linha(self):
        # base em 0 e pontos embaralhados numa reta: a ordem ótima é crescente
        pos = [0, 5, 1, 4, 2, 3]
        m = [[abs(a - b) for b in pos] for a in pos]
        ordem = rotas.ordem_otima(m, volta=False)
        self.assertEqual([pos[i] for i in ordem], [1, 2, 3, 4, 5])

    def test_links_ate_9_paradas(self):
        class P:
            def __init__(self, i):
                self.lat, self.lon = -22.9 + i * 0.001, -47.06

        base = type("B", (), {"lat": -22.9, "lon": -47.06})()
        r = rotas.planejar(base, [P(i) for i in range(1, 15)])
        self.assertEqual(len(r["ordem"]), 14)
        for link in r["links"]:
            wps = link.split("waypoints=")[1].split("&")[0].split("|") if "waypoints=" in link else []
            self.assertLessEqual(len(wps), rotas.MAX_PARADAS_LINK)
        self.assertIn("destination=-22.900000,-47.060000", r["links"][-1])  # volta para a base
        self.assertGreater(r["km"], 0)

    def test_link_simples(self):
        self.assertEqual(rotas.link_ate((-1, -2), -3, -4),
                         "https://www.google.com/maps/dir/?api=1&origin=-1.000000,-2.000000"
                         "&destination=-3.000000,-4.000000&travelmode=driving")


class QualificaTest(unittest.TestCase):
    def test_sinais(self):
        revs = '[{"Description": "O FREEZER estava quente e o sorvete derretido"}]'
        self.assertEqual(qualifica.sinais_em(revs, ["freezer", "derretid", "barata"]), ["freezer", "derretid"])
        self.assertEqual(qualifica.sinais_em("lixo", ["freezer"]), [])

    def test_prioridade(self):
        self.assertEqual([qualifica.prioridade(n) for n in (80, 50, 10)], ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()
