"""Painel local no navegador: nova busca com progresso, histórico, mapa e lista de prospects com status,
rota, exportação e o chat que usa o plano do ChatGPT do usuário.

Segurança: só escuta em 127.0.0.1; recusa Host e Origin de fora (DNS rebinding, sites maliciosos); toda
chamada à API exige o token aleatório desta execução, que só a página do painel conhece."""
import json
import mimetypes
import os
import re
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .chat import AgenteChat, ErroChat
from .chatgpt import GERENCIAR_USO, Autenticador, ErroLogin
from .ferramentas import ErroFerramenta, Prospecta
from .motor import ErroMotor

PORTA_PADRAO = 8765
PAGINA = Path(__file__).with_name("painel.html")
ARQUIVOS = {"relatorio.html", "prospects.xlsx", "prospects.csv", "prospects.kml", "prospects.json", "resumo.md"}
MAX_CORPO = 200_000


class ServidorPainel(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, porta, app, auth, agente):
        super().__init__(("127.0.0.1", porta), Manipulador)
        self.porta = self.server_address[1]
        self.app, self.auth, self.agente = app, auth, agente
        self.token = secrets.token_urlsafe(24)
        self.exportados = {}  # busca_id -> pasta
        self._motor = (0.0, False)

    @property
    def redirect_uri(self):
        return f"http://127.0.0.1:{self.porta}/auth/callback"

    def motor_ok(self):
        quando, ok = self._motor
        if time.time() - quando > 15:
            try:
                ok = self.app.motor.saude()
            except ErroMotor:
                ok = False
            self._motor = (time.time(), ok)
        return ok

    def server_bind(self):  # sem getfqdn(), que pode levar segundos
        import socketserver
        socketserver.TCPServer.server_bind(self)


class Manipulador(BaseHTTPRequestHandler):
    server_version = f"Prospecta/{__version__}"

    def log_message(self, fmt, *args):
        pass

    # ── respostas ──
    def _enviar(self, status, corpo, tipo="application/json; charset=utf-8", extra=()):
        if isinstance(corpo, (dict, list)) or corpo is None:
            corpo = json.dumps(corpo, ensure_ascii=False, default=str).encode()
        elif isinstance(corpo, str):
            corpo = corpo.encode()
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _erro(self, status, msg, **extra):
        self._enviar(status, dict({"erro": msg}, **extra))

    def _redirecionar(self, destino):
        self.send_response(303)
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── segurança ──
    def _seguro(self, exige_token=True, token_na_url=None):
        porta = self.server.porta
        host = self.headers.get("Host", "")
        if not re.fullmatch(rf"(127\.0\.0\.1|localhost):{porta}", host):
            self._erro(421, "o painel só atende em 127.0.0.1")
            return False
        origem = self.headers.get("Origin")
        if origem is not None and origem not in (f"http://127.0.0.1:{porta}", f"http://localhost:{porta}"):
            self._erro(403, "pedido de outro site recusado")
            return False
        if exige_token:
            dado = token_na_url if token_na_url is not None else self.headers.get("X-Prospecta", "")
            if not secrets.compare_digest(dado.encode(), self.server.token.encode()):
                self._erro(401, "token do painel ausente ou inválido; recarregue a página")
                return False
        return True

    def _json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if not 0 <= n <= MAX_CORPO:
            raise ErroFerramenta("pedido grande demais")
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            raise ErroFerramenta("JSON inválido") from None
        if not isinstance(d, dict):
            raise ErroFerramenta("JSON deve ser um objeto")
        return d

    # ── rotas ──
    def do_GET(self):
        self._protegido(self._get)

    def do_POST(self):
        self._protegido(self._post)

    def _protegido(self, fn):
        try:
            fn()
        except Exception as ex:  # um erro inesperado vira 500 com mensagem, não conexão derrubada
            import traceback
            traceback.print_exc()
            try:
                self._erro(500, f"erro interno: {ex}")
            except OSError:
                pass

    def _get(self):
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        caminho = url.path
        if caminho in ("/", "/index.html"):
            if not self._seguro(exige_token=False):
                return
            html = PAGINA.read_text(encoding="utf-8").replace("__TOKEN__", self.server.token)
            csp = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; "
                   "style-src 'self' 'unsafe-inline' https://unpkg.com; img-src 'self' data: https://*.tile.openstreetmap.org "
                   "https://unpkg.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            return self._enviar(200, html, "text/html; charset=utf-8", [("Content-Security-Policy", csp)])
        if caminho == "/auth/callback":
            if not self._seguro(exige_token=False):
                return
            return self._callback(q)
        if caminho == "/auth/entrar":
            if not self._seguro(token_na_url=q.get("t", "")):
                return
            try:
                destino = self.server.auth.iniciar(self.server.redirect_uri, nova=q.get("nova") == "1",
                                                   forcar_consentimento=q.get("consentir") == "1")
            except ErroLogin as ex:
                return self._redirecionar("/?login_erro=" + urllib.parse.quote(str(ex)))
            return self._redirecionar(destino)
        if caminho.startswith("/arquivos/"):
            if not self._seguro(token_na_url=q.get("t", "")):
                return
            return self._arquivo(caminho)
        if not caminho.startswith("/api/") or not self._seguro():
            return None if caminho.startswith("/api/") else self._erro(404, "não encontrado")
        try:
            return self._api_get(caminho, q)
        except (ErroFerramenta, ErroMotor) as ex:
            return self._erro(400, str(ex))

    def _post(self):
        caminho = urllib.parse.urlsplit(self.path).path
        if not self._seguro():
            return
        try:
            corpo = self._json()
            return self._api_post(caminho, corpo)
        except (ErroFerramenta, ErroMotor, ErroLogin) as ex:
            return self._erro(400, str(ex))
        except ErroChat as ex:
            return self._erro(502 if ex.tipo in ("rede", "temporario") else 400, str(ex), tipo=ex.tipo,
                              gerenciar_uso=GERENCIAR_USO)

    # ── implementação ──
    def _estado(self):
        app, auth = self.server.app, self.server.auth
        conta = auth.contas.ativa()
        info_conta = None
        if conta and conta.get("access_token"):
            info_conta = {"email": conta.get("email"), "plano": auth.plano_liberado(conta),
                          "boas_vindas_vista": conta.get("boas_vindas_vista", False)}
        elif conta:
            info_conta = {"email": conta.get("email"), "plano": False, "desconectada": True}
        return {"versao": __version__, "config": app.configuracao(), "perfis": app.listar_perfis(),
                "conta": info_conta, "tarefas": app.listar_tarefas(8), "buscas": app.listar_buscas(30),
                "motor": self.server.motor_ok(), "gerenciar_uso": GERENCIAR_USO,
                "raio_maximo_km": app.cfg.raio_maximo_km}

    def _api_get(self, caminho, q):
        app = self.server.app
        if caminho == "/api/estado":
            return self._enviar(200, self._estado())
        if caminho == "/api/tarefas":
            return self._enviar(200, app.listar_tarefas(8))
        m = re.fullmatch(r"/api/buscas/(\d+)", caminho)
        if m:
            return self._enviar(200, app.busca_completa(int(m.group(1))))
        m = re.fullmatch(r"/api/buscas/(\d+)/rota", caminho)
        if m:
            n = int(q.get("n") or 8)
            return self._enviar(200, app.planejar_rota(int(m.group(1)), quantidade=n, prioridade=q.get("prioridade")))
        if caminho == "/api/chat/modelos":
            try:
                return self._enviar(200, self.server.agente.modelos())
            except ErroChat as ex:
                return self._erro(400, str(ex), tipo=ex.tipo)
        if caminho == "/api/funil":
            return self._enviar(200, app.resumo_funil())
        return self._erro(404, "não encontrado")

    def _api_post(self, caminho, d):
        app, srv = self.server.app, self.server
        if caminho == "/api/config":
            campos = {k: d[k] for k in ("meu_nome", "minha_empresa", "base_endereco", "raio_km", "modo", "perfil")
                      if k in d}
            return self._enviar(200, app.configurar(**campos))
        if caminho == "/api/buscas":
            opcoes = {k: d.get(k) or None for k in ("raio_km", "perfil", "alvos", "servico", "sinais", "mensagem", "modo")}
            opcoes["so_novos"] = bool(d.get("so_novos"))
            if not (d.get("endereco") or "").strip():
                raise ErroFerramenta("informe o endereço")
            r = app.iniciar_busca(d["endereco"], **opcoes)
            lembrar = {"raio_km": opcoes["raio_km"], "modo": opcoes["modo"]}
            if opcoes["perfil"] and not opcoes["alvos"]:
                lembrar["perfil"] = opcoes["perfil"]
            try:  # o painel abre da próxima vez com as mesmas escolhas
                app.configurar(**{k: v for k, v in lembrar.items() if v})
            except ErroFerramenta:
                pass
            return self._enviar(200, r)
        m = re.fullmatch(r"/api/tarefas/(\d+)/cancelar", caminho)
        if m:
            return self._enviar(200, app.cancelar_busca(int(m.group(1))))
        if caminho == "/api/prospects/marcar":
            return self._enviar(200, app.marcar_prospect(d.get("chave", ""), d.get("status"), d.get("observacao")))
        m = re.fullmatch(r"/api/buscas/(\d+)/exportar", caminho)
        if m:
            exp = app.exportar(int(m.group(1)))
            srv.exportados[exp["busca_id"]] = Path(exp["pasta"])
            t = urllib.parse.quote(srv.token)
            links = {k: f"/arquivos/{exp['busca_id']}/{Path(v).name}?t={t}" for k, v in exp["arquivos"].items()}
            return self._enviar(200, {"pasta": exp["pasta"], "links": links})
        if caminho == "/api/chat":
            agente = srv.agente
            conversa = agente.conversa(d.get("conversa_id"))
            texto = (d.get("mensagem") or "").strip()
            if not texto:
                raise ErroFerramenta("mensagem vazia")
            r = agente.enviar(conversa, texto, d.get("modelo"))
            return self._enviar(200, dict(r, conversa_id=conversa.id))
        if caminho == "/api/chat/boas-vindas":
            srv.auth.marcar_boas_vindas()
            return self._enviar(200, {"ok": True})
        if caminho == "/auth/sair":
            aviso = srv.auth.sair()
            srv.agente.conversas.clear()
            return self._enviar(200, {"ok": True, "aviso": aviso})
        return self._erro(404, "não encontrado")

    def _callback(self, q):
        try:
            self.server.auth.concluir(q)
        except ErroLogin as ex:
            return self._redirecionar("/?login_erro=" + urllib.parse.quote(str(ex)))
        return self._redirecionar("/?login=ok")

    def _arquivo(self, caminho):
        m = re.fullmatch(r"/arquivos/(\d+)/([a-z_.]+)", caminho)
        pasta = self.server.exportados.get(int(m.group(1))) if m else None
        if not m or m.group(2) not in ARQUIVOS or not pasta:
            return self._erro(404, "arquivo não encontrado; gere de novo pelo botão Exportar")
        arq = pasta / m.group(2)
        if not arq.is_file():
            return self._erro(404, "arquivo não encontrado")
        tipo = mimetypes.guess_type(arq.name)[0] or "application/octet-stream"
        if arq.suffix in (".html", ".md", ".json", ".kml", ".csv"):
            tipo += "; charset=utf-8"
        disp = "inline" if arq.suffix == ".html" else f'attachment; filename="{arq.name}"'
        self._enviar(200, arq.read_bytes(), tipo, [("Content-Disposition", disp)])


def porta_livre(preferida):
    for p in [preferida] + list(range(preferida + 1, preferida + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 0


def criar(cfg, porta=None, app=None, auth=None, agente=None):
    app = app or Prospecta(cfg)
    auth = auth or Autenticador()
    agente = agente or AgenteChat(app, auth)
    return ServidorPainel(porta_livre(porta or PORTA_PADRAO) if porta != 0 else 0, app, auth, agente)


def servir(cfg, porta=None, abrir=True):
    srv = criar(cfg, porta)
    url = f"http://127.0.0.1:{srv.porta}/"
    marca = Path(cfg.pasta_dados) / "painel.json"  # para a ferramenta abrir_painel achar este painel
    try:
        marca.parent.mkdir(parents=True, exist_ok=True)
        marca.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
    except OSError:
        pass
    print(f"✓ Painel do Prospecta em {url}\n  (deixe esta janela aberta; Ctrl+C para fechar)")
    if abrir:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nPainel fechado. Buscas em andamento continuam em segundo plano.")
    finally:
        srv.server_close()
        try:
            marca.unlink()
        except OSError:
            pass
    return 0
