"""Leitura leve do site de cada empresa para achar o WhatsApp (links wa.me / api.whatsapp.com).

Só segue http/https, recusa endereços de rede interna (o "site" vem de um cadastro público e pode
apontar para qualquer lugar), lê no máximo 1,5 MB e segue até 3 redirecionamentos."""
import concurrent.futures
import http.client
import ipaddress
import socket
import ssl
import urllib.parse

from . import rede, telefone

LIMITE = 1_500_000
REDES_SOCIAIS = ("instagram.com", "facebook.com", "linktr.ee", "wa.me", "whatsapp.com", "ifood.com.br")


def _ip_publico(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, OSError):
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            return False
    return bool(infos)


def baixar(url, tempo=8):
    """O HTML da página, ou "" se não for possível (bloqueio, erro, tempo)."""
    for _ in range(4):
        p = urllib.parse.urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname or not _ip_publico(p.hostname):
            return ""
        caminho = (p.path or "/") + (f"?{p.query}" if p.query else "")
        try:
            if p.scheme == "https":
                c = http.client.HTTPSConnection(p.hostname, p.port, timeout=tempo, context=ssl.create_default_context())
            else:
                c = http.client.HTTPConnection(p.hostname, p.port, timeout=tempo)
            c.request("GET", caminho, headers={"User-Agent": "Mozilla/5.0 (compatible; " + rede.AGENTE + ")",
                                               "Accept": "text/html,*/*", "Accept-Language": "pt-BR,pt;q=0.9"})
            r = c.getresponse()
            if r.status in (301, 302, 303, 307, 308) and r.getheader("Location"):
                url = urllib.parse.urljoin(url, r.getheader("Location"))
                c.close()
                continue
            if r.status != 200:
                return ""
            corpo = r.read(LIMITE)
            c.close()
            return corpo.decode(r.headers.get_content_charset() or "utf-8", "replace")
        except (OSError, http.client.HTTPException, ValueError):
            return ""
    return ""


def analisar_site(url):
    """-> {"whatsapp": [nacional], "site_proprio": bool}. Um "site" que já é wa.me, Instagram ou
    Facebook é tratado como ausência de site próprio (comum em pequenos negócios)."""
    url = (url or "").strip()
    if not url:
        return {"whatsapp": [], "site_proprio": False}
    if "://" not in url:
        url = "http://" + url
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if any(host == d or host.endswith("." + d) for d in REDES_SOCIAIS):
        return {"whatsapp": telefone.numeros_whatsapp(url), "site_proprio": False}
    return {"whatsapp": telefone.numeros_whatsapp(baixar(url)), "site_proprio": True}


def analisar_varios(urls, paralelos=8):
    """{url: resultado} para uma lista de sites, em paralelo."""
    unicos = [u for u in dict.fromkeys(u for u in urls if u)]
    if not unicos:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=paralelos) as ex:
        return dict(zip(unicos, ex.map(analisar_site, unicos)))
