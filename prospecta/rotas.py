"""Rotas de visita: ordem otimizada a partir da base e links prontos para Google Maps e Waze.

Sem chave de API: a ordem usa distância em linha reta (vizinho mais próximo + 2-opt) e o tempo é
estimado. Com OSRM_URL configurado (um servidor OSRM próprio), usa distâncias reais de carro."""
import urllib.parse

from . import geo, rede

MAX_PARADAS_LINK = 9      # o Google Maps aceita até 9 paradas intermediárias por link
FATOR_RUA = 1.35          # linha reta -> trajeto aproximado pelas ruas
VELOCIDADE_KMH = 22       # média urbana com trânsito
MINUTOS_POR_VISITA = 20


def _matriz_reta(pontos):
    return [[geo.distancia_m(a[0], a[1], b[0], b[1]) * FATOR_RUA for b in pontos] for a in pontos]


def _matriz_osrm(osrm_url, pontos):
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in pontos)
    d = rede.json_get(f"{osrm_url}/table/v1/driving/{coords}", {"annotations": "distance,duration"}, tempo=30)
    if d.get("code") != "Ok":
        raise rede.ErroRede("OSRM recusou a rota")
    return d["distances"], d["durations"]


def ordem_otima(matriz, volta=True):
    """Índices 1..n na melhor ordem encontrada, saindo do 0 (a base)."""
    n = len(matriz)
    if n <= 2:
        return list(range(1, n))
    restantes, atual, ordem = set(range(1, n)), 0, []
    while restantes:
        prox = min(restantes, key=lambda j: matriz[atual][j])
        ordem.append(prox)
        restantes.remove(prox)
        atual = prox

    def custo(o):
        caminho = [0] + o + ([0] if volta else [])
        return sum(matriz[a][b] for a, b in zip(caminho, caminho[1:]))

    melhor, melhorou = custo(ordem), True
    while melhorou:
        melhorou = False
        for i in range(len(ordem) - 1):
            for k in range(i + 1, len(ordem)):
                nova = ordem[:i] + ordem[i:k + 1][::-1] + ordem[k + 1:]
                c = custo(nova)
                if c + 1e-6 < melhor:
                    ordem, melhor, melhorou = nova, c, True
    return ordem


def link_google(origem, paradas, destino=None):
    """Link do Google Maps com origem, paradas intermediárias e destino (lat, lon)."""
    if destino is None:
        meio, destino = paradas[:-1], paradas[-1]
    else:
        meio = paradas
    q = {"api": "1", "origin": f"{origem[0]:.6f},{origem[1]:.6f}",
         "destination": f"{destino[0]:.6f},{destino[1]:.6f}", "travelmode": "driving"}
    if meio:
        q["waypoints"] = "|".join(f"{la:.6f},{lo:.6f}" for la, lo in meio)
    return "https://www.google.com/maps/dir/?" + urllib.parse.urlencode(q, safe=",|")


def link_ate(origem, lat, lon):
    return link_google(origem, [(lat, lon)])


def link_waze(lat, lon):
    return f"https://waze.com/ul?ll={lat:.6f},{lon:.6f}&navigate=yes"


def planejar(base, prospects, volta=True, osrm_url=""):
    """-> {"ordem": [Prospect], "km": float, "minutos": int, "links": [str], "estimado": bool}.
    Os links quebram a rota em trechos de até 9 paradas (limite do Google Maps)."""
    pontos = [(base.lat, base.lon)] + [(p.lat, p.lon) for p in prospects]
    estimado, duracoes = True, None
    matriz = None
    if osrm_url and len(pontos) > 1:
        try:
            matriz, duracoes = _matriz_osrm(osrm_url, pontos)
            estimado = False
        except (rede.ErroRede, KeyError, TypeError):
            matriz = None
    if matriz is None:
        matriz = _matriz_reta(pontos)
    ordem = ordem_otima(matriz, volta)
    caminho = [0] + ordem + ([0] if volta else [])
    metros = sum(matriz[a][b] for a, b in zip(caminho, caminho[1:]))
    if duracoes and not estimado:
        minutos_carro = sum(duracoes[a][b] for a, b in zip(caminho, caminho[1:])) / 60
    else:
        minutos_carro = metros / 1000 / VELOCIDADE_KMH * 60
    paradas = [pontos[i] for i in ordem]
    links, atual = [], pontos[0]
    for i in range(0, len(paradas), MAX_PARADAS_LINK + 1):
        trecho = paradas[i:i + MAX_PARADAS_LINK + 1]
        ultimo = i + MAX_PARADAS_LINK + 1 >= len(paradas)
        if ultimo and volta:
            if len(trecho) > MAX_PARADAS_LINK:  # não cabe a volta neste link: fecha o trecho e abre outro
                links.append(link_google(atual, trecho))
                links.append(link_google(trecho[-1], [pontos[0]]))
            else:
                links.append(link_google(atual, trecho, destino=pontos[0]))
        else:
            links.append(link_google(atual, trecho))
        atual = trecho[-1]
    return {"ordem": [prospects[i - 1] for i in ordem], "km": round(metros / 1000, 1),
            "minutos": int(round(minutos_carro + MINUTOS_POR_VISITA * len(prospects))),
            "minutos_carro": int(round(minutos_carro)), "links": links, "estimado": estimado}
