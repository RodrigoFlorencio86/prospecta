"""HTTP simples com a biblioteca padrão (sem dependências)."""
import json
import urllib.error
import urllib.parse
import urllib.request

AGENTE = "prospecta-bot/1.0 (+https://github.com/RodrigoFlorencio86/AI-Stuff)"


class ErroRede(RuntimeError):
    pass


def pedir(url, metodo="GET", corpo=None, cabecalhos=None, tempo=20, limite=5_000_000):
    """-> (status, bytes). Lança ErroRede para falhas de conexão; HTTP 4xx/5xx voltam como status."""
    dados = json.dumps(corpo).encode() if isinstance(corpo, (dict, list)) else corpo
    h = {"User-Agent": AGENTE, "Accept": "application/json, */*"}
    if isinstance(corpo, (dict, list)):
        h["Content-Type"] = "application/json"
    h.update(cabecalhos or {})
    req = urllib.request.Request(url, data=dados, headers=h, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=tempo) as r:
            return r.status, r.read(limite)
    except urllib.error.HTTPError as e:
        return e.code, e.read(limite)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ErroRede(f"{urllib.parse.urlsplit(url).netloc}: {getattr(e, 'reason', e)}") from e


def json_get(url, params=None, cabecalhos=None, tempo=20):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    status, dados = pedir(url, cabecalhos=cabecalhos, tempo=tempo)
    if status >= 400:
        raise ErroRede(f"HTTP {status} em {urllib.parse.urlsplit(url).netloc}")
    try:
        return json.loads(dados.decode("utf-8", "replace"))
    except ValueError as e:
        raise ErroRede(f"resposta inválida de {urllib.parse.urlsplit(url).netloc}") from e
