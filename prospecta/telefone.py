"""Telefones brasileiros: normalização, tipo (celular, fixo, 0800) e link de WhatsApp."""
import re
import urllib.parse
from dataclasses import dataclass

DDDS = {11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46,
        47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85,
        86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99}


@dataclass
class Telefone:
    nacional: str       # só dígitos, DDD + número: "19999998888"
    tipo: str           # "celular", "fixo", "0800", "capitais" (4004-xxxx) ou "desconhecido"

    @property
    def formatado(self):
        n = self.nacional
        if self.tipo == "celular":
            return f"({n[:2]}) {n[2:7]}-{n[7:]}"
        if self.tipo == "fixo":
            return f"({n[:2]}) {n[2:6]}-{n[6:]}"
        if self.tipo == "0800":
            return f"{n[:4]} {n[4:7]} {n[7:]}"
        if self.tipo == "capitais":
            return f"{n[:4]}-{n[4:]}"
        return n

    @property
    def e164(self):
        return f"+55{self.nacional}" if self.tipo in ("celular", "fixo") else ""

    @property
    def whatsapp(self):
        """"provável" para celular, "possível" para fixo (WhatsApp Business aceita fixo), senão ""."""
        return {"celular": "provável", "fixo": "possível"}.get(self.tipo, "")


def normalizar(texto):
    """Qualquer forma comum ("+55 19 99999-8888", "(019) 3333-4444", "0800 123 4567") -> Telefone ou None."""
    d = re.sub(r"\D", "", texto or "")
    if not d:
        return None
    if d.startswith(("0800", "0300", "0500", "0900")) and len(d) == 11:
        return Telefone(d, "0800")
    if re.fullmatch(r"[34]00[0-9]\d{4}", d):
        return Telefone(d, "capitais")
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    elif d.startswith("0") and len(d) in (11, 12, 13, 14):
        d = d.lstrip("0")
        if len(d) in (12, 13):  # 0 + operadora + DDD + número: "0 21 19 3333-4444"
            d = d[2:]
    if len(d) not in (10, 11) or int(d[:2]) not in DDDS:
        return Telefone(d, "desconhecido") if d else None
    num = d[2:]
    if len(d) == 11 and num[0] == "9":
        return Telefone(d, "celular")
    if len(d) == 10 and num[0] in "2345":
        return Telefone(d, "fixo")
    if len(d) == 10 and num[0] in "6789":  # celular antigo sem o 9 na frente
        return Telefone(d[:2] + "9" + num, "celular")
    return Telefone(d, "desconhecido")


def link_whatsapp(nacional, texto=""):
    """wa.me com o número no padrão internacional e a mensagem pré-preenchida."""
    url = f"https://wa.me/55{nacional}"
    return url + ("?text=" + urllib.parse.quote(texto) if texto else "")


WA = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send/?\?(?:[^\"'\s<>]*?&)?phone=|whatsapp://send/?\?phone=|"
                r"web\.whatsapp\.com/send/?\?phone=)\+?(\d{10,13})", re.I)


def numeros_whatsapp(html):
    """Números de WhatsApp em links wa.me / api.whatsapp.com de um texto ou HTML -> [nacional]."""
    saida = []
    for m in WA.finditer(html or ""):
        t = normalizar(m.group(1))
        if t and t.tipo in ("celular", "fixo") and t.nacional not in saida:
            saida.append(t.nacional)
    return saida
