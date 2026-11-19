"""Entrar com ChatGPT (Sign in with ChatGPT) e usar o plano do usuário no chat do painel.

Segue o fluxo documentado pela OpenAI para apps de código aberto e locais
(https://developers.openai.com/siwc/token-sharing-open-source):

- registro dinâmico na primeira vez (client_id=dynamic_agent_client) com um identificador estável deste
  computador (ext_agent_host_id) e o nome do app; depois, reautorização com o client_id emitido;
- Authorization Code + PKCE (S256), state e nonce novos a cada tentativa, retorno em 127.0.0.1;
- validação do ID token (assinatura RS256 pelo JWKS, emissor, audiência, validade, nonce) e do escopo
  chatgpt.tokens.use.direct antes de qualquer uso do plano;
- credenciais num arquivo local só do usuário (0600), renovação perto do vencimento, revogação ao sair.

Só biblioteca padrão: a verificação RS256 é feita aqui mesmo (PKCS#1 v1.5 com SHA-256)."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from . import rede

EMISSOR = "https://auth.openai.com"
PADRAO = {"authorization_endpoint": f"{EMISSOR}/api/accounts/authorize",
          "token_endpoint": f"{EMISSOR}/api/accounts/oauth/token",
          "jwks_uri": f"{EMISSOR}/.well-known/jwks.json",
          "revocation_endpoint": "",  # só o que a descoberta (openid-configuration) informar
          "issuer": EMISSOR}
RECURSO = "https://api.openai.com/v1"
ESCOPO_PLANO = "chatgpt.tokens.use.direct"
ESCOPOS = "openid profile email offline_access resource.invoke " + ESCOPO_PLANO
NOME_APP = "Prospecta"
CLIENTE_DINAMICO = "dynamic_agent_client"
GERENCIAR_USO = "https://chatgpt.com/settings/usage"


class ErroLogin(RuntimeError):
    pass


def pasta_config():
    if os.environ.get("PROSPECTA_CONFIG"):
        return Path(os.environ["PROSPECTA_CONFIG"])
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / "prospecta"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "prospecta"


def _gravar_protegido(caminho, dados):
    """Grava JSON de forma atômica e legível só pelo dono (0600)."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(caminho.parent, 0o700)
    except OSError:
        pass
    tmp = caminho.with_name(caminho.name + f".{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    os.replace(tmp, caminho)


def id_do_computador():
    """ext_agent_host_id estável deste computador (urn:uuid), criado uma vez e guardado."""
    arq = pasta_config() / "host.json"
    try:
        hid = json.loads(arq.read_text(encoding="utf-8")).get("ext_agent_host_id")
        if isinstance(hid, str) and hid.startswith("urn:uuid:"):
            return hid
    except (OSError, ValueError):
        pass
    hid = f"urn:uuid:{uuid.uuid4()}"
    _gravar_protegido(arq, {"ext_agent_host_id": hid})
    return hid


class Contas:
    """Registros de contas do ChatGPT (um por client_id emitido), com a conta ativa."""

    def __init__(self, pasta=None):
        self.arq = Path(pasta or pasta_config()) / "contas.json"
        self.trava = threading.Lock()

    def _ler(self):
        try:
            d = json.loads(self.arq.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("contas"), dict):
                return d
        except (OSError, ValueError):
            pass
        return {"ativa": None, "contas": {}}

    def ativa(self):
        d = self._ler()
        return d["contas"].get(d.get("ativa") or "")

    def todas(self):
        return list(self._ler()["contas"].values())

    def salvar(self, registro, ativar=True):
        with self.trava:
            d = self._ler()
            d["contas"][registro["client_id"]] = registro
            if ativar:
                d["ativa"] = registro["client_id"]
            _gravar_protegido(self.arq, d)

    def ativar(self, client_id):
        with self.trava:
            d = self._ler()
            if client_id not in d["contas"]:
                raise ErroLogin("conta não encontrada")
            d["ativa"] = client_id
            _gravar_protegido(self.arq, d)


# ── JWT RS256 ──

def _b64url(s):
    s = s.encode() if isinstance(s, str) else s
    return base64.urlsafe_b64decode(s + b"=" * (-len(s) % 4))


def _int(b):
    return int.from_bytes(_b64url(b), "big")


DIGEST_SHA256 = bytes.fromhex("3031300d060960864801650304020105000420")


def verificar_rs256(mensagem, assinatura, n, e):
    """Verificação PKCS#1 v1.5 com SHA-256 (RFC 8017, 8.2.2)."""
    k = (n.bit_length() + 7) // 8
    if len(assinatura) != k:
        return False
    s = int.from_bytes(assinatura, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = DIGEST_SHA256 + hashlib.sha256(mensagem).digest()
    if k < len(t) + 11:
        return False
    esperado = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, esperado)


def decodificar_jwt(token):
    try:
        cab, corpo, ass = token.split(".")
        return json.loads(_b64url(cab)), json.loads(_b64url(corpo)), _b64url(ass), f"{cab}.{corpo}".encode()
    except (ValueError, AttributeError) as ex:
        raise ErroLogin("ID token malformado") from ex


class Autenticador:
    def __init__(self, contas=None, emissor_url=EMISSOR):
        self.contas = contas or Contas()
        self.emissor_url = emissor_url.rstrip("/")
        self._descoberta = None
        self._jwks = {}
        self.pendentes = {}  # state -> tentativa em andamento
        self.trava_renovacao = threading.Lock()

    # ── descoberta e chaves ──
    def descoberta(self):
        if self._descoberta is None:
            d = dict(PADRAO) if self.emissor_url == EMISSOR else {
                "authorization_endpoint": f"{self.emissor_url}/api/accounts/authorize",
                "token_endpoint": f"{self.emissor_url}/api/accounts/oauth/token",
                "jwks_uri": f"{self.emissor_url}/.well-known/jwks.json",
                "revocation_endpoint": "", "issuer": self.emissor_url}
            try:
                lido = rede.json_get(f"{self.emissor_url}/.well-known/openid-configuration", tempo=15)
                d.update({k: lido[k] for k in d if isinstance(lido.get(k), str)})
                self._descoberta = d
            except rede.ErroRede:
                return d  # sem cache: tenta de novo na próxima vez
        return self._descoberta

    def _chave(self, kid):
        if kid not in self._jwks:
            try:
                dados = rede.json_get(self.descoberta()["jwks_uri"], tempo=15)
            except rede.ErroRede as ex:
                raise ErroLogin(f"não consegui baixar as chaves da OpenAI ({ex})") from ex
            self._jwks = {k.get("kid"): k for k in dados.get("keys", []) if k.get("kty") == "RSA"}
        chave = self._jwks.get(kid)
        if not chave:
            raise ErroLogin("ID token assinado com uma chave desconhecida")
        return _int(chave["n"]), _int(chave["e"])

    def validar_id_token(self, id_token, client_id, nonce, sub_esperado=None, folga=5):
        cab, c, ass, msg = decodificar_jwt(id_token)
        if cab.get("alg") != "RS256":
            raise ErroLogin("ID token com algoritmo inesperado")
        n, e = self._chave(cab.get("kid"))
        if not verificar_rs256(msg, ass, n, e):
            raise ErroLogin("assinatura do ID token inválida")
        agora = time.time()
        aud = c.get("aud")
        if c.get("iss") != self.descoberta()["issuer"]:
            raise ErroLogin("ID token de outro emissor")
        if client_id not in (aud if isinstance(aud, list) else [aud]):
            raise ErroLogin("ID token emitido para outro aplicativo")
        if not isinstance(c.get("exp"), (int, float)) or c["exp"] < agora - folga:
            raise ErroLogin("ID token vencido")
        if not isinstance(c.get("iat"), (int, float)):
            raise ErroLogin("ID token sem data de emissão")
        if not nonce or not hmac.compare_digest(str(c.get("nonce", "")), nonce):
            raise ErroLogin("nonce do ID token não confere")
        if not isinstance(c.get("sub"), str) or not c["sub"]:
            raise ErroLogin("ID token sem identificação da conta")
        if "sid" in c and (not isinstance(c["sid"], str) or not c["sid"].strip()):
            raise ErroLogin("ID token com sessão inválida")
        if sub_esperado and c["sub"] != sub_esperado:
            raise ErroLogin("você entrou com outra conta do ChatGPT; para trocar, use 'Usar outra conta'")
        return c

    # ── login ──
    def iniciar(self, redirect_uri, conta=None, nova=False, forcar_consentimento=False):
        """URL de autorização para abrir no navegador. conta: registro salvo (reautorização)."""
        if not redirect_uri.startswith("http://127.0.0.1:") or not redirect_uri.endswith("/auth/callback"):
            raise ErroLogin("o retorno do login precisa ser http://127.0.0.1:<porta>/auth/callback")
        conta = None if nova else (conta or self.contas.ativa())
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verificador = secrets.token_urlsafe(64)
        desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        q = {"response_type": "code", "redirect_uri": redirect_uri, "scope": ESCOPOS, "resource": RECURSO,
             "state": state, "nonce": nonce, "code_challenge_method": "S256", "code_challenge": desafio,
             "ext_agent_host_id": id_do_computador()}
        if conta:
            q["client_id"] = conta["client_id"]
            if conta.get("id_token"):
                q["id_token_hint"] = conta["id_token"]
            if conta.get("email"):
                q["login_hint"] = conta["email"]
        else:
            q["client_id"] = CLIENTE_DINAMICO
            q["agent_name_hint"] = NOME_APP
        if forcar_consentimento:
            q["prompt"] = "consent"
        agora = time.time()
        self.pendentes = {k: v for k, v in self.pendentes.items() if agora - v["criado"] < 900}
        self.pendentes[state] = {"verificador": verificador, "nonce": nonce, "redirect_uri": redirect_uri,
                                 "client_id": conta["client_id"] if conta else None,
                                 "sub": conta.get("subject") if conta else None, "criado": agora}
        return self.descoberta()["authorization_endpoint"] + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)

    def concluir(self, params):
        """Trata o retorno do navegador (?code=&state=&client_id=…) -> registro da conta salvo."""
        state = params.get("state") or ""
        tentativa = self.pendentes.pop(state, None)
        if not tentativa:
            raise ErroLogin("tentativa de login desconhecida ou expirada; comece de novo")
        if params.get("error"):
            if params["error"] == "access_denied":
                raise ErroLogin("você não autorizou o Prospecta a usar o plano do ChatGPT. Dá para tentar de novo "
                                "quando quiser.")
            raise ErroLogin(f"o login falhou: {params.get('error_description') or params['error']}")
        code = params.get("code")
        if not code:
            raise ErroLogin("o retorno do login não trouxe o código de autorização")
        cid = tentativa["client_id"]
        vindo = params.get("client_id")
        if cid is None:
            if not vindo or vindo == CLIENTE_DINAMICO:
                raise ErroLogin("o registro do app não foi concluído (sem client_id emitido); tente de novo")
            cid = vindo
        elif vindo and vindo != cid:
            raise ErroLogin("o retorno trouxe outro client_id; login recusado por segurança")
        tok = self._token({"grant_type": "authorization_code", "client_id": cid, "code": code,
                           "code_verifier": tentativa["verificador"], "redirect_uri": tentativa["redirect_uri"],
                           "resource": RECURSO})
        if not tok.get("id_token"):
            raise ErroLogin("a OpenAI não devolveu o ID token")
        claims = self.validar_id_token(tok["id_token"], cid, tentativa["nonce"], tentativa["sub"])
        reg = self._registro(cid, claims, tok)
        self.contas.salvar(reg)
        return reg

    def _registro(self, cid, claims, tok, anterior=None):
        anterior = anterior or {}
        escopos = (tok.get("scope") or " ".join(anterior.get("scopes") or [])).split()
        agora = time.time()
        return {"email": claims.get("email") if claims else anterior.get("email"),
                "issuer": self.descoberta()["issuer"], "subject": claims["sub"] if claims else anterior.get("subject"),
                "client_id": cid, "ext_agent_host_id": id_do_computador(),
                "id_token": tok.get("id_token") or anterior.get("id_token"),
                "access_token": tok["access_token"], "refresh_token": tok.get("refresh_token") or anterior.get("refresh_token"),
                "token_type": tok.get("token_type", "Bearer"), "expires_in": int(tok.get("expires_in") or 3600),
                "expira_em": agora + int(tok.get("expires_in") or 3600), "scopes": sorted(escopos),
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(agora)),
                "boas_vindas_vista": anterior.get("boas_vindas_vista", False)}

    def _token(self, form):
        corpo = urllib.parse.urlencode(form).encode()
        try:
            status, dados = rede.pedir(self.descoberta()["token_endpoint"], "POST", corpo,
                                       {"Content-Type": "application/x-www-form-urlencoded"}, tempo=30)
        except rede.ErroRede as ex:
            raise ErroLogin(f"não consegui falar com a OpenAI ({ex})") from ex
        try:
            r = json.loads(dados.decode("utf-8", "replace") or "{}")
        except ValueError:
            r = {}
        if status != 200:
            codigo = r.get("error") if isinstance(r.get("error"), str) else (r.get("error") or {}).get("code", "")
            erro = ErroLogin(f"a OpenAI recusou ({status} {codigo or ''}): "
                             f"{r.get('error_description') or r.get('detail') or ''}".strip())
            erro.codigo = codigo
            raise erro
        if not r.get("access_token"):
            raise ErroLogin("resposta de token sem access_token")
        return r

    # ── uso ──
    @staticmethod
    def plano_liberado(conta):
        return bool(conta) and ESCOPO_PLANO in (conta.get("scopes") or [])

    def token_valido(self, conta=None, margem=120):
        """access_token da conta ativa, renovado se estiver perto de vencer."""
        conta = conta or self.contas.ativa()
        if not conta or not conta.get("access_token"):
            raise ErroLogin("entre com o ChatGPT para usar o chat")
        if not self.plano_liberado(conta):
            raise ErroLogin("o uso do plano do ChatGPT não foi autorizado nesta conta")
        if conta.get("expira_em", 0) - time.time() > margem:
            return conta["access_token"]
        return self.renovar(conta)["access_token"]

    def renovar(self, conta):
        with self.trava_renovacao:  # um refresh por vez: o refresh token é rotativo
            atual = next((c for c in self.contas.todas() if c["client_id"] == conta["client_id"]), conta)
            if atual.get("expira_em", 0) - time.time() > 120 and atual.get("access_token") != conta.get("access_token"):
                return atual  # outro pedido já renovou
            if not atual.get("refresh_token"):
                raise ErroLogin("sessão do ChatGPT encerrada; entre de novo")
            try:
                tok = self._token({"grant_type": "refresh_token", "client_id": atual["client_id"],
                                   "refresh_token": atual["refresh_token"], "resource": RECURSO})
            except ErroLogin as ex:
                if getattr(ex, "codigo", "") in ("invalid_grant", "invalid_refresh_token", "token_expired",
                                                 "refresh_token_expired", "refresh_token_invalidated",
                                                 "refresh_token_reused"):
                    self._limpar_tokens(atual)
                    raise ErroLogin("sua sessão do ChatGPT expirou; entre de novo") from ex
                raise
            novo = self._registro(atual["client_id"], None, tok, anterior=atual)
            self.contas.salvar(novo, ativar=False)
            return novo

    def _limpar_tokens(self, conta):
        limpo = dict(conta, access_token="", refresh_token="", id_token=conta.get("id_token", ""), expira_em=0)
        self.contas.salvar(limpo, ativar=False)

    def sair(self):
        """Revoga a sessão renovável e apaga os tokens locais (mantém o registro para entrar de novo)."""
        conta = self.contas.ativa()
        if not conta:
            return ""
        aviso = ""
        revogar = self.descoberta().get("revocation_endpoint")
        if conta.get("refresh_token") and not revogar:
            aviso = ("Não consegui confirmar o encerramento da sessão na OpenAI. Se quiser, desconecte o "
                     "Prospecta em ChatGPT → Configurações.")
        elif conta.get("refresh_token"):
            form = urllib.parse.urlencode({"token": conta["refresh_token"], "token_type_hint": "refresh_token",
                                           "client_id": conta["client_id"]}).encode()
            ok = False
            for tentativa in range(3):
                try:
                    status, _ = rede.pedir(revogar, "POST", form,
                                           {"Content-Type": "application/x-www-form-urlencoded"}, tempo=15)
                    if status == 200:
                        ok = True
                        break
                    if status < 500:
                        break
                except rede.ErroRede:
                    pass
                time.sleep(1 + 2 * tentativa)
            if not ok:
                aviso = ("Não consegui confirmar o encerramento da sessão na OpenAI. Se quiser, desconecte o "
                         "Prospecta em ChatGPT → Configurações.")
        limpo = dict(conta, access_token="", refresh_token="", id_token="", expira_em=0)
        self.contas.salvar(limpo, ativar=True)
        return aviso

    def marcar_boas_vindas(self):
        conta = self.contas.ativa()
        if conta:
            self.contas.salvar(dict(conta, boas_vindas_vista=True), ativar=True)
