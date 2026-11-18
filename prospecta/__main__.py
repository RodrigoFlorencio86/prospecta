"""Linha de comando.

    python -m prospecta bot                          # liga o bot do Telegram
    python -m prospecta buscar "Rua X, 100, Campinas" --raio 3 --perfil climatizacao
    python -m prospecta buscar "13010-001" --alvos "padaria, hotel" --saida resultados
    python -m prospecta perfis                       # lista os serviços prontos
    python -m prospecta verificar                    # testa motor, Telegram e geocodificação
"""
import argparse
import logging
import sys
import threading
from pathlib import Path

from . import busca, exporta, geo, perfis as perfis_mod, rotas
from .config import Config
from .motor import ErroMotor, Motor
from .rede import ErroRede


def _geocoder(cfg):
    return geo.Geocodificador(cfg.nominatim_url, cfg.contato_geocoder)


def cmd_bot(cfg, _a):
    from .banco import Banco
    from .bot import Bot
    from .telegram import Telegram
    if not cfg.usuarios_permitidos:
        logging.warning("USUARIOS_PERMITIDOS está vazio: o bot vai recusar todo mundo e responder com o ID de "
                        "quem escrever. Coloque esse ID no .env e reinicie.")
    bot = Bot(cfg, Telegram(cfg.telegram_token), Motor(cfg.motor_url, cfg.motor_chave), _geocoder(cfg),
              Banco(Path(cfg.pasta_dados) / "prospecta.db"), perfis_mod.carregar())
    bot.rodar()


def cmd_perfis(_cfg, _a):
    for k, p in perfis_mod.carregar().items():
        print(f"{k:20} {p.nome}\n{'':20} {', '.join(p.alvos)}\n")


def cmd_verificar(cfg, _a):
    ok = True
    try:
        print("motor de busca:", "ok" if Motor(cfg.motor_url, cfg.motor_chave).saude() else "respondeu com erro")
    except ErroMotor as ex:
        ok = False
        print("motor de busca: FALHOU —", ex)
    try:
        local = _geocoder(cfg).buscar("Praça da Sé, São Paulo")
        print("geocodificação:", f"ok ({local.lat:.4f}, {local.lon:.4f})" if local else "sem resultado")
    except ErroRede as ex:
        ok = False
        print("geocodificação: FALHOU —", ex)
    if cfg.telegram_token:
        from .telegram import ErroTelegram, Telegram
        try:
            eu = Telegram(cfg.telegram_token).chamar("getMe")
            print(f"telegram: ok (@{eu.get('username')})")
        except ErroTelegram as ex:
            ok = False
            print("telegram: FALHOU —", ex)
    else:
        print("telegram: TELEGRAM_TOKEN não configurado")
    print("usuários permitidos:", ", ".join(map(str, sorted(cfg.usuarios_permitidos))) or "nenhum")
    return 0 if ok else 1


def cmd_buscar(cfg, a):
    todos = perfis_mod.carregar()
    if a.alvos:
        base_perfil = todos.get(a.perfil)
        perfil = perfis_mod.personalizado(perfis_mod.separar_alvos(a.alvos), base_perfil.mensagem if base_perfil else None)
    elif a.perfil in todos:
        perfil = todos[a.perfil]
    else:
        sys.exit(f"perfil desconhecido: {a.perfil}. Veja: python -m prospecta perfis")
    local = _geocoder(cfg).buscar(a.endereco)
    if not local:
        sys.exit("endereço não encontrado")
    minutos, areas = busca.estimar_minutos(a.raio * 1000, a.modo, len(perfil.alvos))
    print(f"📍 {local.descricao}\n{perfil.nome}: {', '.join(perfil.alvos)}\nraio {a.raio} km, {areas} área(s), ~{minutos} min")

    def progresso(feitos, total, lugares):
        print(f"\r  {int(100 * feitos / max(total, 1))}% · {lugares} lugares", end="", flush=True)

    try:
        res = busca.prospectar(Motor(cfg.motor_url, cfg.motor_chave), local, a.raio * 1000, perfil, a.modo, progresso,
                               threading.Event(), ler_sites=not a.sem_sites)
    except ErroMotor as ex:
        sys.exit(f"\n✗ {ex}")
    print()
    for aviso in res.avisos:
        print("⚠", aviso)
    meu_nome, _, empresa = (a.empresa or "").partition("|")
    pasta = Path(a.saida)
    pasta.mkdir(parents=True, exist_ok=True)
    rota = rotas.planejar(local, res.prospects[:10], osrm_url=cfg.osrm_url) if res.prospects else None
    dados = exporta.linhas(res.prospects, local, perfil, meu_nome.strip(), empresa.strip())
    plan = exporta.salvar_xlsx(pasta / "prospects.xlsx", dados,
                               {"Endereço": local.descricao, "Raio (km)": a.raio, "Serviço": perfil.nome}, rota)
    mapa = exporta.salvar_kml(pasta / "prospects.kml", res.prospects, local)
    print(f"✅ {len(res.prospects)} prospects → {plan} e {mapa}")
    for p in res.prospects[:10]:
        print(f"  {p.prioridade} {p.nota:3} {p.distancia_km:4.1f} km  {p.nome}  {p.telefone}")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="prospecta", description="Prospecção B2B pelo Google Maps")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bot", help="liga o bot do Telegram")
    sub.add_parser("perfis", help="lista os serviços prontos")
    sub.add_parser("verificar", help="testa as conexões")
    b = sub.add_parser("buscar", help="uma busca pela linha de comando")
    b.add_argument("endereco", help='endereço, CEP ou "lat, lon"')
    b.add_argument("--raio", type=float, default=3.0, help="km (padrão 3)")
    b.add_argument("--perfil", default="refrigeracao")
    b.add_argument("--alvos", help='tipos de negócio separados por vírgula, ex.: "padaria, hotel"')
    b.add_argument("--modo", choices=sorted(busca.MODOS), default="rapido")
    b.add_argument("--empresa", help='"Seu Nome | Sua Empresa" para a mensagem sugerida')
    b.add_argument("--saida", default="resultados")
    b.add_argument("--sem-sites", action="store_true", help="não abrir os sites para procurar WhatsApp")
    a = ap.parse_args(argv)
    cfg = Config.do_ambiente()
    return {"bot": cmd_bot, "perfis": cmd_perfis, "verificar": cmd_verificar, "buscar": cmd_buscar}[a.cmd](cfg, a) or 0


if __name__ == "__main__":
    sys.exit(main())
