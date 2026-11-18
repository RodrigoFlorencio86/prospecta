"""Cliente do motor do google-maps-scraper-kit (API REST em localhost:8080).

O motor recusa pedidos cujo cabeçalho Host não seja localhost (proteção contra DNS rebinding).
Quando ele roda em outro container (MOTOR_URL=http://engine:8080), enviamos Host: localhost:<porta>."""
import json
import re
import time
import urllib.parse

from . import rede

ID = re.compile(r"[A-Za-z0-9-]{1,64}")
BLOQUEIO = "unusual traffic"


class ErroMotor(RuntimeError):
    pass


class Cancelado(Exception):
    pass


class Motor:
    def __init__(self, url="http://localhost:8080", chave="", intervalo=3.0):
        self.url = url.rstrip("/")
        self.chave = chave
        self.intervalo = intervalo
        partes = urllib.parse.urlsplit(self.url)
        self.cab = {"Host": f"localhost:{partes.port or 80}"}
        if chave:
            self.cab["X-API-Key"] = chave

    def _pedir(self, metodo, caminho, corpo=None, tempo=30):
        try:
            return rede.pedir(self.url + caminho, metodo, corpo, self.cab, tempo=tempo, limite=200_000_000)
        except rede.ErroRede as e:
            raise ErroMotor(f"não consegui falar com o motor de busca em {self.url} ({e}). Ele está ligado?") from e

    def saude(self):
        status, _ = self._pedir("GET", "/api/v1/jobs", tempo=10)
        return status == 200

    def criar(self, nome, palavras, lat, lon, zoom, profundidade, avaliacoes=0, idioma="pt", pais="br",
              emails=True, redes=True, tempo_max=None):
        corpo = {"name": nome[:200], "keywords": palavras, "lang": idioma, "country": pais,
                 "lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "zoom": int(zoom), "depth": int(profundidade),
                 "max_time": int(tempo_max or 120 + 45 * len(palavras) * profundidade + 20 * avaliacoes * len(palavras)),
                 "fast_mode": False, "email": bool(emails), "socials": bool(redes), "reviews_max": int(avaliacoes)}
        status, dados = self._pedir("POST", "/api/v1/jobs", corpo)
        if status != 201:
            raise ErroMotor(f"o motor recusou a busca (HTTP {status}: {dados[:200].decode('utf-8', 'replace')})")
        jid = json.loads(dados).get("id")
        if not isinstance(jid, str) or not ID.fullmatch(jid):
            raise ErroMotor("o motor não devolveu um id de busca")
        return jid

    def estado(self, jid):
        status, dados = self._pedir("GET", f"/api/v1/jobs/{jid}")
        if status != 200:
            raise ErroMotor(f"busca {jid} sumiu do motor (HTTP {status})")
        return json.loads(dados)

    def linhas(self, jid):
        status, dados = self._pedir("GET", f"/api/v1/jobs/{jid}/download?format=json", tempo=60)
        if status == 404:
            return []
        if status != 200:
            raise ErroMotor(f"não consegui baixar os resultados (HTTP {status})")
        return json.loads(dados.decode("utf-8", "replace"))

    def apagar(self, jid):
        try:
            self._pedir("DELETE", f"/api/v1/jobs/{jid}", tempo=10)
        except ErroMotor:
            pass

    def executar(self, jid, cancelar=None, progresso=None, espera_max=3600):
        """Espera a busca terminar -> (linhas, aviso). aviso é "" ou o motivo de uma parada antecipada
        (ex.: bloqueio do Google), mantendo as linhas obtidas até ali."""
        inicio = time.monotonic()
        while True:
            if cancelar is not None and cancelar.is_set():
                self.apagar(jid)
                raise Cancelado()
            job = self.estado(jid)
            st, erro = job.get("Status"), (job.get("Error") or "").strip()
            if progresso:
                p = job.get("Progress") or {}
                progresso(p.get("percent", 0), p.get("places", 0), p.get("stage", ""))
            if st == "ok":
                return self.linhas(jid), erro
            if st == "failed":
                linhas = self.linhas(jid)
                if linhas:
                    return linhas, erro or "a busca parou no meio"
                raise ErroMotor(f"a busca falhou: {erro or 'sem motivo informado'}")
            if time.monotonic() - inicio > espera_max:
                return self.linhas(jid), "tempo esgotado esperando o motor"
            time.sleep(self.intervalo)
