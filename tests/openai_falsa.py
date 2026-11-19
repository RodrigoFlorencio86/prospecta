"""Servidor falso da OpenAI para testes: OAuth (autorizar, token, JWKS, revogar), /v1/models e
/v1/responses em streaming, com as mesmas regras da documentação do Sign in with ChatGPT."""
import base64
import hashlib
import json
import random
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROIBIDOS = {"background", "conversation", "max_output_tokens", "max_tool_calls", "metadata", "moderation",
             "prompt", "safety_identifier", "temperature", "top_p", "truncation", "user", "previous_response_id"}


def _primo(bits, rnd):
    while True:
        n = rnd.getrandbits(bits) | (1 << (bits - 1)) | 1
        if all(n % p for p in (3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)) and _miller(n, rnd):
            return n


def _miller(n, rnd, k=24):
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(k):
        x = pow(rnd.randrange(2, n - 2), d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


class ChaveRSA:
    def __init__(self, bits=1024, semente=7):
        rnd = random.Random(semente)
        e = 65537
        while True:
            p, q = _primo(bits // 2, rnd), _primo(bits // 2, rnd)
            phi = (p - 1) * (q - 1)
            if p != q and phi % e:
                break
        self.n, self.e, self.d = p * q, e, pow(e, -1, phi)
        self.kid = "chave-teste"

    def jwk(self):
        b = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()  # noqa: E731
        return {"kty": "RSA", "kid": self.kid, "alg": "RS256", "use": "sig", "n": b(self.n), "e": b(self.e)}

    def assinar(self, cabecalho, corpo):
        b64 = lambda x: base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b"=").decode()  # noqa: E731
        msg = f"{b64(cabecalho)}.{b64(corpo)}".encode()
        k = (self.n.bit_length() + 7) // 8
        t = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(msg).digest()
        em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
        s = pow(int.from_bytes(em, "big"), self.d, self.n).to_bytes(k, "big")
        return msg.decode() + "." + base64.urlsafe_b64encode(s).rstrip(b"=").decode()


class OpenAIFalsa:
    def __init__(self):
        self.chave = ChaveRSA()
        self.codigos = {}           # code -> dados da autorização
        self.autorizacoes = []      # parâmetros recebidos em /authorize
        self.revogados = []
        self.pedidos_responses = []
        self.recusar_plano = False  # simula o usuário negando o escopo do plano
        self.limite = False         # simula limite de uso atingido
        self.roteiro = None         # função(corpo) -> lista de eventos SSE
        self.refreshs = 0
        dono = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = dict(urllib.parse.parse_qsl(u.query))
                if u.path == "/.well-known/openid-configuration":
                    b = dono.url
                    return self._json(200, {"issuer": b, "authorization_endpoint": f"{b}/api/accounts/authorize",
                                            "token_endpoint": f"{b}/api/accounts/oauth/token",
                                            "jwks_uri": f"{b}/.well-known/jwks.json",
                                            "revocation_endpoint": f"{b}/oauth/revoke"})
                if u.path == "/.well-known/jwks.json":
                    return self._json(200, {"keys": [dono.chave.jwk()]})
                if u.path == "/api/accounts/authorize":
                    return dono._autorizar(self, q)
                if u.path == "/v1/models":
                    if not dono._token_ok(self):
                        return self._json(401, {"detail": "invalid token"})
                    return self._json(200, {"models": [{"slug": "gpt-teste", "display_name": "GPT Teste",
                                                        "visibility": "list"},
                                                       {"slug": "oculto", "display_name": "X", "visibility": "hide"}]})
                self._json(404, {})

            def do_POST(self):
                u = urllib.parse.urlsplit(self.path)
                corpo = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if u.path == "/api/accounts/oauth/token":
                    return dono._token(self, dict(urllib.parse.parse_qsl(corpo.decode())))
                if u.path == "/oauth/revoke":
                    dono.revogados.append(dict(urllib.parse.parse_qsl(corpo.decode())))
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                if u.path == "/v1/responses":
                    return dono._responder(self, json.loads(corpo))
                self._json(404, {})

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def fechar(self):
        self.srv.shutdown()
        self.srv.server_close()

    # ── OAuth ──
    def _autorizar(self, h, q):
        self.autorizacoes.append(q)
        assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
        assert q["resource"] == "https://api.openai.com/v1" and q["ext_agent_host_id"].startswith("urn:uuid:")
        assert q["redirect_uri"].startswith("http://127.0.0.1:") and q["redirect_uri"].endswith("/auth/callback")
        novo = q["client_id"] == "dynamic_agent_client"
        if novo:
            assert q.get("agent_name_hint") == "Prospecta"
        else:
            assert "agent_name_hint" not in q
        cid = "oaiapp_teste123" if novo else q["client_id"]
        escopos = q["scope"].split()
        if self.recusar_plano:
            escopos = [s for s in escopos if s != "chatgpt.tokens.use.direct"]
        code = f"code-{len(self.codigos)}"
        self.codigos[code] = {"client_id": cid, "challenge": q["code_challenge"], "nonce": q["nonce"],
                              "redirect_uri": q["redirect_uri"], "scope": " ".join(escopos)}
        volta = {"code": code, "state": q["state"], "scope": " ".join(escopos)}
        if novo:
            volta["client_id"] = cid
        h.send_response(302)
        h.send_header("Location", q["redirect_uri"] + "?" + urllib.parse.urlencode(volta))
        h.send_header("Content-Length", "0")
        h.end_headers()

    def _id_token(self, cid, nonce, sub="usuario-1"):
        agora = int(time.time())
        return self.chave.assinar({"alg": "RS256", "kid": self.chave.kid, "typ": "JWT"},
                                  {"iss": self.url, "aud": cid, "sub": sub, "email": "ana@exemplo.com",
                                   "iat": agora, "exp": agora + 3600, "nonce": nonce})

    def _token(self, h, f):
        if f.get("grant_type") == "authorization_code":
            c = self.codigos.pop(f.get("code"), None)
            ok = c and f.get("client_id") == c["client_id"] and f.get("redirect_uri") == c["redirect_uri"] \
                and base64.urlsafe_b64encode(hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode() == c["challenge"] \
                and f.get("resource") == "https://api.openai.com/v1"
            if not ok:
                return h._json(400, {"error": "invalid_grant"})
            return h._json(200, {"access_token": f"at-{time.time()}", "refresh_token": "rt-1", "token_type": "Bearer",
                                 "expires_in": 3600, "scope": c["scope"], "earliest_refresh_at": 0,
                                 "id_token": self._id_token(c["client_id"], c["nonce"])})
        if f.get("grant_type") == "refresh_token":
            if f.get("refresh_token") == "rt-morto":
                return h._json(400, {"error": "invalid_grant"})
            self.refreshs += 1
            return h._json(200, {"access_token": f"at-renovado-{self.refreshs}", "refresh_token": f"rt-{self.refreshs + 1}",
                                 "token_type": "Bearer", "expires_in": 3600,
                                 "scope": "chatgpt.tokens.use.direct email offline_access openid profile resource.invoke"})
        return h._json(400, {"error": "unsupported_grant_type"})

    @staticmethod
    def _token_ok(h):
        return (h.headers.get("Authorization") or "").startswith("Bearer at-")

    # ── Responses ──
    def _responder(self, h, corpo):
        self.pedidos_responses.append(corpo)
        if not self._token_ok(h):
            return h._json(401, {"detail": "token inválido"})
        assert corpo["store"] is False and corpo["stream"] is True
        assert not (PROIBIDOS & set(corpo)), PROIBIDOS & set(corpo)
        assert all(i.get("role") != "system" for i in corpo["input"] if isinstance(i, dict))
        assert corpo["tools"][0]["type"] == "namespace"
        if self.limite:
            eventos = [{"type": "response.created", "response": {"id": "r1"}},
                       {"type": "response.failed", "response": {"error": {
                           "code": "subscription_sharing_usage_limit_exceeded", "message": "limite"}}}]
        else:
            eventos = (self.roteiro or _roteiro_padrao)(corpo)
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.end_headers()
        for ev in eventos:
            h.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
            h.wfile.flush()


def _roteiro_padrao(corpo):
    """1ª rodada: chama consultar_prospects; 2ª (com o resultado): responde em texto."""
    saidas = [i for i in corpo["input"] if isinstance(i, dict) and i.get("type") == "function_call_output"]
    if not saidas:
        item = {"type": "function_call", "id": "fc1", "call_id": "call_1", "namespace": "prospecta",
                "name": "consultar_prospects", "arguments": json.dumps({"prioridade": "A", "limite": 3}),
                "status": "completed"}
        return [{"type": "response.output_item.done", "item": item},
                {"type": "response.completed", "response": {"id": "r1", "output": [
                    {"type": "reasoning", "id": "rs1", "encrypted_content": "xyz", "summary": []}, item]}}]
    dados = json.loads(saidas[-1]["output"])
    texto = f"Achei {dados.get('total_filtrado', 0)} prospects A."
    msg = {"type": "message", "id": "m1", "role": "assistant", "status": "completed",
           "content": [{"type": "output_text", "text": texto, "annotations": []}]}
    return [{"type": "response.output_text.delta", "delta": texto},
            {"type": "response.completed", "response": {"id": "r2", "output": [msg]}}]
