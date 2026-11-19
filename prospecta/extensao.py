"""Gera a extensão do Claude Desktop (arquivo .mcpb, formato MCP Bundle).

    python -m prospecta empacotar-extensao            # cria dist/prospecta-<versão>.mcpb

O pacote usa o tipo "uv" (manifest 0.4): o próprio Claude Desktop baixa o Python e as dependências,
então quem instala não precisa ter Python. Os dados ficam fora da pasta da extensão (que é trocada a
cada atualização): buscas e histórico em ~/Prospecta, resultados na pasta escolhida pelo usuário
(padrão Documentos/Prospecta). O motor de busca é baixado sozinho na primeira busca."""
import json
import zipfile
from pathlib import Path

from . import __version__
from .config import RAIZ
from .ferramentas import FERRAMENTAS

AUTOR = {"name": "Rodrigo Florencio", "url": "https://www.linkedin.com/in/rodrigoflorencio/"}
REPOSITORIO = "https://github.com/RodrigoFlorencio86/AI-Stuff"
ICONE = RAIZ / "extensao" / "icon.png"
IGNORAR = {"__pycache__", ".pytest_cache"}
VARIAVEL_VALIDA = r"^\$\{(__dirname|pathSeparator|/|user_config\..+)\}$"  # a mesma regra do mcpb oficial

DESCRICAO_LONGA = """Encontre empresas que podem contratar o seu serviço perto de você.

Diga ao Claude o que você faz e de onde quer partir (endereço ou CEP). O Prospecta procura no Google \
Maps, num raio de alguns quilômetros, os negócios certos para o seu serviço: padarias para quem conserta \
freezer, clínicas para quem limpa ar-condicionado, restaurantes para quem faz dedetização e assim por diante.

Você recebe:
- lista priorizada (nota de 0 a 100) com telefone, WhatsApp, e-mail, Instagram e distância;
- mensagem de WhatsApp pronta para cada empresa (quem envia é você);
- rota de visitas otimizada no Google Maps;
- relatório, planilha e mapa, e um painel no navegador para acompanhar os contatos.

Tudo roda no seu computador. Na primeira busca, o Prospecta baixa o motor de busca (código aberto, \
google-maps-scraper-kit) e, se preciso, um Chrome sem janela (~100 MB). Use com moderação: muitas buscas \
seguidas fazem o Google bloquear temporariamente. Dados públicos de empresas, para contato comercial (LGPD)."""


def manifest():
    return {
        "manifest_version": "0.4",
        "name": "prospecta",
        "display_name": "Prospecta: clientes perto de você",
        "version": __version__,
        "description": ("Encontra empresas que podem contratar o seu serviço num raio em volta de um endereço, "
                        "com WhatsApp, rota de visitas e planilha."),
        "long_description": DESCRICAO_LONGA,
        "author": AUTOR,
        "repository": {"type": "git", "url": REPOSITORIO},
        "homepage": REPOSITORIO,
        "icon": "icon.png",
        "server": {
            "type": "uv",
            "entry_point": "server/mcp.py",
            "mcp_config": {
                "command": "uv",
                "args": ["run", "--directory", "${__dirname}", "server/mcp.py"],
                # Só ${__dirname}, ${/} e ${user_config.*} são aceitos aqui pelo validador oficial; as pastas
                # em ~/Prospecta e Documentos/Prospecta são calculadas pelo próprio Prospecta (PROSPECTA_EXTENSAO)
                "env": {
                    "PROSPECTA_EXTENSAO": "1",
                    "PASTA_RESULTADOS": "${user_config.pasta_resultados}",
                    "CONTATO_GEOCODER": "${user_config.email_contato}",
                    "PROSPECTA_AUTO_INSTALAR": "1",
                    "PYTHONUTF8": "1",
                },
            },
        },
        "tools": [{"name": f["nome"], "description": f["descricao"]} for f in FERRAMENTAS],
        "keywords": ["prospecção", "clientes", "leads", "B2B", "google maps", "whatsapp", "autônomo", "brasil"],
        "privacy_policies": ["https://osmfoundation.org/wiki/Privacy_Policy", "https://policies.google.com/privacy"],
        "compatibility": {"platforms": ["darwin", "win32", "linux"], "runtimes": {"python": ">=3.10"}},
        "user_config": {
            "pasta_resultados": {
                "type": "directory", "title": "Pasta dos resultados",
                "description": "Onde salvar relatórios, planilhas e mapas das buscas.",
                "default": "${DOCUMENTS}/Prospecta", "required": False},
            "email_contato": {
                "type": "string", "title": "Seu e-mail (opcional)",
                "description": ("O serviço público de mapas OpenStreetMap, usado para localizar endereços, pede um "
                                "e-mail de contato de quem usa. Ele vai só nesses pedidos."),
                "required": False},
        },
    }


PYPROJECT = """[project]
name = "prospecta"
version = "{versao}"
description = "Prospecção B2B por raio a partir do Google Maps (extensão do Claude Desktop)"
requires-python = ">=3.10"
dependencies = ["openpyxl>=3.1.5,<4"]
"""


def arquivos():
    """(caminho no pacote, bytes) de tudo que vai na extensão."""
    yield "manifest.json", (json.dumps(manifest(), ensure_ascii=False, indent=2) + "\n").encode()
    yield "pyproject.toml", PYPROJECT.format(versao=__version__).encode()
    yield ".mcpbignore", b".venv/\n__pycache__/\n"
    yield "icon.png", ICONE.read_bytes()
    yield "server/mcp.py", (RAIZ / "mcp.py").read_bytes()
    pacote = RAIZ / "prospecta"
    for arq in sorted(pacote.rglob("*")):
        if arq.is_file() and not (IGNORAR & set(arq.parts)) and arq.suffix != ".pyc":
            yield f"server/prospecta/{arq.relative_to(pacote).as_posix()}", arq.read_bytes()


def empacotar(destino=None):
    destino = Path(destino or RAIZ / "dist" / f"prospecta-{__version__}.mcpb")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for nome, dados in arquivos():
            info = zipfile.ZipInfo(nome, date_time=(2026, 1, 1, 0, 0, 0))  # pacote reproduzível
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, dados)
    tmp.replace(destino)
    return destino


def gravar_pasta(destino):
    """Os mesmos arquivos numa pasta (para `mcpb validate` / `mcpb pack` oficiais)."""
    destino = Path(destino)
    for nome, dados in arquivos():
        alvo = destino / nome
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(dados)
    return destino
