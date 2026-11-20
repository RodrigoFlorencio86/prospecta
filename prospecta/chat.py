"""Chat do painel: conversa com um modelo da OpenAI usando o plano do ChatGPT do usuário, com as
ferramentas do Prospecta (buscar, filtrar, marcar, rota, mensagens, exportar).

Regras do uso do plano (prévia da OpenAI): POST /v1/responses com store=false e stream=true, histórico
enviado inteiro em `input`, instruções em `instructions`, ferramentas de função agrupadas num
namespace, sem campos não suportados (temperature, max_output_tokens, previous_response_id…)."""
import json
import threading
import time
import uuid

from . import rede
from .chatgpt import GERENCIAR_USO, Autenticador, ErroLogin
from .ferramentas import FERRAMENTAS, chamar, schema

API = "https://api.openai.com/v1"
MAX_RODADAS = 10
MAX_SAIDA_FERRAMENTA = 60_000  # ~100 empresas resumidas cabem inteiras
MAX_ITENS_HISTORICO = 80
SO_FORA_DO_PAINEL = {"abrir_painel"}
COM_BUSCA = {"consultar_prospects", "planejar_rota", "exportar", "detalhar_prospect"}  # o chat já está dentro do painel
FERRAMENTAS_QUE_MUDAM = {"iniciar_busca", "cancelar_busca", "marcar_prospect", "configurar", "exportar"}


class ErroChat(RuntimeError):
    def __init__(self, mensagem, tipo="erro", status=None, codigo=None):
        super().__init__(mensagem)
        self.tipo, self.status, self.codigo = tipo, status, codigo


def namespace_ferramentas():
    return [{"type": "namespace", "name": "prospecta",
             "description": "Ferramentas do Prospecta: buscar empresas num raio, consultar e acompanhar prospects.",
             "tools": [{"type": "function", "name": f["nome"], "description": f["descricao"], "parameters": schema(f)}
                       for f in FERRAMENTAS if f["nome"] not in SO_FORA_DO_PAINEL]}]


def instrucoes(config, busca_aberta=None):
    hoje = time.strftime("%d/%m/%Y")
    quem = ", ".join(x for x in (config.get("meu_nome"), config.get("minha_empresa")) if x) or "não informado"
    base = (config.get("base") or {}).get("descricao") or "não informada (rotas saem do endereço da busca)"
    return f"""Você é o assistente do Prospecta, que ajuda um profissional autônomo brasileiro a encontrar e \
organizar empresas que podem contratar o serviço dele (prospecção B2B) perto de um endereço. Hoje é {hoje}.
Usuário: {quem}. Endereço-base das rotas: {base}. Raio padrão: {config.get('raio_km')} km.
{_aberta(busca_aberta)}

Como trabalhar:
- Fale em português do Brasil, simples e direto, sem jargão. Respostas curtas; use listas quando ajudar.
- Use as ferramentas para tudo que envolve dados; nunca invente empresas, telefones ou números.
- Antes de iniciar_busca, confirme endereço, raio (sugira 1 a 5 km) e o que procurar: um perfil pronto \
(listar_perfis) ou 'alvos' sob medida (5 a 12 tipos de negócio como digitados no Google Maps, no singular) \
com 'sinais' (palavras de necessidade nas avaliações). Informe a estimativa de tempo. Uma busca por vez.
- Buscas rodam em segundo plano por minutos; o painel mostra o andamento. Quando o usuário perguntar, use \
estado_busca. Com a busca pronta, mostre um resumo e os melhores prospects (consultar_prospects).
- Para rotas use planejar_rota; para abordagem, mensagem_whatsapp (mostre o texto e o link). Os links só abrem \
a conversa: você nunca envia mensagens nem sugere disparos em massa.
- Marque status e observações quando o usuário contar o resultado de um contato (marcar_prospect).
- LGPD: dados públicos de empresas, para contato comercial; o usuário deve se identificar e respeitar quem \
pedir para não ser contatado. Não colete dados pessoais além do necessário.
- Perguntas sobre "essa busca", "os resultados" ou empresas na tela referem-se à busca aberta no painel. Para \
responder, leia os dados com consultar_prospects. Para um tipo de negócio, use o filtro categoria com o nome EXATO \
de categorias_da_busca (vem em toda resposta da ferramenta; não invente nomes). Para julgar algo que a categoria não \
diz (ex.: "parece fundo de venture capital?"), leia sem filtros (limite=100, todas as páginas) e julgue por nome, \
categoria e site. Deixe claro quando é uma inferência.
- Ao citar um prospect, use o nome e a distância; não mostre a 'chave' ao usuário."""


def _aberta(b):
    if not b:
        return "Nenhuma busca aberta no painel agora."
    return (f"Busca aberta no painel agora: busca_id={b.get('busca_id')} ({b.get('servico')}, {b.get('total')} "
            f"empresas, até {b.get('raio_km')} km de {b.get('local')}).")


def _erro_http(status, corpo):
    try:
        d = json.loads(corpo.decode("utf-8", "replace") or "{}")
    except ValueError:
        d = {}
    err = d.get("error") if isinstance(d.get("error"), dict) else {}
    codigo, msg = err.get("code") or "", err.get("message") or d.get("detail") or ""
    return _traduzir(status, codigo, msg, err.get("param"))


def _traduzir(status, codigo, msg, param=None):
    codigo = codigo or ""
    if codigo == "subscription_sharing_usage_limit_exceeded":
        return ErroChat("Você chegou ao limite de uso do seu plano do ChatGPT (ou ao limite definido para o "
                        "Prospecta).", "limite", status, codigo)
    if codigo == "subscription_sharing_user_not_eligible":
        return ErroChat("Seu plano ou conta do ChatGPT não permite usar o plano em outros apps (é preciso Go, "
                        "Plus, Pro ou Business).", "nao_elegivel", status, codigo)
    if codigo in ("subscription_sharing_usage_unavailable", "subscription_sharing_user_unavailable") or status == 503:
        return ErroChat("O ChatGPT não conseguiu verificar seu uso agora. Tente de novo em instantes.",
                        "temporario", status, codigo)
    if codigo == "subscription_sharing_invalid_user" or status == 401:
        return ErroChat("Sua sessão do ChatGPT não foi aceita. Entre de novo.", "sessao", status, codigo)
    if codigo == "subscription_sharing_unsupported_capability":
        return ErroChat(f"O modelo escolhido não aceita um recurso usado pelo chat ({param or msg}). Tente outro "
                        "modelo.", "modelo", status, codigo)
    if status == 403:
        return ErroChat(f"A OpenAI recusou o pedido ({msg or codigo or 'permissão'}).", "permissao", status, codigo)
    return ErroChat(f"A OpenAI respondeu com erro {status or ''} {codigo} {msg}".strip(), "erro", status, codigo)


class ClienteResponses:
    def __init__(self, base=API):
        self.base = base.rstrip("/")

    def modelos(self, token):
        status, dados = rede.pedir(f"{self.base}/models", cabecalhos={"Authorization": f"Bearer {token}"}, tempo=20)
        if status != 200:
            raise _erro_http(status, dados)
        d = json.loads(dados.decode("utf-8", "replace"))
        lista = d.get("models") if isinstance(d.get("models"), list) else d.get("data") or []
        return [{"slug": m.get("slug") or m.get("id"), "nome": m.get("display_name") or m.get("slug") or m.get("id")}
                for m in lista if m.get("visibility", "list") == "list" and (m.get("slug") or m.get("id"))]

    def responder(self, token, corpo, ao_texto=None):
        """POST /responses em streaming -> objeto response de response.completed."""
        import urllib.error
        import urllib.request
        req = urllib.request.Request(f"{self.base}/responses", data=json.dumps(corpo).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                              "Accept": "text/event-stream", "User-Agent": rede.AGENTE})
        try:
            r = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            raise _erro_http(e.code, e.read(200_000)) from None
        except (urllib.error.URLError, OSError) as e:
            raise ErroChat(f"Não consegui falar com a OpenAI ({getattr(e, 'reason', e)}).", "rede") from None
        final = None
        with r:
            for evento in _eventos_sse(r):
                tipo = evento.get("type", "")
                if tipo == "response.output_text.delta" and ao_texto:
                    ao_texto(evento.get("delta", ""))
                elif tipo == "response.completed":
                    final = evento.get("response") or {}
                elif tipo == "response.failed":
                    err = ((evento.get("response") or {}).get("error")) or {}
                    raise _traduzir(None, err.get("code"), err.get("message"), err.get("param"))
                elif tipo == "response.incomplete":
                    final = evento.get("response") or {}
                    final["_incompleta"] = True
                elif tipo == "error":
                    raise _traduzir(None, evento.get("code"), evento.get("message"), evento.get("param"))
        if final is None:
            raise ErroChat("A resposta da OpenAI foi interrompida antes de terminar. Tente de novo.", "rede")
        return final


def _eventos_sse(resposta):
    dados = []
    for bruto in resposta:
        linha = bruto.decode("utf-8", "replace").rstrip("\r\n")
        if not linha:
            if dados:
                texto = "\n".join(dados)
                dados = []
                if texto.strip() == "[DONE]":
                    continue
                try:
                    yield json.loads(texto)
                except ValueError:
                    continue
            continue
        if linha.startswith("data:"):
            dados.append(linha[5:].lstrip())
    if dados:
        try:
            yield json.loads("\n".join(dados))
        except ValueError:
            pass


class Conversa:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.historico = []
        self.trava = threading.Lock()
        self.criada = time.time()


class AgenteChat:
    def __init__(self, app, autenticador=None, cliente=None):
        self.app = app
        self.auth = autenticador or Autenticador()
        self.cliente = cliente or ClienteResponses()
        self.conversas = {}

    def conversa(self, cid=None):
        if cid and cid in self.conversas:
            return self.conversas[cid]
        c = Conversa()
        self.conversas = {k: v for k, v in self.conversas.items() if time.time() - v.criada < 86400}
        self.conversas[c.id] = c
        return c

    def modelos(self):
        try:
            return self.cliente.modelos(self.auth.token_valido())
        except ErroLogin as ex:
            raise ErroChat(str(ex), "sessao") from ex

    def enviar(self, conversa, texto, modelo, busca_aberta=None):
        """Uma mensagem do usuário -> {"resposta", "acoes", "atualizar"}."""
        if not modelo:
            raise ErroChat("Escolha um modelo.", "modelo")
        with conversa.trava:
            conversa.historico.append({"role": "user", "content": texto[:8000]})
            acoes, atualizar = [], False
            for _ in range(MAX_RODADAS):
                try:
                    token = self.auth.token_valido()
                except ErroLogin as ex:
                    self._desfazer(conversa)
                    raise ErroChat(str(ex), "sessao") from ex
                corpo = {"model": modelo, "instructions": instrucoes(self.app.configuracao(), self._busca_info(busca_aberta)),
                         "input": conversa.historico, "tools": namespace_ferramentas(), "store": False, "stream": True}
                try:
                    resp = self.cliente.responder(token, corpo)
                except ErroChat:
                    self._desfazer(conversa)
                    raise
                saida = [i for i in resp.get("output") or [] if isinstance(i, dict)]
                conversa.historico.extend(saida)
                chamadas = [i for i in saida if i.get("type") == "function_call"]
                if not chamadas:
                    texto_final = _texto(saida) or ("(a resposta veio incompleta)" if resp.get("_incompleta") else "")
                    self._aparar(conversa)
                    return {"resposta": texto_final, "acoes": acoes, "atualizar": atualizar}
                for ch in chamadas:
                    nome = ch.get("name", "")
                    try:
                        args = json.loads(ch.get("arguments") or "{}")
                    except ValueError:
                        args = None
                    if busca_aberta and isinstance(args, dict) and nome in COM_BUSCA and not args.get("busca_id"):
                        args["busca_id"] = int(busca_aberta)  # "essa busca" = a que está na tela
                    resultado, erro = chamar(self.app, nome, args)
                    saida_txt = _caber(resultado)
                    conversa.historico.append({"type": "function_call_output", "call_id": ch.get("call_id"),
                                               "output": saida_txt})
                    acoes.append({"ferramenta": nome, "erro": erro, "resumo": _resumo_acao(nome, args, resultado, erro)})
                    atualizar = atualizar or (nome in FERRAMENTAS_QUE_MUDAM and not erro)
            self._aparar(conversa)
            return {"resposta": "Parei aqui para não gastar demais seu plano. Quer que eu continue?",
                    "acoes": acoes, "atualizar": atualizar}

    def _busca_info(self, busca_id):
        if not busca_id:
            return None
        try:
            b = self.app.db.busca(0, int(busca_id))
        except (TypeError, ValueError):
            return None
        if not b:
            return None
        return {"busca_id": b["id"], "servico": b["perfil"], "total": len(b["itens"]), "raio_km": b["raio_km"],
                "local": b["local"].get("descricao", "")}

    @staticmethod
    def _desfazer(conversa):
        """Tira do histórico a última mensagem do usuário que não teve resposta."""
        while conversa.historico:
            item = conversa.historico.pop()
            if item.get("role") == "user":
                break

    @staticmethod
    def _aparar(conversa):
        h = conversa.historico
        if len(h) <= MAX_ITENS_HISTORICO:
            return
        corte = len(h) - MAX_ITENS_HISTORICO
        while corte < len(h) and h[corte].get("role") != "user":  # começa sempre numa mensagem do usuário
            corte += 1
        del h[:corte]


def _caber(resultado):
    """JSON do resultado dentro do limite. Listas de empresas perdem itens do fim (nunca um corte no meio do
    JSON), com aviso para pedir a próxima página."""
    txt = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(txt) <= MAX_SAIDA_FERRAMENTA:
        return txt
    if isinstance(resultado, dict) and isinstance(resultado.get("prospects"), list):
        r = dict(resultado)
        lista = list(r["prospects"])
        while lista and len(txt) > MAX_SAIDA_FERRAMENTA:
            lista = lista[:max(0, len(lista) - max(1, len(lista) // 10))]
            r["prospects"] = lista
            r["aviso"] = f"lista cortada em {len(lista)} itens por tamanho; peça limite menor ou a próxima página"
            txt = json.dumps(r, ensure_ascii=False, default=str)
        return txt
    return json.dumps({"erro": "resultado grande demais; use filtros ou limite menor"}, ensure_ascii=False)


def _texto(itens):
    partes = []
    for i in itens:
        if i.get("type") == "message":
            for c in i.get("content") or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    partes.append(c["text"])
    return "\n\n".join(partes).strip()


def _resumo_acao(nome, args, resultado, erro):
    if erro:
        return f"{nome}: {(resultado or {}).get('erro', 'erro')}"
    r = resultado if isinstance(resultado, dict) else {}
    if nome == "iniciar_busca":
        return f"🔎 Busca iniciada: {r.get('local', '')[:50]} · ~{r.get('estimativa_min')} min"
    if nome == "consultar_prospects":
        legivel = lambda v: "sim" if v is True else "não" if v is False else v  # noqa: E731
        filtros = ", ".join(f"{k}: {legivel(v)}" for k, v in (r.get("filtros_aplicados") or {}).items())
        return (f"📋 {r.get('total_filtrado')} de {r.get('total_na_busca')} empresas"
                + (f" ({filtros})" if filtros else " (sem filtros)")
                + (f", página {r.get('pagina')} de {r.get('paginas')}" if (r.get("paginas") or 1) > 1 else ""))
    if nome == "marcar_prospect":
        return f"✅ {r.get('nome')}: {r.get('status') or 'sem status'}"
    if nome == "planejar_rota":
        return f"🗺️ Rota com {len(r.get('paradas') or [])} paradas, {r.get('km')} km"
    if nome == "exportar":
        return "📄 Relatório e planilha gerados"
    if nome == "estado_busca":
        return f"⏳ Busca {r.get('estado')} ({r.get('progresso_pct')}%)"
    return f"• {nome}"


GERENCIAR = GERENCIAR_USO
