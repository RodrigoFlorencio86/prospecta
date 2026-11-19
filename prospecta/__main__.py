"""Linha de comando (é o que o seu agente de IA roda por você).

    python -m prospecta instalar                     # baixa o motor de busca, confere e abre o painel
    python -m prospecta painel                       # painel no navegador (busca, mapa, contatos, chat)
    python -m prospecta buscar "Rua X, 100, Campinas" --raio 3 --perfil climatizacao
    python -m prospecta buscar "13010-001" --alvos "padaria, hotel" --empresa "Ana | Frio Total"
    python -m prospecta perfis [--json]              # serviços prontos
    python -m prospecta conectar claude|claude-desktop|codex  # liga o Prospecta ao Claude Code, Claude Desktop ou Codex (MCP)
    python -m prospecta mcp                          # servidor MCP (quem roda é o Claude Code / Codex)
    python -m prospecta chatgpt status|sair          # conta do ChatGPT usada no chat do painel
    python -m prospecta motor ligar|desligar|status
    python -m prospecta verificar                    # testa motor, mapas e Telegram
    python -m prospecta bot                          # opcional: bot do Telegram
"""
import argparse
import json
import logging
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from . import busca, geo, kit, perfis as perfis_mod
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


def _app(cfg, **k):
    from .ferramentas import Prospecta
    return Prospecta(cfg, **k)


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
        print(f"✓ criei {env} (coloque seu e-mail em CONTATO_GEOCODER)")
    print("\nPronto. Para usar:\n"
          "  • painel no navegador:  python -m prospecta painel\n"
          "  • no app do Claude:     python -m prospecta conectar claude-desktop\n"
          "  • no Claude Code:       python -m prospecta conectar claude\n"
          "  • pela linha de comando: python -m prospecta buscar \"Rua X, 100, Sua Cidade\" --raio 3 --perfil limpeza")
    if not a.sem_painel:
        print()
        return cmd_painel(cfg, argparse.Namespace(porta=None, nao_abrir=False))
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
    from . import chatgpt
    conta = chatgpt.Contas().ativa()
    print("ChatGPT:", f"conectado ({conta.get('email')})" if conta and conta.get("access_token") else "não conectado (opcional)")
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


def cmd_buscar(cfg, a):
    from .ferramentas import ErroFerramenta
    app = _app(cfg, log=print)
    try:
        if a.empresa:
            nome, _, empresa = a.empresa.partition("|")
            app.configurar(meu_nome=nome, minha_empresa=empresa)
        if a.base:
            app.configurar(base_endereco=a.base)
        opcoes = dict(raio_km=a.raio, perfil=a.perfil or None, alvos=a.alvos, servico=a.servico, sinais=a.sinais,
                      mensagem=a.mensagem, modo=a.modo, so_novos=a.so_novos)
        if not a.perfil and not a.alvos:
            sys.exit("✗ informe --perfil (veja: python -m prospecta perfis) ou --alvos \"tipo 1, tipo 2\"")
        p = app.preparar_busca(a.endereco, **opcoes)
    except ErroFerramenta as ex:
        sys.exit(f"✗ {ex}")
    print(f"📍 {p['local']['descricao']}\n🔎 {p['perfil']['nome']}: {', '.join(p['perfil']['alvos'])}\n"
          f"   raio {p['raio_km']:g} km · modo {busca.MODOS[p['modo']]['nome']} · {p['areas']} área(s) · "
          f"~{p['estimativa_min']} min (estimativa)")
    if not a.nao_ligar:
        try:
            kit.garantir(app.motor, cfg.motor_url)
        except kit.ErroKit as ex:
            sys.exit(f"✗ {ex}")

    def progresso(feitos, total, lugares):
        print(f"\r   {int(100 * feitos / max(total, 1)):3d}% · área {min(int(feitos) + 1, total)}/{total} · "
              f"{lugares} lugares lidos", end="", flush=True)

    try:
        busca_id, info = app.rodar(p, progresso=progresso, cancelar=threading.Event())
    except (ErroMotor, ErroFerramenta) as ex:
        sys.exit(f"\n✗ {ex}")
    print(f"\n\n✅ {info}")
    exp = app.exportar(busca_id, top=a.top)
    print(f"\n📂 {exp['pasta']}")
    for nome, caminho in exp["arquivos"].items():
        print(f"   {nome:10} {Path(caminho).name}")
    print(f"\nAbra o relatório no navegador: {Path(exp['arquivos']['relatorio']).as_uri()}")
    print("Ou veja tudo no painel: python -m prospecta painel")
    return 0


def cmd_painel(cfg, a):
    from .painel import servir
    return servir(cfg, porta=a.porta, abrir=not a.nao_abrir)


def cmd_trabalhar(cfg, _a):
    """Processo em segundo plano que executa as buscas da fila (disparado pelo painel, chat e MCP)."""
    _app(cfg, log=lambda *x: print(*x, file=sys.stderr)).trabalhar_fila()
    return 0


def cmd_empacotar(cfg, a):
    from . import extensao
    if a.pasta:
        print(f"✓ arquivos da extensão em {extensao.gravar_pasta(a.pasta)}")
        return 0
    destino = extensao.empacotar(a.saida_pacote)
    print(f"✓ extensão do Claude Desktop: {destino} ({destino.stat().st_size // 1024} KB)\n"
          "  Para instalar: abra o Claude Desktop > Configurações > Extensões > Configurações avançadas >\n"
          "  \"Instalar extensão…\" e escolha esse arquivo (ou dê dois cliques nele).")
    return 0


def cmd_mcp(cfg, _a):
    from .mcp_servidor import servir
    return servir(cfg)


def cmd_conectar(cfg, a):
    """Registra o servidor MCP no Claude Code, no Claude Desktop ou no Codex, com caminhos absolutos."""
    if a.cliente == "claude-desktop":
        return _conectar_desktop(a.remover)
    lancador = str((RAIZ / "mcp.py").resolve())
    if a.remover:
        cmd = ["claude", "mcp", "remove", "--scope", "user", "prospecta"] if a.cliente == "claude" else \
            ["codex", "mcp", "remove", "prospecta"]
        return subprocess.run(cmd).returncode if shutil.which(cmd[0]) else 1
    if a.cliente == "claude":
        cmd = ["claude", "mcp", "add", "--scope", "user", "prospecta", "--", sys.executable, lancador]
    else:
        cmd = ["codex", "mcp", "add", "prospecta", "--", sys.executable, lancador]
    if not shutil.which(cmd[0]):
        print(f"Não achei o comando '{cmd[0]}'. Instale o {'Claude Code' if a.cliente == 'claude' else 'Codex'} "
              f"e rode de novo, ou registre manualmente:\n  {' '.join(_q(c) for c in cmd)}")
        return 1
    print("▶", " ".join(_q(c) for c in cmd))
    r = subprocess.run(cmd)
    if r.returncode == 0:
        print(f"✓ pronto: abra o {'Claude Code' if a.cliente == 'claude' else 'Codex'} e peça, por exemplo, "
              "\"procure padarias num raio de 2 km da Rua X, 100, Campinas\".")
    return r.returncode


def _conectar_desktop(remover=False):
    from . import desktop
    try:
        feitos = desktop.desconectar() if remover else desktop.conectar()
    except (desktop.ErroDesktop, OSError) as ex:
        sys.exit(f"✗ {ex}")
    if remover:
        print("\n".join(f"✓ removido de {c}" for c, _ in feitos) or "O Prospecta não estava no Claude Desktop.")
        return 0
    for caminho, estado in feitos:
        print({"adicionado": "✓ Prospecta adicionado", "atualizado": "✓ Prospecta atualizado",
               "igual": "✓ Prospecta já estava configurado"}[estado] + f" em {caminho}")
    e = desktop.entrada()
    print(f"   comando: {e['command']} {e['args'][0]}")
    print("\nAgora feche o Claude Desktop por completo (no Mac: Claude > Sair; no Windows: clique com o botão\n"
          "direito no ícone perto do relógio > Sair) e abra de novo. Para conferir: no chat, clique em \"+\"\n"
          "> Conectores; o \"prospecta\" deve aparecer com as ferramentas. Depois é só pedir, por exemplo:\n"
          "\"procure padarias num raio de 2 km da Rua X, 100, Campinas\".")
    if sys.platform.startswith("linux"):
        print("\nObs.: no Linux o caminho do arquivo pode variar conforme a versão do app.")
    return 0


def _q(s):
    return f'"{s}"' if " " in s else s


def cmd_chatgpt(cfg, a):
    from . import chatgpt
    contas = chatgpt.Contas()
    conta = contas.ativa()
    if a.acao == "status":
        if not conta:
            print("Nenhuma conta do ChatGPT conectada. Conecte pelo painel: python -m prospecta painel")
        else:
            uso = "liberado" if chatgpt.ESCOPO_PLANO in (conta.get("scopes") or []) else "NÃO autorizado"
            print(f"Conta: {conta.get('email')} · uso do plano: {uso} · sessão: "
                  f"{'ativa' if conta.get('refresh_token') else 'encerrada'}")
        return 0
    if not conta:
        print("Nenhuma conta conectada.")
        return 0
    aviso = chatgpt.Autenticador(contas).sair()
    print("✓ desconectado." + (f" {aviso}" if aviso else ""))
    return 0


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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    ap = argparse.ArgumentParser(prog="prospecta", description="Prospecção B2B por raio a partir do Google Maps")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("instalar", help="baixa o motor de busca, liga, confere e abre o painel")
    i.add_argument("--sem-painel", action="store_true", help="não abrir o painel no final")
    pn = sub.add_parser("painel", help="painel no navegador")
    pn.add_argument("--porta", type=int, help="porta local (padrão 8765)")
    pn.add_argument("--nao-abrir", action="store_true", help="não abrir o navegador")
    sub.add_parser("mcp", help="servidor MCP (stdio) para Claude Code / Codex")
    sub.add_parser("trabalhar", help=argparse.SUPPRESS)
    ex = sub.add_parser("empacotar-extensao", help="gera a extensão do Claude Desktop (.mcpb)")
    ex.add_argument("--saida", dest="saida_pacote", help="arquivo .mcpb a gerar (padrão: dist/prospecta-<versão>.mcpb)")
    ex.add_argument("--pasta", help="em vez do .mcpb, grava os arquivos numa pasta (para o mcpb oficial)")
    c = sub.add_parser("conectar", help="registra o Prospecta no Claude Code, no Claude Desktop ou no Codex")
    c.add_argument("cliente", choices=["claude", "claude-desktop", "codex"])
    c.add_argument("--remover", action="store_true", help="tira o Prospecta desse aplicativo")
    g = sub.add_parser("chatgpt", help="conta do ChatGPT do chat do painel")
    g.add_argument("acao", choices=["status", "sair"])
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
    b.add_argument("--empresa", help='"Seu Nome | Sua Empresa" para assinar a mensagem (fica salvo)')
    b.add_argument("--base", help="endereço da sua empresa, ponto de partida das rotas (fica salvo)")
    b.add_argument("--modo", choices=sorted(busca.MODOS), default="rapido")
    b.add_argument("--so-novos", action="store_true", help="esconde prospects já entregues em buscas anteriores")
    b.add_argument("--top", type=int, default=15, help="quantos aparecem no resumo.md")
    b.add_argument("--saida", help="pasta dos resultados (padrão: resultados/)")
    b.add_argument("--sem-sites", action="store_true", help=argparse.SUPPRESS)
    b.add_argument("--nao-ligar", action="store_true", help="não ligar o motor automaticamente")
    a = ap.parse_args(argv)
    cfg = Config.do_ambiente()
    if getattr(a, "saida", None):
        cfg.pasta_resultados = Path(a.saida)
    cmds = {"instalar": cmd_instalar, "painel": cmd_painel, "mcp": cmd_mcp, "conectar": cmd_conectar,
            "chatgpt": cmd_chatgpt, "motor": cmd_motor, "perfis": cmd_perfis, "verificar": cmd_verificar,
            "buscar": cmd_buscar, "bot": cmd_bot, "trabalhar": cmd_trabalhar,
            "empacotar-extensao": cmd_empacotar}
    return cmds[a.cmd](cfg, a) or 0


if __name__ == "__main__":
    sys.exit(main())
