"""Orquestra uma prospecção: cobre o raio com buscas no motor, junta, filtra pela distância real,
enriquece (WhatsApp, site) e ordena pela nota de prioridade."""
import json
import time
from dataclasses import asdict, dataclass, field

from . import geo, perfis as perfis_mod, qualifica, sites, telefone
from .motor import BLOQUEIO, Cancelado, ErroMotor  # noqa: F401  (Cancelado é reexportado para quem chama)

MODOS = {
    # espaçamento entre centros de busca = max(minimo, raio * fator); profundidade = lotes de ~20 por termo
    "rapido": {"nome": "rápido", "fator": 1.0, "minimo": 1500, "profundidade": 1, "avaliacoes": 0},
    "completo": {"nome": "completo", "fator": 0.55, "minimo": 1200, "profundidade": 3, "avaliacoes": 3},
}
MAX_PONTOS = 19
SEGUNDOS_POR_TERMO = 10  # por lote de ~20 lugares, medido de forma conservadora


@dataclass
class Prospect:
    chave: str
    nome: str
    categoria: str = ""
    alvo: str = ""
    endereco: str = ""
    bairro: str = ""
    cidade: str = ""
    lat: float = 0.0
    lon: float = 0.0
    distancia_m: float = 0.0
    telefone: str = ""
    telefone_tipo: str = ""
    whatsapp: str = ""
    whatsapp_status: str = ""
    emails: str = ""
    site: str = ""
    site_proprio: bool = False
    instagram: str = ""
    facebook: str = ""
    linkedin: str = ""
    nota_google: str = ""
    avaliacoes: str = ""
    horario: str = ""
    situacao: str = ""
    link_maps: str = ""
    place_id: str = ""
    sinais: list = field(default_factory=list)
    nota: int = 0
    prioridade: str = "C"

    @property
    def distancia_km(self):
        return round(self.distancia_m / 1000, 1)

    def como_dict(self):
        return asdict(self)

    @classmethod
    def de_dict(cls, d):
        campos = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**campos)


@dataclass
class Resultado:
    prospects: list
    avisos: list
    pontos_feitos: int
    pontos_total: int
    segundos: float
    brutos: int = 0


def plano(raio_m, modo, lat=0.0, lon=0.0):
    m = MODOS[modo]
    esp = max(m["minimo"], raio_m * m["fator"])
    pontos = geo.pontos_cobertura(lat, lon, raio_m, esp)
    return pontos[:MAX_PONTOS], m


def estimar_minutos(raio_m, modo, n_alvos):
    pontos, m = plano(raio_m, modo)
    seg = len(pontos) * n_alvos * (m["profundidade"] * SEGUNDOS_POR_TERMO + m["avaliacoes"] * 4) + 60
    return max(1, round(seg / 60)), len(pontos)


def _chave(r):
    for c in ("place_id", "cid", "data_id"):
        if r.get(c):
            return f"{c}:{r[c]}"
    return "t:" + "|".join((r.get(c) or "").strip().lower() for c in ("title", "address"))


def _horario(texto):
    try:
        semana = json.loads(texto) if texto else {}
    except ValueError:
        return ""
    if not isinstance(semana, dict):
        return ""
    return "; ".join(f"{dia[:3]}: {', '.join(h) if isinstance(h, list) else h}" for dia, h in semana.items())


def _bairro(r):
    try:
        partes = json.loads(r.get("complete_address") or "{}")
    except ValueError:
        partes = {}
    return (partes.get("borough") or "").strip(), (partes.get("city") or "").strip()


def converter(r, centro):
    """Uma linha do motor -> Prospect (sem nota ainda)."""
    try:
        lat, lon = float(r.get("latitude") or "nan"), float(r.get("longitude") or "nan")
    except ValueError:
        lat = lon = float("nan")
    tel = telefone.normalizar(r.get("phone"))
    bairro, cidade = _bairro(r)
    p = Prospect(
        chave=_chave(r), nome=(r.get("title") or "").strip(), categoria=(r.get("category") or "").strip(),
        alvo=(r.get("input_id") or "").strip(), endereco=(r.get("address") or "").strip(), bairro=bairro, cidade=cidade,
        lat=lat, lon=lon, telefone=tel.formatado if tel else (r.get("phone") or "").strip(),
        telefone_tipo=tel.tipo if tel else "", emails=(r.get("emails") or "").strip(),
        site=(r.get("website") or "").strip(), instagram=(r.get("instagram") or "").strip(),
        facebook=(r.get("facebook") or "").strip(), linkedin=(r.get("linkedin") or "").strip(),
        nota_google=(r.get("review_rating") or "").strip(), avaliacoes=(r.get("review_count") or "").strip(),
        horario=_horario(r.get("open_hours")), situacao=(r.get("status") or "").strip(),
        link_maps=(r.get("link") or "").strip(), place_id=(r.get("place_id") or "").strip())
    if lat == lat and lon == lon:  # não é NaN
        p.distancia_m = geo.distancia_m(centro.lat, centro.lon, lat, lon)
    if tel and tel.whatsapp:
        p.whatsapp, p.whatsapp_status = tel.nacional, tel.whatsapp
    p._avaliacoes_json = r.get("user_reviews") or ""
    return p


def fechado_de_vez(p):
    s = p.situacao.lower()
    return "permanent" in s


def juntar(linhas, centro, raio_m):
    """Remove repetidos, quem está fora do raio, sem coordenadas ou fechado definitivamente."""
    vistos = {}
    for r in linhas:
        p = converter(r, centro)
        if not p.nome or p.lat != p.lat or p.distancia_m > raio_m or fechado_de_vez(p):
            continue
        if p.chave in vistos:
            antigo = vistos[p.chave]
            if p.alvo and p.alvo not in antigo.alvo.split(", "):
                antigo.alvo = ", ".join(filter(None, [antigo.alvo, p.alvo]))
            continue
        vistos[p.chave] = p
    return list(vistos.values())


def enriquecer(prospects, ler_sites=True):
    analises = sites.analisar_varios([p.site for p in prospects]) if ler_sites else {}
    for p in prospects:
        a = analises.get(p.site)
        if a is None:
            p.site_proprio = bool(p.site) and not any(d in p.site.lower() for d in sites.REDES_SOCIAIS)
        else:
            p.site_proprio = a["site_proprio"]
            if a["whatsapp"]:
                p.whatsapp, p.whatsapp_status = a["whatsapp"][0], "confirmado"
        if not p.instagram and "instagram.com" in p.site.lower():
            p.instagram = p.site


def pontuar(prospects, perfil, raio_m):
    for p in prospects:
        p.sinais = qualifica.sinais_em(getattr(p, "_avaliacoes_json", ""), perfil.sinais)
        p.nota = qualifica.nota(p, raio_m)
        p.prioridade = qualifica.prioridade(p.nota)
    prospects.sort(key=lambda p: (-p.nota, p.distancia_m))


def mensagem_para(p, perfil, meu_nome="", minha_empresa=""):
    return perfis_mod.montar_mensagem(perfil.mensagem, prospect=p.nome, meu_nome=meu_nome,
                                      minha_empresa=minha_empresa, bairro=p.bairro)


def prospectar(motor, centro, raio_m, perfil, modo="rapido", progresso=None, cancelar=None, ler_sites=True,
               eventos=None):
    """Executa a prospecção inteira -> Resultado. progresso(feitos, total, lugares) é chamado a cada
    centro de busca concluído e durante a espera. eventos(tipo, dados), opcional, recebe o passo a passo
    para quem quer mostrar o andamento: "plano", "area", "andamento", "area_fim" e "etapa"."""
    def avisar(tipo, **dados):
        if eventos:
            eventos(tipo, dados)

    inicio = time.monotonic()
    pontos, m = plano(raio_m, modo, centro.lat, centro.lon)
    espacamento = max(m["minimo"], raio_m * m["fator"])
    avisar("plano", areas=[{"lat": p["lat"], "lon": p["lon"]} for p in pontos],
           raio_area_m=round(min(espacamento / 3 ** 0.5 * 1.05, max(raio_m, 300))), alvos=list(perfil.alvos))
    linhas, avisos, feitos, falhas = [], [], 0, 0
    for i, pt in enumerate(pontos, 1):
        if cancelar is not None and cancelar.is_set():
            raise Cancelado()
        avisar("area", i=i, total=len(pontos))

        def _prog(pct, lugares, etapa, i=i):
            if progresso:
                progresso(i - 1 + pct / 100, len(pontos), len(linhas) + lugares)
            avisar("andamento", i=i, pct=pct, lugares=lugares, etapa=etapa)

        falhou = False
        try:
            jid = motor.criar(f"prospecta {perfil.nome} {i}/{len(pontos)}", perfil.alvos, pt["lat"], pt["lon"],
                              pt["zoom"], m["profundidade"], m["avaliacoes"])
            novas, aviso = motor.executar(jid, cancelar=cancelar, progresso=_prog)
        except ErroMotor as ex:
            falhas += 1
            if falhas == i and (i >= 2 or len(pontos) == 1):  # nada funcionou: não adianta insistir
                avisar("area_fim", i=i, estado="falhou", linhas=[], aviso=str(ex))
                raise
            novas, aviso, falhou = [], f"área {i} falhou: {ex}", True
        linhas.extend(novas)
        feitos = i
        avisar("area_fim", i=i, estado="falhou" if falhou else ("parcial" if aviso else "ok"), linhas=novas, aviso=aviso)
        if aviso:
            avisos.append(aviso)
            if BLOQUEIO in aviso.lower():
                avisos.append("O Google limitou as buscas deste IP; parei para não piorar. "
                              "Tente de novo mais tarde ou com raio menor.")
                break
        if progresso:
            progresso(i, len(pontos), len(linhas))
    avisar("etapa", nome="juntar", lugares=len(linhas))
    prospects = juntar(linhas, centro, raio_m)
    avisar("etapa", nome="sites", empresas=len(prospects), sites=len({p.site for p in prospects if p.site}) if ler_sites else 0)
    enriquecer(prospects, ler_sites)
    avisar("etapa", nome="notas", empresas=len(prospects))
    pontuar(prospects, perfil, raio_m)
    return Resultado(prospects, avisos, feitos, len(pontos), time.monotonic() - inicio, len(linhas))
