"""Login com ChatGPT, chat com ferramentas, painel HTTP, MCP e trabalhador de buscas, sem internet."""
import io
import json
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock

from prospecta import chat, chatgpt, geo, mcp_servidor, painel
from prospecta.config import Config
from prospecta.ferramentas import ErroFerramenta, Prospecta, TravaArquivo, chamar
from tests.apoio import CENTRO, GeoFalso, MotorFalso, linha
from tests.openai_falsa import OpenAIFalsa

SEM_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}), type("SemRedir", (urllib.request.HTTPRedirectHandler,), {
    "redirect_request": lambda self, *a, **k: None})())


def pedir(url, metodo="GET", corpo=None, cab=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo, headers=dict({"Content-Type": "application/json"}, **(cab or {})))
    try:
        with SEM_PROXY.open(req, timeout=20) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def criar_app(tmp, linhas=None):
    cfg = Config(pasta_dados=tmp / "dados", pasta_resultados=tmp / "res")
    rows = linhas or [linha(f"Lugar {i}", *geo.deslocar(CENTRO.lat, CENTRO.lon, 150 * i, 20), phone=f"19 99999-20{i:02d}",
                            review_count=str(500 - i * 30)) for i in range(8)]
    app = Prospecta(cfg, motor=MotorFalso([rows] * 30), geocoder=GeoFalso(), ligar_motor=False)
    app.disparar = lambda: threading.Thread(target=app.trabalhar_fila, kwargs={"ocioso": 0.05}, daemon=True).start()
    return app


def esperar_tarefa(app, tid, limite=20):
    fim = time.time() + limite
    while time.time() < fim:
        t = app.estado_busca(tid)
        if t["estado"] in ("ok", "erro", "cancelada"):
            return t
        time.sleep(0.05)
    raise AssertionError("busca não terminou")


class BaseOpenAI(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"PROSPECTA_CONFIG": str(self.tmp / "cfg")})
        self.env.start()
        self.oa = OpenAIFalsa()
        self.auth = chatgpt.Autenticador(chatgpt.Contas(), emissor_url=self.oa.url)

    def tearDown(self):
        self.env.stop()
        self.oa.fechar()

    def login(self, redirect="http://127.0.0.1:5555/auth/callback", **k):
        url = self.auth.iniciar(redirect, **k)
        status, cab, _ = pedir(url)
        self.assertEqual(status, 302)
        volta = urllib.parse.urlsplit(cab["Location"])
        return self.auth.concluir(dict(urllib.parse.parse_qsl(volta.query)))


class LoginTest(BaseOpenAI):
    def test_registro_dinamico_e_credenciais_protegidas(self):
        conta = self.login()
        a = self.oa.autorizacoes[0]
        self.assertEqual((a["client_id"], a["agent_name_hint"]), ("dynamic_agent_client", "Prospecta"))
        self.assertIn("chatgpt.tokens.use.direct", a["scope"].split())
        self.assertEqual((conta["client_id"], conta["email"], conta["subject"]), ("oaiapp_teste123", "ana@exemplo.com", "usuario-1"))
        self.assertTrue(chatgpt.Autenticador.plano_liberado(conta))
        arq = Path(os.environ["PROSPECTA_CONFIG"]) / "contas.json"
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(arq.stat().st_mode), 0o600)
        host = json.loads((arq.parent / "host.json").read_text())["ext_agent_host_id"]
        self.assertEqual(a["ext_agent_host_id"], host)
        # reautorização reusa o client_id emitido, sem agent_name_hint, com id_token_hint
        self.login()
        b = self.oa.autorizacoes[1]
        self.assertEqual(b["client_id"], "oaiapp_teste123")
        self.assertIn("id_token_hint", b)
        self.assertEqual(b["ext_agent_host_id"], host)

    def test_recusas(self):
        url = self.auth.iniciar("http://127.0.0.1:5555/auth/callback")
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        with self.assertRaises(chatgpt.ErroLogin):
            self.auth.concluir({"state": "outro", "code": "x"})
        with self.assertRaisesRegex(chatgpt.ErroLogin, "não autorizou"):
            self.auth.concluir({"state": state, "error": "access_denied"})
        with self.assertRaises(chatgpt.ErroLogin):
            self.auth.iniciar("http://localhost:5555/auth/callback")  # só 127.0.0.1

    def test_nonce_errado_e_assinatura_falsa(self):
        url = self.auth.iniciar("http://127.0.0.1:5555/auth/callback")
        _, cab, _ = pedir(url)
        volta = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(cab["Location"]).query))
        self.auth.pendentes[volta["state"]]["nonce"] = "outro-nonce"
        with self.assertRaisesRegex(chatgpt.ErroLogin, "nonce"):
            self.auth.concluir(volta)
        token = self.oa._id_token("oaiapp_teste123", "n")
        cab_, corpo, ass = token.split(".")
        falso = cab_ + "." + corpo[:-2] + "AA" + "." + ass
        with self.assertRaises(chatgpt.ErroLogin):
            self.auth.validar_id_token(falso, "oaiapp_teste123", "n")
        with self.assertRaisesRegex(chatgpt.ErroLogin, "outro aplicativo"):
            self.auth.validar_id_token(token, "oaiapp_outro", "n")

    def test_plano_recusado(self):
        self.oa.recusar_plano = True
        conta = self.login()
        self.assertFalse(chatgpt.Autenticador.plano_liberado(conta))
        with self.assertRaisesRegex(chatgpt.ErroLogin, "não foi autorizado"):
            self.auth.token_valido()
        self.oa.recusar_plano = False
        self.login(forcar_consentimento=True)
        self.assertEqual(self.oa.autorizacoes[-1]["prompt"], "consent")
        self.assertTrue(chatgpt.Autenticador.plano_liberado(self.auth.contas.ativa()))

    def test_renovacao_e_saida(self):
        conta = self.login()
        self.auth.contas.salvar(dict(conta, expira_em=time.time() + 30))
        self.assertEqual(self.auth.token_valido(), "at-renovado-1")
        nova = self.auth.contas.ativa()
        self.assertEqual(nova["refresh_token"], "rt-2")
        self.assertEqual(nova["id_token"], conta["id_token"])  # mantém o id_token para id_token_hint
        self.assertEqual(self.auth.sair(), "")
        self.assertEqual(self.oa.revogados[-1], {"token": "rt-2", "token_type_hint": "refresh_token",
                                                 "client_id": "oaiapp_teste123"})
        depois = self.auth.contas.ativa()
        self.assertEqual((depois["access_token"], depois["refresh_token"], depois["client_id"]), ("", "", "oaiapp_teste123"))
        with self.assertRaises(chatgpt.ErroLogin):
            self.auth.token_valido()

    def test_refresh_invalido_pede_login(self):
        conta = self.login()
        self.auth.contas.salvar(dict(conta, expira_em=0, refresh_token="rt-morto"))
        with self.assertRaisesRegex(chatgpt.ErroLogin, "entre de novo"):
            self.auth.token_valido()
        self.assertEqual(self.auth.contas.ativa()["refresh_token"], "")


class ChatTest(BaseOpenAI):
    def setUp(self):
        super().setUp()
        self.app = criar_app(self.tmp)
        tid = self.app.iniciar_busca("Rua A, 1", raio_km=1.5, perfil="limpeza")["tarefa_id"]
        self.assertEqual(esperar_tarefa(self.app, tid)["estado"], "ok")
        self.login()
        self.agente = chat.AgenteChat(self.app, self.auth, chat.ClienteResponses(self.oa.url + "/v1"))

    def test_ferramenta_e_resposta(self):
        self.assertEqual(self.agente.modelos(), [{"slug": "gpt-teste", "nome": "GPT Teste"}])
        c = self.agente.conversa()
        r = self.agente.enviar(c, "quais os melhores?", "gpt-teste")
        self.assertRegex(r["resposta"], r"Achei \d+ prospects A")
        self.assertEqual([a["ferramenta"] for a in r["acoes"]], ["consultar_prospects"])
        segundo = self.oa.pedidos_responses[-1]
        tipos = [i.get("type") or i.get("role") for i in segundo["input"]]
        self.assertEqual(tipos, ["user", "reasoning", "function_call", "function_call_output"])  # tudo reenviado
        self.assertIn("Você é o assistente do Prospecta", segundo["instructions"])
        self.assertEqual({t["name"] for t in segundo["tools"][0]["tools"]} >= {"iniciar_busca", "planejar_rota"}, True)
        # segunda pergunta mantém o histórico
        self.agente.enviar(c, "e agora?", "gpt-teste")
        self.assertEqual(self.oa.pedidos_responses[-2]["input"][0], {"role": "user", "content": "quais os melhores?"})

    def test_conversa_sobre_a_busca_aberta(self):
        """O chat sabe qual busca está na tela e a usa quando o modelo não diz qual."""
        bid = self.app.db.busca(0)["id"]
        tid = self.app.iniciar_busca("Rua B", raio_km=1, perfil="ti")["tarefa_id"]  # outra busca, mais nova
        esperar_tarefa(self.app, tid)
        self.assertNotEqual(self.app.db.busca(0)["id"], bid)
        vistos = []
        original = self.app.consultar_prospects
        self.app.consultar_prospects = lambda **k: (vistos.append(k), original(**k))[1]
        r = self.agente.enviar(self.agente.conversa(), "quais dessas parecem fundos?", "gpt-teste", busca_aberta=bid)
        self.assertEqual(vistos[0]["busca_id"], bid)
        self.assertIn(f"busca_id={bid}", self.oa.pedidos_responses[0]["instructions"])
        self.assertRegex(r["resposta"], r"Achei \d+ prospects A")

    def test_conversas_ficam_salvas_e_presas_a_busca(self):
        bid = self.app.db.busca(0)["id"]
        c = self.agente.conversa()
        r = self.agente.enviar(c, "quais os melhores?", "gpt-teste", busca_aberta=bid)
        self.assertEqual(r["conversa"], {"id": c.id, "titulo": "quais os melhores?", "busca_id": bid})
        # outra busca aberta na tela não muda o assunto de uma conversa que já tem busca
        tid = self.app.iniciar_busca("Rua B", raio_km=1, perfil="ti")["tarefa_id"]
        outra = esperar_tarefa(self.app, tid)["busca_id"]
        self.agente.enviar(c, "e os de WhatsApp?", "gpt-teste", busca_aberta=outra)
        self.assertEqual(c.busca_id, bid)
        # o painel reiniciou: a conversa volta do banco, com histórico e mensagens
        novo = chat.AgenteChat(self.app, self.auth, chat.ClienteResponses(self.oa.url + "/v1"))
        lista = novo.listar()
        self.assertEqual(len(lista), 1)
        self.assertEqual((lista[0]["id"], lista[0]["titulo"], lista[0]["busca_id"], lista[0]["mensagens"]),
                         (c.id, "quais os melhores?", bid, len(c.mensagens)))
        self.assertRegex(lista[0]["busca"], r"· 8 empresas$")
        volta = novo.conversa(c.id)
        self.assertEqual([m["tipo"] for m in volta.mensagens][:4], ["eu", "acao", "ia", "eu"])
        self.assertEqual(volta.mensagens, c.mensagens)
        self.assertEqual(volta.historico, c.historico)
        novo.enviar(volta, "e agora?", "gpt-teste")
        self.assertEqual(self.oa.pedidos_responses[-2]["input"][0], {"role": "user", "content": "quais os melhores?"})
        self.assertIn(f"busca_id={bid}", self.oa.pedidos_responses[-1]["instructions"])
        # conversa geral adota a busca aberta na primeira pergunta; id desconhecido vira conversa nova
        g = novo.conversa("f" * 32)
        self.assertNotEqual(g.id, "f" * 32)
        self.assertTrue(novo.apagar(c.id))
        self.assertEqual(novo.listar(), [])
        self.assertFalse(novo.apagar(c.id))

    def test_limite_de_uso(self):
        self.oa.limite = True
        c = self.agente.conversa()
        with self.assertRaises(chat.ErroChat) as ctx:
            self.agente.enviar(c, "oi", "gpt-teste")
        self.assertEqual(ctx.exception.tipo, "limite")
        self.assertEqual(c.historico, [])  # a pergunta sem resposta sai do histórico

    def test_sessao_invalida(self):
        conta = self.auth.contas.ativa()
        self.auth.contas.salvar(dict(conta, access_token="xx-invalido", expira_em=time.time() + 3600))
        with self.assertRaises(chat.ErroChat) as ctx:
            self.agente.enviar(self.agente.conversa(), "oi", "gpt-teste")
        self.assertEqual(ctx.exception.tipo, "sessao")


class CaberTest(unittest.TestCase):
    def test_lista_grande_e_cortada_por_itens(self):
        r = {"total_filtrado": 500, "prospects": [{"nome": "x" * 300, "n": i} for i in range(500)]}
        txt = chat._caber(r)
        d = json.loads(txt)  # sempre JSON válido
        self.assertLessEqual(len(txt), chat.MAX_SAIDA_FERRAMENTA)
        self.assertLess(len(d["prospects"]), 500)
        self.assertIn("próxima página", d["aviso"])
        self.assertEqual(json.loads(chat._caber({"ok": 1})), {"ok": 1})


class FerramentasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.app = criar_app(self.tmp)

    def test_fluxo_completo(self):
        r = self.app.iniciar_busca("Rua A, 1", raio_km=1.5, alvos=["padaria", "hotel"], servico="Fornos",
                                   sinais=["forno"])
        t = esperar_tarefa(self.app, r["tarefa_id"])
        self.assertEqual(t["estado"], "ok")
        bid = t["busca_id"]
        lista = self.app.consultar_prospects(prioridade="A", limite=3)
        self.assertLessEqual(len(lista["prospects"]), 3)
        chave = self.app.consultar_prospects(ordenar="distancia")["prospects"][0]["chave"]
        self.app.marcar_prospect(chave, "interessado", "ligar segunda")
        self.assertEqual(self.app.consultar_prospects(status="interessado")["total_filtrado"], 1)
        det = self.app.detalhar_prospect(chave)
        self.assertTrue(det["link_whatsapp"].startswith("https://wa.me/55"))
        rota = self.app.planejar_rota(quantidade=4)
        self.assertEqual(len(rota["paradas"]), 4)
        exp = self.app.exportar(bid)
        self.assertTrue(Path(exp["arquivos"]["relatorio"]).is_file())
        self.assertEqual(self.app.resumo_funil()["em_andamento"][0]["observacao"], "ligar segunda")
        self.assertEqual(self.app.busca_completa(bid)["servico"], "Fornos")

    def test_andamento_detalhado(self):
        """O painel acompanha a busca área por área: empresas achadas, categorias, etapas e tempo."""
        r = self.app.iniciar_busca("Rua A, 1", raio_km=3, perfil="limpeza")
        self.assertEqual(esperar_tarefa(self.app, r["tarefa_id"])["estado"], "ok")
        a = self.app.andamento_busca(r["tarefa_id"])
        x = a["detalhe"]
        n = len(x["areas"])
        self.assertGreater(n, 1)
        self.assertEqual(n, r["areas"])
        self.assertEqual({ar["estado"] for ar in x["areas"]}, {"ok"})
        self.assertEqual(x["etapa"], "fim")
        self.assertEqual(x["categorias"], {"Padaria": 8})  # as mesmas 8 em todas as áreas: contadas uma vez
        self.assertEqual(len(x["lugares"]), 8)
        self.assertEqual(x["brutos"], 8 * n)
        self.assertEqual(sum(ar["novos"] for ar in x["areas"]), 8)
        textos = [e[1] for e in x["eventos"]]
        self.assertIn("Preparando o motor de busca", textos)
        self.assertTrue(any(tx.startswith("Pronto: 8 prospects") for tx in textos))
        self.assertEqual((a["servico"], a["raio_km"], a["estado"], a["restante_s"]), ("Limpeza e conservação", 3, "ok", None))
        self.assertGreater(x["raio_area_m"], 0)
        self.assertNotIn("detalhe", self.app.db.tarefas(0)[0])  # a lista continua leve
        with self.assertRaises(ErroFerramenta):
            self.app.andamento_busca(999)

    def test_andamento_quando_falha(self):
        from prospecta.motor import ErroMotor

        class MotorQuebrado(MotorFalso):
            def executar(self, jid, cancelar=None, progresso=None, espera_max=0):
                raise ErroMotor("o motor caiu")
        self.app.motor = MotorQuebrado()
        r = self.app.iniciar_busca("Rua A, 1", raio_km=3, perfil="limpeza")
        self.assertEqual(esperar_tarefa(self.app, r["tarefa_id"])["estado"], "erro")
        x = self.app.andamento_busca(r["tarefa_id"])["detalhe"]
        self.assertEqual((x["etapa"], x["parou_em"]), ("erro", "areas"))
        self.assertEqual([ar["estado"] for ar in x["areas"][:2]], ["falhou", "falhou"])
        self.assertIn("Erro: o motor caiu", x["eventos"][-1][1])

    def test_banco_antigo_ganha_coluna_de_detalhe(self):
        import sqlite3
        from prospecta.banco import Banco
        caminho = self.tmp / "antigo.db"
        con = sqlite3.connect(caminho)
        con.execute("CREATE TABLE tarefas (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL, criada REAL NOT NULL,"
                    " atualizada REAL NOT NULL, estado TEXT NOT NULL, parametros TEXT NOT NULL, descricao TEXT DEFAULT '',"
                    " progresso REAL DEFAULT 0, lugares INTEGER DEFAULT 0, mensagem TEXT DEFAULT '', busca_id INTEGER, dono TEXT DEFAULT '')")
        con.execute("INSERT INTO tarefas (chat_id, criada, atualizada, estado, parametros) VALUES (0, 1, 1, 'ok', '{}')")
        con.commit()
        con.close()
        db = Banco(caminho)
        self.assertEqual(db.tarefa(1)["detalhe"], {})

    def test_campos_vazios_nao_filtram(self):
        """Modelos mandam todos os campos opcionais com "", 0 ou false: isso não pode zerar a consulta."""
        tid = self.app.iniciar_busca("Rua A", raio_km=1.5, perfil="limpeza")["tarefa_id"]
        esperar_tarefa(self.app, tid)
        total = len(self.app.db.busca(0)["itens"])
        vazios = {"busca_id": 0, "prioridade": "", "whatsapp": "qualquer", "email": "qualquer", "texto": "",
                  "bairro": "", "status": "qualquer", "max_km": 0, "min_avaliacoes": 0, "ordenar": "nota",
                  "limite": 0, "pagina": 0, "com_whatsapp": None}
        r, erro = chamar(self.app, "consultar_prospects", vazios)
        self.assertFalse(erro)
        self.assertEqual((r["total_filtrado"], r["filtros_aplicados"]), (total, {}))
        r, _ = chamar(self.app, "consultar_prospects", {"whatsapp": "nao"})
        self.assertEqual(r["total_filtrado"], 0)  # todas as empresas do teste têm celular
        self.assertIn("dica", r)
        r, _ = chamar(self.app, "consultar_prospects", {"whatsapp": "sim", "status": "sem_status", "max_km": 0.5})
        self.assertEqual(r["filtros_aplicados"], {"whatsapp": True, "max_km": 0.5, "status": "sem_status"})
        self.assertTrue(all(p["distancia_km"] <= 0.5 for p in r["prospects"]))

    def test_categorias_exatas_e_texto_tolerante(self):
        rows = [linha("Biotec Nutri", *geo.deslocar(CENTRO.lat, CENTRO.lon, 100, 0), category="Distribuidora de Produtos Farmacêuticos"),
                linha("SAR Medicamentos", *geo.deslocar(CENTRO.lat, CENTRO.lon, 200, 0), category="Empresa farmacêutica"),
                linha("Oncoprod", *geo.deslocar(CENTRO.lat, CENTRO.lon, 300, 0), category="Distribuidora de Produtos Farmacêuticos"),
                linha("Drogaria X", *geo.deslocar(CENTRO.lat, CENTRO.lon, 400, 0), category="Drogaria")]
        app = criar_app(self.tmp, rows)
        esperar_tarefa(app, app.iniciar_busca("Rua A", raio_km=1, perfil="ti")["tarefa_id"])
        r, _ = chamar(app, "consultar_prospects", {"texto": "nada que exista"})
        self.assertEqual(r["total_filtrado"], 0)  # mesmo vazia, a resposta mostra as categorias exatas
        self.assertEqual(r["categorias_da_busca"][0], {"categoria": "Distribuidora de Produtos Farmacêuticos", "empresas": 2})
        r, _ = chamar(app, "consultar_prospects", {"categoria": "distribuidora de produtos farmaceuticos"})
        self.assertEqual(sorted(p["nome"] for p in r["prospects"]), ["Biotec Nutri", "Oncoprod"])
        r, _ = chamar(app, "consultar_prospects", {"categoria": "Drogaria | Empresa farmacêutica"})
        self.assertEqual(r["total_filtrado"], 2)
        r, _ = chamar(app, "consultar_prospects", {"texto": "distribuidora farmaceutica"})  # sem acento, singular
        self.assertEqual(r["total_filtrado"], 2)
        self.assertIn("categoria: distribuidora", chat._resumo_acao("consultar_prospects", {}, chamar(
            app, "consultar_prospects", {"categoria": "distribuidora de produtos farmaceuticos"})[0], False))

    def test_erros_viram_mensagem(self):
        res, erro = chamar(self.app, "iniciar_busca", {"endereco": "lugar que nada existe", "perfil": "ti"})
        self.assertTrue(erro)
        self.assertIn("não encontrado", res["erro"])
        res, erro = chamar(self.app, "iniciar_busca", {"endereco": "Rua A", "raio_km": 99, "perfil": "ti"})
        self.assertIn("raio", res["erro"])
        res, erro = chamar(self.app, "marcar_prospect", {"chave": "x", "status": "hackeado"})
        self.assertTrue(erro)
        res, erro = chamar(self.app, "nao_existe", {})
        self.assertTrue(erro)

    def test_cancelar_na_fila(self):
        self.app.disparar = lambda: None  # ninguém trabalha: fica na fila
        tid = self.app.iniciar_busca("Rua A", perfil="ti")["tarefa_id"]
        self.assertEqual(self.app.cancelar_busca(tid)["estado"], "cancelando")
        self.assertEqual(self.app.estado_busca(tid)["estado"], "cancelada")

    def test_um_trabalhador_por_vez(self):
        t1 = TravaArquivo(self.tmp / "x.lock")
        self.assertTrue(t1.tentar())
        self.assertTrue(TravaArquivo(self.tmp / "x.lock").ocupada())
        t1.liberar()
        self.assertFalse(TravaArquivo(self.tmp / "x.lock").ocupada())

    def test_orfa_vira_erro(self):
        self.app.disparar = lambda: None
        tid = self.app.iniciar_busca("Rua A", perfil="ti")["tarefa_id"]
        self.app.db.atualizar_tarefa(tid, estado="rodando")
        with self.app.db.trava, self.app.db.con:
            self.app.db.con.execute("UPDATE tarefas SET atualizada=0 WHERE id=?", (tid,))
        self.assertEqual(self.app.estado_busca(tid)["estado"], "erro")


class MCPTest(unittest.TestCase):
    def test_protocolo(self):
        tmp = Path(tempfile.mkdtemp())
        app = criar_app(tmp)
        entrada = "\n".join(json.dumps(m) for m in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "iniciar_busca", "arguments": {
                "endereco": "Rua A", "raio_km": 1, "perfil": "coifas"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "consultar_prospects", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "nada"},
        ]) + "\nisto não é json\n"
        saida = io.StringIO()
        with mock.patch.object(mcp_servidor, "Prospecta", lambda cfg, **k: app):
            mcp_servidor.servir(Config(), io.StringIO(entrada), saida)
        r = {m.get("id"): m for m in map(json.loads, saida.getvalue().splitlines())}
        self.assertEqual(r[1]["result"]["protocolVersion"], "2025-03-26")
        nomes = {t["name"] for t in r[2]["result"]["tools"]}
        self.assertIn("iniciar_busca", nomes)
        self.assertTrue(all(t["inputSchema"]["type"] == "object" for t in r[2]["result"]["tools"]))
        self.assertFalse(r[3]["result"]["isError"])
        self.assertIn("tarefa_id", json.loads(r[3]["result"]["content"][0]["text"]))
        self.assertEqual(r[5]["error"]["code"], -32601)
        self.assertEqual(r[None]["error"]["code"], -32700)


class PainelTest(BaseOpenAI):
    def setUp(self):
        super().setUp()
        self.app = criar_app(self.tmp)
        agente = chat.AgenteChat(self.app, self.auth, chat.ClienteResponses(self.oa.url + "/v1"))
        self.srv = painel.ServidorPainel(0, self.app, self.auth, agente)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.porta}"
        self.cab = {"X-Prospecta": self.srv.token}

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def api(self, caminho, corpo=None):
        status, _, dados = pedir(self.base + caminho, "POST" if corpo is not None else "GET", corpo, self.cab)
        return status, json.loads(dados or b"null")

    def test_seguranca(self):
        status, _, html = pedir(self.base + "/")
        self.assertEqual(status, 200)
        self.assertIn(self.srv.token.encode(), html)
        self.assertEqual(pedir(self.base + "/api/estado")[0], 401)
        self.assertEqual(pedir(self.base + "/api/estado", cab={"X-Prospecta": "errado"})[0], 401)
        self.assertEqual(pedir(self.base + "/api/estado", cab=dict(self.cab, Host="evil.com"))[0], 421)
        self.assertEqual(pedir(self.base + "/api/config", "POST", {}, dict(self.cab, Origin="https://evil.com"))[0], 403)
        self.assertEqual(pedir(self.base + "/auth/entrar")[0], 401)  # sem token na URL
        self.assertEqual(pedir(self.base + "/arquivos/1/../../etc/passwd?t=" + self.srv.token)[0], 404)

    def test_busca_pelo_painel(self):
        st, cfg = self.api("/api/config", {"meu_nome": "Ana", "minha_empresa": "Limpa Tudo"})
        self.assertEqual((st, cfg["meu_nome"]), (200, "Ana"))
        st, r = self.api("/api/buscas", {"endereco": "Rua A, 1", "raio_km": 1.5, "perfil": "limpeza"})
        self.assertEqual(st, 200, r)
        esperar_tarefa(self.app, r["tarefa_id"])
        st, e = self.api("/api/estado")
        bid = e["buscas"][0]["busca_id"]
        st, b = self.api(f"/api/buscas/{bid}")
        self.assertEqual(len(b["itens"]), 8)
        self.assertIn("Limpa%20Tudo", b["itens"][0]["link_whatsapp"])
        st, _ = self.api("/api/prospects/marcar", {"chave": b["itens"][0]["chave"], "status": "visitar"})
        self.assertEqual(st, 200)
        st, rota = self.api(f"/api/buscas/{bid}/rota?n=5")
        self.assertEqual(len(rota["paradas"]), 5)
        st, exp = self.api(f"/api/buscas/{bid}/exportar", {})
        status, cab, dados = pedir(self.base + exp["links"]["planilha"])
        self.assertEqual(status, 200)
        self.assertTrue(dados.startswith(b"PK"))
        st, r = self.api("/api/buscas", {"endereco": ""})
        self.assertEqual(st, 400)
        tid = self.api("/api/tarefas")[1][0]["tarefa_id"]
        st, a = self.api(f"/api/tarefas/{tid}")
        self.assertEqual((st, a["estado"], a["detalhe"]["etapa"]), (200, "ok", "fim"))
        self.assertEqual(self.api("/api/tarefas/9999")[0], 400)

    def test_login_e_chat_pelo_painel(self):
        st, e = self.api("/api/estado")
        self.assertIsNone(e["conta"])
        status, cab, _ = pedir(f"{self.base}/auth/entrar?t={self.srv.token}")
        self.assertEqual(status, 303)
        status, cab, _ = pedir(cab["Location"])  # "navegador" vai à OpenAI falsa
        self.assertEqual(status, 302)
        volta = cab["Location"]
        self.assertTrue(volta.startswith(f"http://127.0.0.1:{self.srv.porta}/auth/callback?"))
        status, cab, _ = pedir(volta)
        self.assertEqual((status, cab["Location"]), (303, "/?login=ok"))
        st, e = self.api("/api/estado")
        self.assertEqual((e["conta"]["email"], e["conta"]["plano"], e["conta"]["boas_vindas_vista"]),
                         ("ana@exemplo.com", True, False))
        self.api("/api/chat/boas-vindas", {})
        self.assertTrue(self.api("/api/estado")[1]["conta"]["boas_vindas_vista"])
        tid = self.app.iniciar_busca("Rua A", raio_km=1, perfil="ti")["tarefa_id"]
        esperar_tarefa(self.app, tid)
        st, ms = self.api("/api/chat/modelos")
        st, r = self.api("/api/chat", {"mensagem": "quais os melhores?", "modelo": ms[0]["slug"]})
        self.assertEqual(st, 200, r)
        self.assertIn("Achei", r["resposta"])
        cid = r["conversa_id"]
        self.assertEqual(r["conversa"]["busca_id"], None)  # nada aberto na tela: conversa geral
        st, lista = self.api("/api/chat/conversas")
        self.assertEqual([(x["id"], x["titulo"]) for x in lista], [(cid, "quais os melhores?")])
        st, conv = self.api(f"/api/chat/conversas/{cid}")
        self.assertEqual([m["tipo"] for m in conv["mensagens"]], ["eu", "acao", "ia"])
        bid = self.api("/api/estado")[1]["buscas"][0]["busca_id"]
        st, r2 = self.api("/api/chat", {"mensagem": "e os de WhatsApp?", "modelo": "gpt-teste", "busca_id": bid})
        self.assertEqual(r2["conversa"]["busca_id"], bid)
        self.assertEqual(self.api("/api/chat", {"mensagem": "x", "busca_id": "1; drop"})[0], 400)
        self.assertEqual(self.api("/api/chat/conversas/../../x")[0], 404)
        self.assertEqual(self.api(f"/api/chat/conversas/{'0' * 32}")[0], 404)
        st, _ = self.api(f"/api/chat/conversas/{r2['conversa_id']}/apagar", {})
        self.assertEqual(st, 200)
        self.assertEqual(len(self.api("/api/chat/conversas")[1]), 1)
        self.oa.limite = True
        st, r = self.api("/api/chat", {"conversa_id": cid, "mensagem": "mais", "modelo": "gpt-teste"})
        self.assertEqual((st, r["tipo"], r["gerenciar_uso"]), (400, "limite", "https://chatgpt.com/settings/usage"))
        st, r = self.api("/auth/sair", {})
        self.assertEqual(self.oa.revogados[-1]["client_id"], "oaiapp_teste123")
        self.assertTrue(self.api("/api/estado")[1]["conta"]["desconectada"])


if __name__ == "__main__":
    unittest.main()
