"""Configuração lida do ambiente (ou de um arquivo .env na pasta do projeto)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def carregar_env(caminho=RAIZ / ".env"):
    """Lê KEY=valor de um .env simples sem sobrescrever o que já está no ambiente."""
    try:
        linhas = Path(caminho).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def eh_extensao():
    """Rodando como extensão do Claude Desktop? Lá a pasta do programa é trocada a cada atualização,
    então os dados vão para ~/Prospecta e os resultados para Documentos/Prospecta."""
    return os.environ.get("PROSPECTA_EXTENSAO") == "1"


def pasta_base():
    return Path.home() / "Prospecta" if eh_extensao() else RAIZ


def _documentos():
    if os.name != "nt":
        try:  # Linux com pastas localizadas (ex.: ~/Documentos)
            import subprocess
            r = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip() and Path(r.stdout.strip()) != Path.home():
                return Path(r.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return Path.home() / "Documents"


def _ids(texto):
    return {int(x) for x in (texto or "").replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()}


@dataclass
class Config:
    telegram_token: str = ""
    usuarios_permitidos: set = field(default_factory=set)
    motor_url: str = "http://localhost:8080"
    motor_chave: str = ""
    pasta_dados: Path = RAIZ / "dados"
    pasta_resultados: Path = RAIZ / "resultados"
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    contato_geocoder: str = ""
    osrm_url: str = ""
    buscas_por_dia: int = 20
    raio_maximo_km: float = 15.0

    @classmethod
    def do_ambiente(cls):
        carregar_env()

        def e(chave, padrao=None):
            # um campo opcional da extensão do Claude Desktop deixado em branco pode chegar como "${user_config.x}"
            v = os.environ.get(chave)
            return padrao if v is None or v.strip() == "" or v.startswith("${") else v

        return cls(
            telegram_token=e("TELEGRAM_TOKEN", ""),
            usuarios_permitidos=_ids(e("USUARIOS_PERMITIDOS", "")),
            motor_url=e("MOTOR_URL", "http://localhost:8080").rstrip("/"),
            motor_chave=e("MOTOR_CHAVE", ""),
            pasta_dados=Path(e("PASTA_DADOS", str(pasta_base() / "dados"))),
            pasta_resultados=Path(e("PASTA_RESULTADOS", str(_documentos() / "Prospecta" if eh_extensao()
                                                          else RAIZ / "resultados"))),
            nominatim_url=e("NOMINATIM_URL", "https://nominatim.openstreetmap.org").rstrip("/"),
            contato_geocoder=e("CONTATO_GEOCODER", ""),
            osrm_url=e("OSRM_URL", "").rstrip("/"),
            buscas_por_dia=int(e("BUSCAS_POR_DIA", "20") or 20),
            raio_maximo_km=float(e("RAIO_MAXIMO_KM", "15") or 15),
        )
