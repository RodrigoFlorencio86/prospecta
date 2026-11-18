"""Linha de comando (é o que o seu agente de IA roda por você).

    python -m prospecta instalar                     # baixa o motor de busca e testa tudo
    python -m prospecta perfis                       # serviços prontos (--json para agentes)
    python -m prospecta buscar "Rua X, 100, Campinas" --raio 3 --perfil climatizacao
    python -m prospecta buscar "13010-001" --alvos "padaria, hotel" --empresa "Ana | Frio Total"
    python -m prospecta motor ligar|desligar|status
    python -m prospecta verificar                    # testa motor, mapas e Telegram
    python -m prospecta bot                          # opcional: bot do Telegram
"""
import argparse
import json
import logging
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path

from . import busca, exporta, geo, kit, perfis as perfis_mod, relatorio, rotas
from .config import RAIZ, Config
from .motor import ErroMotor, Motor
from .rede import ErroRede

for _s in (sys.stdout, sys.stderr):  # emojis num console Windows cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _geocoder(cfg):
    return geo.Geocodificador(cfg.nominatim_url, cfg.contato_geocoder)


def _motor(cfg):
    return Motor(cfg.motor_url, cfg.motor_chave)


def _slug(texto, n=40):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:n] or "busca"


# ── comandos ──

def cmd_instalar(cfg, a):
    print(f"Python {sys.version.split()[0]} ✓")
    if sys.version_info < (3, 9):
        sys.exit("✗ Precisa de Python 3.9 ou mais novo: https://www.python.org/downloads/")
    try:
        import openpyxl  # noqa: F401
        print("openpyxl ✓ (planilha em .xlsx)")
    except ImportError:
        print("openpyxl ausente: a planilha sai em .csv. Para .xlsx: python -m pip install openpyxl")
    try:
        kit.instalar()
        kit.garantir(_motor(cfg), cfg.motor_url)
    except (kit.ErroKit, ErroRede) as ex:
        sys.exit(f"✗ {ex}")
    print(f"✓ motor de busca ligado em {cfg.motor_url}")
    env = RAIZ / ".env"
    if not env.exists():
        env.write_text((RAIZ / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        print(f"✓ criei {env} (edite CONTATO_GEOCODER com seu e-mail; o Telegram é opcional)")
    print("\nPronto. Exemplo:\n  python -m prospecta buscar \"Rua X, 100, Sua Cidade\" --raio 3 --perfil limpeza")
    return 0


def cmd_motor(cfg, a):
    acao = {"ligar": "start", "desligar": "stop", "status": "status", "reiniciar": "restart"}[a.acao]
    try:
        return kit.comando(acao, cfg.motor_url)
    except kit.ErroKit as ex:
        sys.exit(f"✗ {ex}")


def cmd_perfis(_cfg, a):
    todos = perfis_mod.carregar()
    if a.json:
        print(json.dumps({k: {"nome": p.nome, "descricao": p.descricao, "alvos": p.alvos, "sinais": p.sinais}
                          for k, p in todos.items()}, ensure_ascii=False, indent=1))
        return 0
    for k, p in todos.items():
        print(f"{k:20} {p.nome} — {p.descricao}\n{'':20} {', '.join(p.alvos)}\n")
    return 0


def cmd_verificar(cfg, _a):
    ok = True
    try:
        print("motor de busca:", "ok" if _motor(cfg).saude() else "respondeu com erro")
    except ErroMotor as ex:
        ok = False
        print("motor de busca: desligado —", ex, "\n  ligue com: python -m prospecta motor ligar")
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
        print("telegram: não configurado (opcional)")
    return 0 if ok else 1


def _perfil_da_linha(a):
    todos = perfis_mod.carregar()
    base = todos.get(a.perfil)
    if a.perfil and not base and not a.alvos:
        sys.exit(f"✗ perfil desconhecido: {a.perfil}. Veja: python -m prospecta perfis")
    if a.alvos:
        perfil = perfis_mod.personalizado(perfis_mod.separar_alvos(a.alvos), base.mensagem if base else None)
        perfil.sinais = list(base.sinais) if base else []
        if a.servico:
            perfil.nome = a.servico
    elif base:
        perfil = base
    else:
        sys.exit("✗ informe --perfil (veja: python -m prospecta perfis) ou --alvos \"tipo 1, tipo 2\"")
    if a.sinais:
        perfil.sinais = [s.lower() for s in perfis_mod.separar_alvos(a.sinais)]
    if a.mensagem:
        perfil.mensagem = a.mensagem
    if not perfil.alvos:
        sys.exit("✗ informe --perfil ou --alvos")
    return perfil


def cmd_buscar(cfg, a):
    perfil = _perfil_da_linha(a)
    if not 0.3 <= a.raio <= cfg.raio_maximo_km:
        sys.exit(f"✗ o raio vai de 0,3 a {cfg.raio_maximo_km:g} km (RAIO_MAXIMO_KM no .env)")
    motor = _motor(cfg)
    if not a.nao_ligar:
        try:
            kit.garantir(motor, cfg.motor_url)
        except kit.ErroKit as ex:
            sys.exit(f"✗ {ex}")
    try:
        local = _geocoder(cfg).buscar(a.endereco)
    except ErroRede as ex:
        sys.exit(f"✗ o serviço de mapas não respondeu ({ex}). Tente de novo, ou passe as coordenadas: \"-22.90, -47.06\"")
    if not local:
        sys.exit("✗ endereço não encontrado. Tente com rua, número e cidade, um CEP, ou \"latitude, longitude\".")
    base = local
    if a.base:
        base = _geocoder(cfg).buscar(a.base) or local
    minutos, areas = busca.estimar_minutos(a.raio * 1000, a.modo, len(perfil.alvos))
    print(f"📍 {local.descricao}\n🔎 {perfil.nome}: {', '.join(perfil.alvos)}\n"
          f"   raio {a.raio:g} km · modo {busca.MODOS[a.modo]['nome']} · {areas} área(s) · ~{minutos} min (estimativa)")

    def progresso(feitos, total, lugares):
        print(f"\r   {int(100 * feitos / max(total, 1)):3d}% · área {min(int(feitos) + 1, total)}/{total} · "
              f"{lugares} lugares lidos", end="", flush=True)

    try:
        res = busca.prospectar(motor, local, a.raio * 1000, perfil, a.modo, progresso, threading.Event(),
                               ler_sites=not a.sem_sites)
    except ErroMotor as ex:
        sys.exit(f"\n✗ {ex}")
    print()
    prospects, ocultos = res.prospects, 0
    from .banco import Banco
    hist = Banco(Path(cfg.pasta_dados) / "historico.db")
    if a.so_novos:
        vistos = hist.ja_vistos(0, [p.chave for p in prospects])
        ocultos = sum(p.chave in vistos for p in prospects)
        prospects = [p for p in prospects if p.chave not in vistos]
    hist.salvar_busca(0, {"lat": local.lat, "lon": local.lon, "descricao": local.descricao}, a.raio, perfil.nome,
                      prospects, res.avisos)
    hist.fechar()

    pasta = Path(a.saida) / f"{time.strftime('%Y-%m-%d_%H%M')}_{_slug(perfil.nome, 25)}_{_slug(local.descricao, 30)}"
    pasta.mkdir(parents=True, exist_ok=True)
    meu_nome, _, empresa = (a.empresa or "").partition("|")
    meu_nome, empresa = meu_nome.strip(), empresa.strip()
    rota = rotas.planejar(base, prospects[:a.rota], osrm_url=cfg.osrm_url) if prospects and a.rota else None
    dados = exporta.linhas(prospects, base, perfil, meu_nome, empresa)
    resumo = {"Endereço": local.descricao, "Raio (km)": a.raio, "Serviço": perfil.nome,
              "Procurado": ", ".join(perfil.alvos), "Data": time.strftime("%d/%m/%Y %H:%M"),
              "Base das rotas": base.descricao, "Origem dos dados": "Google Maps (dados públicos) e sites das empresas",
              "LGPD": "Use só para contato comercial B2B, identifique-se e atenda pedidos de exclusão."}
    arquivos = {
        "relatorio": relatorio.gerar(pasta / "relatorio.html", prospects, base, perfil, a.raio * 1000, meu_nome,
                                     empresa, rota, f"{perfil.nome} — {local.bairro or local.cidade or 'busca'}"),
        "planilha": exporta.salvar_xlsx(pasta / "prospects.xlsx", dados, resumo, rota),
        "mapa": exporta.salvar_kml(pasta / "prospects.kml", prospects, base, f"Prospects {perfil.nome}"),
    }
    (pasta / "prospects.json").write_text(json.dumps([p.como_dict() for p in prospects], ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    arquivos["resumo"] = _resumo_md(pasta / "resumo.md", local, base, perfil, a, res, prospects, ocultos, rota, dados)

    print(f"\n✅ {len(prospects)} prospects ({res.brutos} resultados lidos em {res.pontos_feitos}/{res.pontos_total} "
          f"áreas, {max(1, round(res.segundos / 60))} min)")
    if ocultos:
        print(f"   {ocultos} já recebidos em buscas anteriores foram ocultados (--so-novos)")
    for aviso in res.avisos:
        print("⚠️ ", aviso)
    print(f"\n📂 {pasta.resolve()}")
    for nome, caminho in arquivos.items():
        print(f"   {nome:10} {Path(caminho).name}")
    print(f"\nAbra o relatório no navegador: {Path(arquivos['relatorio']).resolve().as_uri()}")
    return 0


def _resumo_md(caminho, local, base, perfil, a, res, prospects, ocultos, rota, dados):
    """Resumo curto em Markdown, feito para o agente mostrar ao usuário."""
    cont = {k: sum(p.prioridade == k for p in prospects) for k in "ABC"}
    ls = [f"# Prospects: {perfil.nome}", "",
          f"- **Local:** {local.descricao}", f"- **Raio:** {a.raio:g} km · modo {busca.MODOS[a.modo]['nome']}",
          f"- **Procurado:** {', '.join(perfil.alvos)}",
          f"- **Encontrados:** {len(prospects)} (A: {cont['A']}, B: {cont['B']}, C: {cont['C']})"
          + (f", {ocultos} já recebidos antes ocultados" if ocultos else ""),
          f"- **Com WhatsApp:** {sum(bool(p.whatsapp) for p in prospects)} · **com e-mail:** "
          f"{sum(bool(p.emails) for p in prospects)} · **sem site próprio:** {sum(not p.site_proprio for p in prospects)}"]
    for av in res.avisos:
        ls.append(f"- ⚠️ {av}")
    ls += ["", f"## Top {min(a.top, len(prospects))}", "",
           "| # | Prior. | Nota | Nome | Categoria | Dist. | Bairro | Telefone | WhatsApp |",
           "|---|---|---|---|---|---|---|---|---|"]
    lim = lambda s: str(s).replace("|", "/").replace("\n", " ")  # noqa: E731
    for i, (p, d) in enumerate(zip(prospects[:a.top], dados[:a.top]), 1):
        wa = f"[abrir]({d['Abrir WhatsApp com mensagem']})" if d["Abrir WhatsApp com mensagem"] else "—"
        ls.append(f"| {i} | {p.prioridade} | {p.nota} | {lim(p.nome)} | {lim(p.categoria)} | {p.distancia_km:.1f} km "
                  f"| {lim(p.bairro)} | {lim(p.telefone) or '—'} | {wa} |")
    if rota:
        ls += ["", f"## Rota sugerida ({len(rota['ordem'])} paradas, saindo de {base.descricao})", "",
               " → ".join(p.nome for p in rota["ordem"]), "",
               f"{rota['km']:.1f} km, ~{rota['minutos_carro']} min dirigindo (estimado), ~{rota['minutos']} min com visitas."]
        ls += [f"- [Abrir trecho {i} no Google Maps]({l})" for i, l in enumerate(rota["links"], 1)]
    ls += ["", "## Arquivos", "", "- `relatorio.html`: abra no navegador (botões de WhatsApp, rota, mapa, status)",
           "- `prospects.xlsx`: planilha completa com colunas para acompanhar os contatos",
           "- `prospects.kml`: importe em mymaps.google.com para ver no mapa",
           "- `prospects.json`: os mesmos dados para outros programas"]
    caminho = Path(caminho)
    caminho.write_text("\n".join(ls) + "\n", encoding="utf-8")
    return caminho


def cmd_bot(cfg, _a):
    from .banco import Banco
    from .bot import Bot
    from .telegram import Telegram
    if not cfg.usuarios_permitidos:
        logging.warning("USUARIOS_PERMITIDOS está vazio: o bot vai recusar todo mundo e responder com o ID de "
                        "quem escrever. Coloque esse ID no .env e reinicie.")
    motor = _motor(cfg)
    try:
        kit.garantir(motor, cfg.motor_url)
    except kit.ErroKit as ex:
        logging.warning("motor de busca: %s", ex)
    Bot(cfg, Telegram(cfg.telegram_token), motor, _geocoder(cfg), Banco(Path(cfg.pasta_dados) / "prospecta.db"),
        perfis_mod.carregar()).rodar()


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="prospecta", description="Prospecção B2B por raio a partir do Google Maps")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("instalar", help="baixa o motor de busca, liga e confere tudo")
    m = sub.add_parser("motor", help="liga, desliga ou mostra o motor de busca")
    m.add_argument("acao", choices=["ligar", "desligar", "status", "reiniciar"])
    p = sub.add_parser("perfis", help="lista os serviços prontos")
    p.add_argument("--json", action="store_true")
    sub.add_parser("verificar", help="testa as conexões")
    sub.add_parser("bot", help="liga o bot do Telegram (opcional)")
    b = sub.add_parser("buscar", help="procura prospects num raio")
    b.add_argument("endereco", help='endereço, CEP ou "latitude, longitude"')
    b.add_argument("--raio", type=float, default=3.0, help="km (padrão 3)")
    b.add_argument("--perfil", default="", help="um serviço pronto (veja: perfis)")
    b.add_argument("--alvos", help='tipos de negócio a procurar, ex.: "padaria, hotel, academia"')
    b.add_argument("--servico", help='nome do seu serviço quando usar --alvos, ex.: "Manutenção de fornos"')
    b.add_argument("--sinais", help='palavras nas avaliações que indicam necessidade, ex.: "forno, queimado"')
    b.add_argument("--mensagem", help="modelo da mensagem de WhatsApp com {prospect} {bairro} {meu_nome} {minha_empresa}")
    b.add_argument("--empresa", help='"Seu Nome | Sua Empresa" para assinar a mensagem')
    b.add_argument("--base", help="endereço da sua empresa, ponto de partida das rotas (padrão: o da busca)")
    b.add_argument("--modo", choices=sorted(busca.MODOS), default="rapido")
    b.add_argument("--so-novos", action="store_true", help="esconde prospects já entregues em buscas anteriores")
    b.add_argument("--rota", type=int, default=10, help="quantos dos melhores entram na rota (0 = sem rota)")
    b.add_argument("--top", type=int, default=15, help="quantos aparecem no resumo.md")
    b.add_argument("--saida", default=str(RAIZ / "resultados"))
    b.add_argument("--sem-sites", action="store_true", help="não abrir os sites para procurar WhatsApp")
    b.add_argument("--nao-ligar", action="store_true", help="não ligar o motor automaticamente")
    a = ap.parse_args(argv)
    cfg = Config.do_ambiente()
    cmds = {"instalar": cmd_instalar, "motor": cmd_motor, "perfis": cmd_perfis, "verificar": cmd_verificar,
            "buscar": cmd_buscar, "bot": cmd_bot}
    return cmds[a.cmd](cfg, a) or 0


if __name__ == "__main__":
    sys.exit(main())
