import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prospecta.telegram import ErroTelegram, Telegram


class TelegramHTTPTest(unittest.TestCase):
    def setUp(self):
        pedidos = self.pedidos = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                corpo = self.rfile.read(int(self.headers["Content-Length"]))
                metodo = self.path.rsplit("/", 1)[1]
                pedidos.append((self.path, self.headers["Content-Type"], corpo))
                if metodo == "falhar":
                    resp, code = {"ok": False, "description": "Bad Request: chat not found"}, 400
                else:
                    resp, code = {"ok": True, "result": {"message_id": 7}}, 200
                b = json.dumps(resp).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tg = Telegram("123:abc", base=f"http://127.0.0.1:{self.srv.server_address[1]}")

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_enviar(self):
        r = self.tg.enviar(42, "<b>oi</b>", {"inline_keyboard": [[{"text": "x", "callback_data": "y"}]]})
        self.assertEqual(r, {"message_id": 7})
        caminho, tipo, corpo = self.pedidos[-1]
        self.assertEqual(caminho, "/bot123:abc/sendMessage")
        d = json.loads(corpo)
        self.assertEqual((d["chat_id"], d["parse_mode"], d["reply_markup"]["inline_keyboard"][0][0]["text"]),
                         (42, "HTML", "x"))

    def test_documento(self):
        arq = Path(tempfile.mkdtemp()) / "lista.xlsx"
        arq.write_bytes(b"PK\x03\x04conteudo")
        self.tg.documento(42, arq, "legenda ç")
        _, tipo, corpo = self.pedidos[-1]
        self.assertTrue(tipo.startswith("multipart/form-data; boundary="))
        self.assertIn(b'filename="lista.xlsx"', corpo)
        self.assertIn(b"PK\x03\x04conteudo", corpo)
        self.assertIn("legenda ç".encode(), corpo)

    def test_erro(self):
        with self.assertRaises(ErroTelegram) as ctx:
            self.tg.chamar("falhar")
        self.assertIn("chat not found", str(ctx.exception))

    def test_sem_token(self):
        with self.assertRaises(ErroTelegram):
            Telegram("")


if __name__ == "__main__":
    unittest.main()
