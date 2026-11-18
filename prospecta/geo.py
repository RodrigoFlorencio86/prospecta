"""Geografia: distância, geocodificação de endereço/CEP e cobertura de um círculo com buscas."""
import math
import re
import threading
import time
from dataclasses import dataclass

from . import rede

R_TERRA = 6_371_000.0


def distancia_m(lat1, lon1, lat2, lon2):
    """Distância em linha reta (haversine), em metros."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_TERRA * math.asin(min(1.0, math.sqrt(a)))


def deslocar(lat, lon, norte_m, leste_m):
    """O ponto a norte_m metros ao norte e leste_m metros a leste (aproximação local)."""
    dlat = norte_m / R_TERRA
    dlon = leste_m / (R_TERRA * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def zoom_para(largura_m, lat):
    """O zoom do Maps cuja janela de ~1000 px mostra cerca de largura_m metros."""
    m_por_px = largura_m / 1000
    z = math.log2(156543.03 * math.cos(math.radians(lat)) / max(m_por_px, 0.1))
    return int(min(17, max(12, round(z))))


def pontos_cobertura(lat, lon, raio_m, espacamento_m):
    """Centros de busca que cobrem o círculo: uma malha hexagonal com o espaçamento dado, só os
    pontos dentro do raio (o centro sempre entra). Cada ponto leva o zoom adequado ao espaçamento.
    -> [{"lat", "lon", "zoom"}], o centro primeiro e os demais do mais perto ao mais longe."""
    zoom = zoom_para(espacamento_m * 1.3, lat)
    if raio_m <= espacamento_m * 0.6:
        return [{"lat": round(lat, 6), "lon": round(lon, 6), "zoom": zoom_para(max(raio_m * 2.2, 800), lat)}]
    passo_n = espacamento_m * math.sqrt(3) / 2
    linhas = int(raio_m // passo_n) + 1
    pontos = []
    for i in range(-linhas, linhas + 1):
        desloc = espacamento_m / 2 if i % 2 else 0.0
        colunas = int(raio_m // espacamento_m) + 2
        for j in range(-colunas, colunas + 1):
            n, l = i * passo_n, j * espacamento_m + desloc
            d = math.hypot(n, l)
            if d <= raio_m + 1:
                plat, plon = deslocar(lat, lon, n, l)
                pontos.append((d, {"lat": round(plat, 6), "lon": round(plon, 6), "zoom": zoom}))
    pontos.sort(key=lambda p: p[0])
    return [p for _, p in pontos]


# ── Geocodificação ──

@dataclass
class Local:
    lat: float
    lon: float
    descricao: str
    bairro: str = ""
    cidade: str = ""


CEP = re.compile(r"^\s*(\d{5})-?(\d{3})\s*$")
COORDS = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


class Geocodificador:
    """Endereço, CEP ou "lat, lon" -> Local. Usa ViaCEP para CEP e Nominatim (OpenStreetMap) para
    endereços, respeitando o limite de 1 pedido por segundo do Nominatim público."""

    def __init__(self, nominatim_url="https://nominatim.openstreetmap.org", contato=""):
        self.url = nominatim_url.rstrip("/")
        self.contato = contato
        self._trava = threading.Lock()
        self._ultimo = 0.0

    def _nominatim(self, caminho, params):
        with self._trava:
            espera = 1.1 - (time.monotonic() - self._ultimo)
            if espera > 0:
                time.sleep(espera)
            if self.contato:
                params = dict(params, email=self.contato)
            try:
                return rede.json_get(f"{self.url}/{caminho}", dict(params, format="jsonv2", addressdetails=1),
                                     cabecalhos={"Accept-Language": "pt-BR"})
            finally:
                self._ultimo = time.monotonic()

    def buscar(self, texto):
        texto = " ".join((texto or "").split())[:200]
        if not texto:
            return None
        m = COORDS.match(texto)
        if m:
            lat, lon = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return self.reverso(lat, lon) or Local(lat, lon, f"{lat:.5f}, {lon:.5f}")
        m = CEP.match(texto)
        if m:
            return self._por_cep(m.group(1) + m.group(2))
        res = self._nominatim("search", {"q": texto, "countrycodes": "br", "limit": 1})
        return _local(res[0]) if res else None

    def _por_cep(self, cep):
        try:
            d = rede.json_get(f"https://viacep.com.br/ws/{cep}/json/")
        except rede.ErroRede:
            d = {}
        if not d or d.get("erro"):
            res = self._nominatim("search", {"postalcode": f"{cep[:5]}-{cep[5:]}", "countrycodes": "br", "limit": 1})
            return _local(res[0]) if res else None
        partes = [d.get("logradouro"), d.get("bairro"), d.get("localidade"), d.get("uf")]
        consulta = ", ".join(p for p in partes if p)
        res = self._nominatim("search", {"q": consulta, "countrycodes": "br", "limit": 1})
        if not res and d.get("logradouro"):  # rua desconhecida no OSM: cai para bairro + cidade
            res = self._nominatim("search", {"q": ", ".join(p for p in partes[1:] if p), "countrycodes": "br", "limit": 1})
        if not res:
            return None
        local = _local(res[0])
        local.bairro = d.get("bairro") or local.bairro
        local.cidade = d.get("localidade") or local.cidade
        local.descricao = f"{consulta} (CEP {cep[:5]}-{cep[5:]})"
        return local

    def reverso(self, lat, lon):
        try:
            res = self._nominatim("reverse", {"lat": lat, "lon": lon, "zoom": 17})
        except rede.ErroRede:
            return None
        if not isinstance(res, dict) or "lat" not in res:
            return None
        local = _local(res)
        local.lat, local.lon = lat, lon  # mantém o ponto exato que o usuário mandou
        return local


def _local(r):
    a = r.get("address") or {}
    bairro = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or a.get("city_district") or ""
    cidade = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
    return Local(float(r["lat"]), float(r["lon"]), r.get("display_name", ""), bairro, cidade)
