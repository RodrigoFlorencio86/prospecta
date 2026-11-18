"""Cliente mínimo da Bot API do Telegram (long polling), só com a biblioteca padrão."""
import json
import mimetypes
import time
import uuid
from pathlib import Path

from . import rede


class ErroTelegram(RuntimeError):
    pass


class Telegram:
    def __init__(self, token, base="https://api.telegram.org"):
        if not token:
            raise ErroTelegram("TELEGRAM_TOKEN não configurado (crie um bot com o @BotFather)")
        self.url = f"{base}/bot{token}"

    def chamar(self, metodo, tempo=30, **params):
        params = {k: v for k, v in params.items() if v is not None}
        for tentativa in range(3):
            try:
                status, dados = rede.pedir(f"{self.url}/{metodo}", "POST", json.dumps(params).encode(),
                                           {"Content-Type": "application/json"}, tempo=tempo)
            except rede.ErroRede as e:
                if tentativa == 2:
                    raise ErroTelegram(str(e)) from e
                time.sleep(2 + 3 * tentativa)
                continue
            r = json.loads(dados.decode("utf-8", "replace") or "{}")
            if r.get("ok"):
                return r.get("result")
            espera = (r.get("parameters") or {}).get("retry_after")
            if status == 429 and espera and tentativa < 2:
                time.sleep(min(int(espera), 30))
                continue
            raise ErroTelegram(f"{metodo}: {r.get('description', status)}")
        return None

    def atualizacoes(self, offset=None, espera=50):
        return self.chamar("getUpdates", tempo=espera + 10, offset=offset, timeout=espera,
                           allowed_updates=["message", "callback_query"]) or []

    def enviar(self, chat_id, texto, teclado=None, html=True, previa=False):
        return self.chamar("sendMessage", chat_id=chat_id, text=texto[:4096], parse_mode="HTML" if html else None,
                           reply_markup=teclado, link_preview_options={"is_disabled": not previa})

    def editar(self, chat_id, msg_id, texto, teclado=None):
        try:
            return self.chamar("editMessageText", chat_id=chat_id, message_id=msg_id, text=texto[:4096],
                               parse_mode="HTML", reply_markup=teclado, link_preview_options={"is_disabled": True})
        except ErroTelegram as e:
            if "not modified" in str(e):
                return None
            raise

    def responder_botao(self, callback_id, texto=None):
        try:
            self.chamar("answerCallbackQuery", callback_query_id=callback_id, text=texto)
        except ErroTelegram:
            pass

    def local(self, chat_id, lat, lon, titulo, endereco):
        return self.chamar("sendVenue", chat_id=chat_id, latitude=lat, longitude=lon, title=titulo[:100],
                           address=(endereco or " ")[:200])

    def documento(self, chat_id, caminho, legenda=""):
        caminho = Path(caminho)
        limite = "----prospecta" + uuid.uuid4().hex
        tipo = mimetypes.guess_type(caminho.name)[0] or "application/octet-stream"
        partes = []
        for k, v in (("chat_id", str(chat_id)), ("caption", legenda[:1024])):
            partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="document"; filename="{caminho.name}"\r\n'
                      f"Content-Type: {tipo}\r\n\r\n".encode() + caminho.read_bytes() + b"\r\n")
        partes.append(f"--{limite}--\r\n".encode())
        try:
            status, dados = rede.pedir(f"{self.url}/sendDocument", "POST", b"".join(partes),
                                       {"Content-Type": f"multipart/form-data; boundary={limite}"}, tempo=120)
        except rede.ErroRede as e:
            raise ErroTelegram(str(e)) from e
        r = json.loads(dados.decode("utf-8", "replace") or "{}")
        if not r.get("ok"):
            raise ErroTelegram(f"sendDocument: {r.get('description', status)}")
        return r["result"]

    def comandos(self, lista):
        self.chamar("setMyCommands", commands=[{"command": c, "description": d} for c, d in lista])
