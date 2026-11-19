"""Registra o servidor MCP do Prospecta no app Claude para desktop (claude_desktop_config.json).

O app lê os servidores locais do bloco "mcpServers" desse arquivo e os inicia sozinho. Como ele não
herda o PATH do terminal (principalmente no Mac), gravamos o caminho completo do Python e do mcp.py.
O resto do arquivo (outros servidores, preferências) é preservado, e uma cópia do original é guardada
antes de qualquer mudança."""
import json
import os
import sys
import time
from pathlib import Path

NOME = "prospecta"


class ErroDesktop(RuntimeError):
    pass


def caminhos_config():
    """Onde o Claude Desktop guarda o claude_desktop_config.json neste sistema (pode haver mais de um)."""
    casa = Path.home()
    if sys.platform == "darwin":
        return [casa / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"]
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA") or casa / "AppData" / "Roaming")
        saida = [appdata / "Claude" / "claude_desktop_config.json"]
        # versão da Microsoft Store (MSIX): a pasta "Roaming" fica virtualizada dentro do pacote
        pacotes = Path(os.environ.get("LOCALAPPDATA") or casa / "AppData" / "Local") / "Packages"
        if pacotes.is_dir():
            for p in sorted(pacotes.glob("Claude_*")):
                saida.append(p / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
        return saida
    return [Path(os.environ.get("XDG_CONFIG_HOME") or casa / ".config") / "Claude" / "claude_desktop_config.json"]


def escolher_config(caminhos=None):
    """Os arquivos a alterar: os que já existem; se nenhum existe, o primeiro cuja pasta existe
    (o app já foi aberto); senão, o caminho padrão."""
    caminhos = caminhos or caminhos_config()
    existentes = [c for c in caminhos if c.is_file()]
    if existentes:
        return existentes
    com_pasta = [c for c in caminhos if c.parent.is_dir()]
    return com_pasta[:1] or caminhos[:1]


def entrada(python=None, lancador=None):
    from .config import RAIZ
    return {"command": str(Path(python or sys.executable).resolve()),
            "args": [str(Path(lancador or RAIZ / "mcp.py").resolve())]}


def _ler(caminho):
    if not caminho.exists():
        return {}
    texto = caminho.read_text(encoding="utf-8-sig").strip()
    if not texto:
        return {}
    try:
        dados = json.loads(texto)
    except ValueError as ex:
        raise ErroDesktop(f"{caminho} não é um JSON válido ({ex}). Corrija ou apague o arquivo e rode de novo; "
                          "não vou sobrescrever a sua configuração.") from ex
    if not isinstance(dados, dict) or not isinstance(dados.get("mcpServers", {}), dict):
        raise ErroDesktop(f"{caminho} tem um formato inesperado; não vou alterá-lo.")
    return dados


def _gravar(caminho, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if caminho.exists():
        copia = caminho.with_name(f"{caminho.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        copia.write_bytes(caminho.read_bytes())
    tmp = caminho.with_name(caminho.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, caminho)


def conectar(caminhos=None, python=None, lancador=None):
    """Adiciona (ou atualiza) o servidor 'prospecta' -> [(caminho, 'adicionado'|'atualizado'|'igual')]."""
    nova = entrada(python, lancador)
    resultado = []
    for caminho in escolher_config(caminhos):
        dados = _ler(caminho)
        servidores = dados.setdefault("mcpServers", {})
        antes = servidores.get(NOME)
        if antes == nova:
            resultado.append((caminho, "igual"))
            continue
        servidores[NOME] = nova
        _gravar(caminho, dados)
        resultado.append((caminho, "atualizado" if antes else "adicionado"))
    return resultado


def desconectar(caminhos=None):
    resultado = []
    for caminho in [c for c in (caminhos or caminhos_config()) if c.is_file()]:
        dados = _ler(caminho)
        if NOME in dados.get("mcpServers", {}):
            del dados["mcpServers"][NOME]
            _gravar(caminho, dados)
            resultado.append((caminho, "removido"))
    return resultado
