import tempfile
import unittest
from pathlib import Path

from prospecta import geo, perfis
from prospecta.banco import Banco
from prospecta.bot import Bot
from prospecta.config import Config
from tests.apoio import CENTRO, GeoFalso, MotorFalso, TelegramFalso, linha

DONO, ESTRANHO, CHAT = 111, 999, 5000


def msg(texto, de=DONO):
    return {"update_id": 1, "message": {"chat": {"id": CHAT}, "from": {"id": de}, "text": texto}}


def botao(dados, de=DONO, msg_id=1):
    return {"update_id": 2, "callback_query": {"id": "cb", "from": {"id": de}, "data": dados,
                                               "message": {"chat": {"id": CHAT}, "message_id": msg_id}}}


class BotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        cfg = Config(usuarios_permitidos={DONO}, pasta_dados=self.tmp, buscas_por_dia=5)
        rows = [linha(f"Lugar {i}", *geo.deslocar(CENTRO.lat, CENTRO.lon, 150 * i, 0),
                      phone=f"+55 19 99999-{1000 + i}") for i in range(14)]
        self.motor = MotorFalso([rows])
        self.tg = TelegramFalso()
        self.db = Banco(self.tmp / "t.db")
        self.bot = Bot(cfg, self.tg, self.motor, GeoFalso(), self.db, perfis.carregar())
        self.bot._trabalhador.start()

    def rodar_busca(self, endereco="Rua A, 10, Campinas"):
        self.bot.tratar(msg(endereco))
        self.assertIn("ir", self.tg.botoes())
        self.bot.tratar(botao("ir"))
        self.bot.fila.join()

    def test_estranho_recebe_o_proprio_id(self):
        self.bot.tratar(msg("/start", de=ESTRANHO))
        self.assertIn(str(ESTRANHO), self.tg.enviadas[-1]["texto"])
        self.assertEqual(len(self.tg.enviadas), 1)
        self.bot.tratar(botao("ir", de=ESTRANHO))
        self.assertEqual(self.motor.criados, [])

    def test_configuracoes(self):
        self.bot.tratar(msg("/raio 2,5"))
        self.bot.tratar(msg("/empresa Ana Souza | Frio Total"))
        self.bot.tratar(msg("/alvos padaria, hotel"))
        self.bot.tratar(botao("modo:completo"))
        c = self.db.chat(CHAT)
        self.assertEqual((c["raio_km"], c["meu_nome"], c["minha_empresa"], c["alvos"], c["modo"]),
                         (2.5, "Ana Souza", "Frio Total", "padaria, hotel", "completo"))
        self.bot.tratar(msg("/raio 99"))
        self.assertEqual(self.db.chat(CHAT)["raio_km"], 2.5)
        self.bot.tratar(botao("perfil:ti"))
        self.assertEqual((self.db.chat(CHAT)["perfil"], self.db.chat(CHAT)["alvos"]), ("ti", ""))

    def test_busca_completa(self):
        self.bot.tratar(msg("/empresa Ana | Frio Total"))
        self.bot.tratar(msg("/alvos padaria, sorveteria"))
        self.rodar_busca()
        self.assertEqual(self.motor.criados[0]["palavras"], ["padaria", "sorveteria"])
        textos = "\n".join(self.tg.textos())
        self.assertIn("14 prospects", textos)
        self.assertIn("Prospects</b> (página 1/2)", textos)
        self.assertEqual([Path(d).suffix for d in self.tg.documentos], [".xlsx", ".kml"])
        b = self.db.busca(CHAT)
        # detalhe com WhatsApp pré-preenchido
        self.bot.tratar(botao(f"p:{b['id']}:0"))
        det = self.tg.enviadas[-1]
        self.assertIn("Lugar 0", det["texto"])
        urls = [x for x in self.tg.botoes() if x and x.startswith("https://wa.me/55199999")]
        self.assertTrue(urls and "Frio%20Total" in urls[-1])
        # mini-CRM
        self.bot.tratar(botao(f"st:{b['id']}:0:interessado"))
        self.bot.tratar(botao(f"obs:{b['id']}:0"))
        self.bot.tratar(msg("Ligar segunda às 9h"))
        reg = self.db.prospect(CHAT, b["itens"][0]["chave"])
        self.assertEqual((reg["status"], reg["obs"]), ("interessado", "Ligar segunda às 9h"))
        self.bot.tratar(msg("/funil"))
        self.assertIn("Ligar segunda", self.tg.enviadas[-1]["texto"])
        # página 2, rota e mapa
        self.bot.tratar(botao(f"pg:{b['id']}:1"))
        self.assertIn("página 2/2", self.tg.editadas[-1]["texto"])
        self.bot.tratar(botao(f"rota:{b['id']}:5"))
        self.assertIn("Rota de visitas", self.tg.enviadas[-1]["texto"])
        self.bot.tratar(botao(f"mapa:{b['id']}:3"))
        self.assertEqual(self.tg.locais[-1][2], "Lugar 3")

    def test_so_novos(self):
        self.rodar_busca()
        self.bot.tratar(msg("/novos"))
        self.motor.criados.clear()
        self.rodar_busca()
        self.assertIn("14 já recebidos antes foram ocultados", "\n".join(self.tg.textos()))
        self.assertEqual(self.db.busca(CHAT)["itens"], [])

    def test_localizacao_e_endereco_inexistente(self):
        self.bot.tratar({"update_id": 3, "message": {"chat": {"id": CHAT}, "from": {"id": DONO},
                                                     "location": {"latitude": -22.9, "longitude": -47.0}}})
        self.assertIn("Pino enviado", self.tg.enviadas[-1]["texto"])
        self.bot.tratar(msg("lugar que nada existe"))
        self.assertIn("Não achei", self.tg.enviadas[-1]["texto"])

    def test_limite_diario(self):
        self.bot.cfg.buscas_por_dia = 1
        self.rodar_busca()
        criados = len(self.motor.criados)
        self.bot.tratar(msg("Outra rua"))
        self.bot.tratar(botao("ir"))
        self.bot.fila.join()
        self.assertEqual(len(self.motor.criados), criados)
        self.assertIn("Limite", self.tg.enviadas[-1]["texto"])

    def test_base_para_rotas(self):
        self.bot.tratar(msg("/base Av. Brasil, 500"))
        self.assertTrue(self.db.chat(CHAT)["base"].endswith("End: Av. Brasil, 500"))
        self.rodar_busca()
        b = self.db.busca(CHAT)
        self.bot.tratar(botao(f"rota:{b['id']}:3"))
        self.assertIn("saindo de End: Av. Brasil", self.tg.enviadas[-1]["texto"])

    def test_update_quebrado_nao_derruba(self):
        self.bot.tratar(botao("p:abc:0"))
        self.bot.tratar({"update_id": 9})


if __name__ == "__main__":
    unittest.main()
