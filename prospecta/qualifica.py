"""Nota de prioridade (0 a 100) de cada prospect, independente do nicho.

  distância    até 35  quanto mais perto da base, melhor (visita e atendimento mais baratos)
  contato      até 25  WhatsApp confirmado 20, celular 18, fixo 10; +5 e-mail ou Instagram
  porte        até 20  número de avaliações no Google (proxy de movimento e de equipamentos)
  sinais       até 20  palavras do perfil nas avaliações (ex.: "freezer", "calor", "barata")
"""
import json
import re
import math


def pontos_distancia(dist_m, raio_m):
    if raio_m <= 0:
        return 0.0
    return 35.0 * max(0.0, 1.0 - dist_m / raio_m)


def pontos_contato(p):
    base = {"confirmado": 20, "provável": 18, "possível": 10}.get(p.whatsapp_status, 0)
    if not base and p.telefone:
        base = 6
    extra = 5 if (p.emails or p.instagram) else 0
    return float(min(25, base + extra))


def pontos_porte(avaliacoes):
    try:
        n = int(float(avaliacoes or 0))
    except ValueError:
        n = 0
    return 20.0 * min(1.0, math.log10(1 + n) / math.log10(501))


def sinais_em(avaliacoes_json, palavras):
    """Palavras do perfil que aparecem nos textos das avaliações -> lista (sem repetir)."""
    if not palavras or not avaliacoes_json:
        return []
    try:
        revs = json.loads(avaliacoes_json)
    except ValueError:
        return []
    texto = " ".join(str(r.get("Description", "")) for r in revs if isinstance(r, dict)).lower()
    achadas = []
    for p in palavras:
        # mostra a palavra como está na avaliação ("gelad" -> "geladeira"), sem repetir
        m = re.search(r"\w*" + re.escape(p) + r"\w*", texto)
        if m and m.group(0) not in achadas:
            achadas.append(m.group(0))
    return achadas


def nota(p, raio_m):
    total = (pontos_distancia(p.distancia_m, raio_m) + pontos_contato(p) + pontos_porte(p.avaliacoes)
             + min(20.0, 10.0 * len(p.sinais)))
    return int(round(min(100.0, total)))


def prioridade(n):
    return "A" if n >= 65 else "B" if n >= 45 else "C"
