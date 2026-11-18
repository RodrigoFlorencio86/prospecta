"""Dublês: motor de busca, geocodificador e Telegram falsos."""
import json
import threading

from prospecta import geo

CENTRO = geo.Local(-22.9056, -47.0608, "Centro, Campinas - SP", "Centro", "Campinas")


def linha(nome, lat, lon, **extra):
    r = {"title": nome, "latitude": str(lat), "longitude": str(lon), "place_id": "pid-" + nome,
         "category": "Padaria", "address": f"Rua {nome}, 1", "phone": "", "website": "", "emails": "",
         "review_count": "10", "review_rating": "4.5", "status": "", "input_id": "padaria",
         "link": f"https://www.google.com/maps/place/{nome}",
         "complete_address": json.dumps({"borough": "Cambuí", "city": "Campinas"})}
    r.update(extra)
    return r


class MotorFalso:
    def __init__(self, linhas_por_ponto=None, aviso=""):
        self.linhas_por_ponto = linhas_por_ponto or [[]]
        self.criados = []
        self.aviso = aviso

    def criar(self, nome, palavras, lat, lon, zoom, profundidade, avaliacoes=0, **k):
        self.criados.append({"palavras": palavras, "lat": lat, "lon": lon, "zoom": zoom, "prof": profundidade})
        return str(len(self.criados))

    def executar(self, jid, cancelar=None, progresso=None, espera_max=0):
        if progresso:
            progresso(50, 3, "search")
        i = int(jid) - 1
        return list(self.linhas_por_ponto[i] if i < len(self.linhas_por_ponto) else []), self.aviso


class GeoFalso:
    def buscar(self, texto):
        return None if "nada" in texto else geo.Local(CENTRO.lat, CENTRO.lon, f"End: {texto}", "Centro", "Campinas")

    def reverso(self, lat, lon):
        return geo.Local(lat, lon, "Pino enviado")


class TelegramFalso:
    def __init__(self):
        self.enviadas, self.editadas, self.documentos, self.locais = [], [], [], []
        self.trava = threading.Lock()
        self._id = 100

    def enviar(self, chat_id, texto, teclado=None, html=True, previa=False):
        with self.trava:
            self._id += 1
            self.enviadas.append({"chat": chat_id, "texto": texto, "teclado": teclado, "id": self._id})
            return {"message_id": self._id}

    def editar(self, chat_id, msg_id, texto, teclado=None):
        with self.trava:
            self.editadas.append({"chat": chat_id, "id": msg_id, "texto": texto, "teclado": teclado})

    def responder_botao(self, *_a):
        pass

    def local(self, chat_id, lat, lon, titulo, endereco):
        self.locais.append((lat, lon, titulo))

    def documento(self, chat_id, caminho, legenda=""):
        self.documentos.append(str(caminho))

    def comandos(self, lista):
        pass

    def textos(self):
        return [m["texto"] for m in self.enviadas] + [m["texto"] for m in self.editadas]

    def botoes(self):
        """Todos os callback_data enviados ou editados."""
        saida = []
        for m in self.enviadas + self.editadas:
            for linha in (m["teclado"] or {}).get("inline_keyboard", []):
                saida += [b.get("callback_data") or b.get("url") for b in linha]
        return saida
