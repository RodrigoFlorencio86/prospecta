"""Instala e controla o motor de busca (google-maps-scraper-kit) dentro desta pasta.

O kit fica em motor/google-maps-scraper-kit, na versão testada com este projeto. Com git
instalado ele é clonado; sem git, baixamos o .zip do GitHub. O motor roda localmente, com o
Chrome do computador (ou um Chrome baixado pelo próprio kit, ~100 MB, na primeira vez)."""
import io
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path

from . import rede
from .config import pasta_base

REPO = "https://github.com/mahanaicoach/google-maps-scraper-kit"
VERSAO = "446f231e66ba787465bb70dad2a416feec18dad3"  # commit testado; troque com cuidado
# PROSPECTA_MOTOR_DIR: onde guardar o motor. Padrão: motor/ nesta pasta, ou ~/Prospecta/motor na extensão do
# Claude Desktop (fora da pasta da extensão, que é trocada a cada atualização)
PASTA = Path(os.environ.get("PROSPECTA_MOTOR_DIR") or pasta_base() / "motor") / "google-maps-scraper-kit"
SAIDA_ERRO = "stderr"  # manda a saída do motor para o stderr (o stdout do servidor MCP é só do protocolo)


class ErroKit(RuntimeError):
    pass


def instalado(pasta=PASTA):
    return (Path(pasta) / "scripts" / "engine.py").is_file() and (Path(pasta) / "engine" / "serve.py").is_file()


def instalar(pasta=PASTA, versao=VERSAO, log=print):
    """Baixa o kit se ainda não estiver aqui. -> caminho da pasta."""
    pasta = Path(pasta)
    if instalado(pasta):
        log(f"✓ motor já instalado em {pasta}")
        return pasta
    pasta.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("git"):
        log("▶ baixando o motor de busca com git…")
        tmp = pasta.with_name(pasta.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            subprocess.run(["git", "init", "-q", str(tmp)], check=True)
            subprocess.run(["git", "-C", str(tmp), "fetch", "-q", "--depth", "1", REPO, versao], check=True)
            subprocess.run(["git", "-C", str(tmp), "checkout", "-q", "FETCH_HEAD"], check=True)
            tmp.rename(pasta)
            return pasta
        except (subprocess.CalledProcessError, OSError) as ex:
            shutil.rmtree(tmp, ignore_errors=True)
            log(f"  git falhou ({ex}); tentando pelo .zip")
    log("▶ baixando o motor de busca (.zip)…")
    url = f"https://codeload.github.com/{urllib.parse.urlsplit(REPO).path.strip('/')}/zip/{versao}"
    status, dados = rede.pedir(url, cabecalhos={"Accept": "application/zip"}, tempo=120, limite=100_000_000)
    if status != 200:
        raise ErroKit(f"não consegui baixar o motor (HTTP {status}). Baixe manualmente de {REPO} para {pasta}")
    extrair_zip(dados, pasta)
    return pasta


def extrair_zip(dados, pasta):
    """Extrai o .zip do GitHub (que tem uma pasta raiz) direto em `pasta`, recusando caminhos que
    escapem dela."""
    pasta = Path(pasta)
    tmp = pasta.with_name(pasta.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        for item in z.infolist():
            partes = Path(item.filename).parts[1:]  # tira a pasta raiz "repo-commit/"
            if not partes or item.is_dir():
                continue
            destino = tmp.joinpath(*partes).resolve()
            if not str(destino).startswith(str(tmp.resolve()) + os.sep):
                raise ErroKit(f"arquivo suspeito no .zip: {item.filename}")
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(z.read(item))
    if not instalado(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
        raise ErroKit("o .zip baixado não parece ser o google-maps-scraper-kit")
    tmp.rename(pasta)


def _porta(motor_url):
    p = urllib.parse.urlsplit(motor_url)
    return p.port or 80


def local(motor_url):
    return (urllib.parse.urlsplit(motor_url).hostname or "") in ("localhost", "127.0.0.1", "::1")


def comando(acao, motor_url="http://localhost:8080", pasta=PASTA, saida=None):
    """Roda `engine.py <acao>` do kit (start, stop, status, restart) -> código de saída."""
    if not instalado(pasta):
        raise ErroKit("o motor não está instalado. Rode: python -m prospecta instalar")
    env = dict(os.environ, SCRAPER_PORT=str(_porta(motor_url)), SCRAPER_NO_UPDATE_CHECK="1")
    if saida == SAIDA_ERRO:
        try:
            saida = sys.stderr.fileno()
        except (AttributeError, OSError, ValueError):
            saida = subprocess.DEVNULL
    return subprocess.run([sys.executable, str(Path(pasta) / "scripts" / "engine.py"), acao], env=env,
                          stdout=saida, stdin=subprocess.DEVNULL).returncode


def garantir(motor, motor_url, pasta=PASTA, log=print, espera=90, saida=None):
    """Liga o motor local se ele não estiver respondendo. Lança ErroKit se não der."""
    from .motor import ErroMotor
    try:
        if motor.saude():
            return
    except ErroMotor:
        pass
    if not local(motor_url):
        raise ErroKit(f"o motor em {motor_url} não responde (ele roda em outra máquina; ligue-o lá)")
    if not instalado(pasta):
        raise ErroKit("o motor não está instalado. Rode: python -m prospecta instalar")
    log("▶ ligando o motor de busca…")
    if comando("start", motor_url, pasta, saida) != 0:
        raise ErroKit("o motor não ligou; veja a mensagem acima")
    fim = time.monotonic() + espera
    while time.monotonic() < fim:
        try:
            if motor.saude():
                return
        except ErroMotor:
            pass
        time.sleep(2)
    raise ErroKit("o motor foi ligado mas não respondeu a tempo")
