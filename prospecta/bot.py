"""Bot do Telegram: o usuário manda um endereço (ou a localização) e recebe os prospects do raio,
com WhatsApp, rota otimizada, planilha, mapa e um mini-CRM para acompanhar cada contato."""
import html
import logging
import queue
import threading
import time
from dataclasses import asdict
from pathlib import Path

from . import busca, exporta, geo, perfis as perfis_mod, rotas, telefone
from .banco import STATUS
from .motor import Cancelado, ErroMotor
from .rede import ErroRede
from .telegram import ErroTelegram

log = logging.getLogger("prospecta")
POR_PAGINA = 10
RAIOS = (1, 2, 3, 5, 8, 10)
COR = {"A": "🟢", "B": "🟡", "C": "⚪"}
COMANDOS = [
    ("start", "Como usar o bot"),
    ("perfil", "Escolher o tipo de serviço que você presta"),
    ("alvos", "Definir os tipos de negócio a procurar"),
    ("raio", "Raio da busca em km (ex.: /raio 3)"),
    ("modo", "Busca rápida ou completa"),
    ("empresa", "Seu nome e empresa (ex.: /empresa Ana | Frio Total)"),
    ("base", "Endereço da sua empresa, ponto de partida das rotas"),
    ("lista", "Ver os prospects da última busca"),
    ("rota", "Rota otimizada de visitas (ex.: /rota 8)"),
    ("planilha", "Receber a planilha e o mapa de novo"),
    ("funil", "Resumo dos contatos que você marcou"),
    ("novos", "Mostrar só prospects que você ainda não recebeu"),
    ("config", "Ver suas configurações"),
    ("cancelar", "Cancelar a busca em andamento"),
]


def e(texto):
    return html.escape(str(texto or ""), quote=False)


def km(valor):
    return f"{valor:.1f}".replace(".", ",") + " km"


class Bot:
    def __init__(self, cfg, tg, motor, geocoder, banco, perfis):
        self.cfg, self.tg, self.motor, self.geo, self.db, self.perfis = cfg, tg, motor, geocoder, banco, perfis
        self.fila = queue.Queue()
        self.pendentes = {}      # chat_id -> Local aguardando confirmação
        self.aguardando = {}     # chat_id -> ("obs", busca_id, idx) quando esperamos um texto
        self.cancelar = {}       # chat_id -> threading.Event da busca em andamento ou na fila
        self.pasta = Path(cfg.pasta_dados) / "arquivos"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._trabalhador = threading.Thread(target=self._trabalhar, daemon=True, name="buscas")

    # ── laço principal ──
    def rodar(self):
        try:
            self.tg.comandos(COMANDOS)
        except ErroTelegram as ex:
            log.warning("não consegui registrar os comandos: %s", ex)
        self._trabalhador.start()
        offset = None
        log.info("bot no ar; aguardando mensagens")
        while True:
            try:
                atualizacoes = self.tg.atualizacoes(offset)
            except ErroTelegram as ex:
                log.warning("getUpdates falhou: %s", ex)
                time.sleep(5)
                continue
            for u in atualizacoes:
                offset = u["update_id"] + 1
                self.tratar(u)

    def tratar(self, u):
        try:
            if "callback_query" in u:
                self._botao(u["callback_query"])
            elif "message" in u:
                self._mensagem(u["message"])
        except (ErroTelegram, ErroRede) as ex:
            log.warning("falha ao responder: %s", ex)
        except (ValueError, IndexError, KeyError, TypeError) as ex:  # botão antigo ou dado malformado
            log.info("update %s ignorado: %r", u.get("update_id"), ex)
        except Exception:  # um update ruim não pode derrubar o bot
            log.exception("erro tratando update %s", u.get("update_id"))

    def permitido(self, usuario_id, chat_id):
        if usuario_id in self.cfg.usuarios_permitidos:
            return True
        self.tg.enviar(chat_id, f"🔒 Este bot é privado. Seu ID do Telegram é <code>{usuario_id}</code>.\n"
                                "Peça ao administrador para incluí-lo em USUARIOS_PERMITIDOS.")
        return False

    # ── mensagens ──
    def _mensagem(self, m):
        chat_id = m["chat"]["id"]
        if not self.permitido((m.get("from") or {}).get("id"), chat_id):
            return
        if "location" in m:
            loc = m["location"]
            local = self.geo.reverso(loc["latitude"], loc["longitude"]) or geo.Local(
                loc["latitude"], loc["longitude"], "Localização enviada")
            return self._confirmar(chat_id, local)
        texto = (m.get("text") or "").strip()
        if not texto:
            return
        if texto.startswith("/"):
            cmd, _, resto = texto[1:].partition(" ")
            cmd = cmd.split("@")[0].lower()
            fn = getattr(self, f"cmd_{cmd}", None)
            self.aguardando.pop(chat_id, None)
            return fn(chat_id, resto.strip()) if fn else self.tg.enviar(chat_id, "Não conheço esse comando. /start")
        espera = self.aguardando.pop(chat_id, None)
        if espera and espera[0] == "obs":
            return self._salvar_obs(chat_id, espera[1], espera[2], texto)
        if espera and espera[0] == "base":
            return self.cmd_base(chat_id, texto)
        self._endereco(chat_id, texto)

    def _endereco(self, chat_id, texto):
        self.tg.enviar(chat_id, "🔎 Procurando o endereço…")
        try:
            local = self.geo.buscar(texto)
        except ErroRede as ex:
            return self.tg.enviar(chat_id, f"⚠️ O serviço de mapas não respondeu ({e(ex)}). Tente de novo em instantes "
                                           "ou mande sua 📎 Localização.")
        if not local:
            return self.tg.enviar(chat_id, "Não achei esse endereço. Tente com rua, número e cidade, um CEP, "
                                           "ou mande a 📎 Localização pelo Telegram.")
        self._confirmar(chat_id, local)

    def _perfil(self, c):
        if c["alvos"]:
            base = self.perfis.get(c["perfil"])
            return perfis_mod.personalizado(perfis_mod.separar_alvos(c["alvos"]), base.mensagem if base else None)
        return self.perfis.get(c["perfil"]) or next(iter(self.perfis.values()))

    def _confirmar(self, chat_id, local, msg_id=None):
        self.pendentes[chat_id] = local
        c = self.db.chat(chat_id)
        perfil = self._perfil(c)
        minutos, areas = busca.estimar_minutos(c["raio_km"] * 1000, c["modo"], len(perfil.alvos))
        texto = (f"📍 <b>{e(local.descricao)}</b>\n\n"
                 f"Serviço: <b>{e(perfil.nome)}</b>\n"
                 f"Procurar: {e(', '.join(perfil.alvos))}\n"
                 f"Raio: <b>{km(c['raio_km'])}</b> · modo {busca.MODOS[c['modo']]['nome']} · "
                 f"{areas} área(s) · ~{minutos} min\n\nConfirma?")
        teclado = {"inline_keyboard": [
            [{"text": "▶️ Buscar prospects", "callback_data": "ir"}],
            [{"text": ("• " if c["raio_km"] == r else "") + f"{r} km", "callback_data": f"raio:{r}"} for r in RAIOS],
            [{"text": "⚙️ Trocar serviço", "callback_data": "menu:perfil"},
             {"text": "⚡ Rápido" if c["modo"] == "completo" else "🔬 Completo",
              "callback_data": "modo:" + ("rapido" if c["modo"] == "completo" else "completo") + ":c"}],
        ]}
        if msg_id:
            self.tg.editar(chat_id, msg_id, texto, teclado)
        else:
            self.tg.enviar(chat_id, texto, teclado)

    # ── comandos ──
    def cmd_start(self, chat_id, _=""):
        nomes = "\n".join(f"• {e(p.nome)} — {e(p.descricao)}" for p in self.perfis.values())
        self.tg.enviar(chat_id,
                       "👋 <b>Prospecção B2B pelo Google Maps</b>\n\n"
                       "Mande um <b>endereço</b>, um <b>CEP</b> ou a sua <b>📎 Localização</b> e eu procuro, no raio "
                       "escolhido, os negócios que podem contratar o seu serviço: telefone, WhatsApp, e-mail, "
                       "Instagram, distância, nota de prioridade, rota de visitas, planilha e mapa.\n\n"
                       f"<b>Serviços prontos</b> (/perfil):\n{nomes}\n\n"
                       "Nenhum serve? Use /alvos com os tipos de negócio, ex.: <code>/alvos padaria, mercado, hotel"
                       "</code>\n\nAntes da primeira busca, configure /empresa (para a mensagem de abordagem) e "
                       "/base (ponto de partida das rotas). /config mostra tudo.")

    cmd_ajuda = cmd_help = cmd_start

    def cmd_config(self, chat_id, _=""):
        c = self.db.chat(chat_id)
        perfil = self._perfil(c)
        base = c["base"].split("|", 2)[2] if c["base"].count("|") >= 2 else "o endereço de cada busca"
        self.tg.enviar(chat_id,
                       f"⚙️ <b>Suas configurações</b>\n\nServiço: {e(perfil.nome)}\nProcurar: {e(', '.join(perfil.alvos))}\n"
                       f"Raio: {km(c['raio_km'])}\nModo: {busca.MODOS[c['modo']]['nome']}\n"
                       f"Seu nome: {e(c['meu_nome']) or '—'}\nEmpresa: {e(c['minha_empresa']) or '—'}\n"
                       f"Base das rotas: {e(base)}\nSó prospects novos: {'sim' if c['so_novos'] else 'não'}")

    def cmd_perfil(self, chat_id, _=""):
        teclado = {"inline_keyboard": [[{"text": p.nome, "callback_data": f"perfil:{k}"}] for k, p in self.perfis.items()]}
        self.tg.enviar(chat_id, "Qual serviço você presta? (para outros, use /alvos)", teclado)

    def cmd_alvos(self, chat_id, texto):
        if texto.lower() in ("limpar", "padrao", "padrão"):
            self.db.ajustar(chat_id, alvos="")
            return self.tg.enviar(chat_id, "Voltei a usar os alvos do serviço escolhido em /perfil.")
        alvos = perfis_mod.separar_alvos(texto)
        if not alvos:
            atual = self._perfil(self.db.chat(chat_id))
            return self.tg.enviar(chat_id, f"Procurando hoje: {e(', '.join(atual.alvos))}\n\nPara mudar: "
                                           "<code>/alvos padaria, sorveteria, mercado</code> (até 20)\n"
                                           "Para voltar ao padrão do serviço: <code>/alvos limpar</code>")
        self.db.ajustar(chat_id, alvos=", ".join(alvos))
        self.tg.enviar(chat_id, f"✅ Vou procurar: {e(', '.join(alvos))}\n"
                                "Dica: menos tipos = busca mais rápida.")

    def cmd_raio(self, chat_id, texto):
        try:
            r = float(texto.replace(",", ".").lower().replace("km", "").strip())
        except ValueError:
            return self.tg.enviar(chat_id, f"Use, por exemplo, <code>/raio 3</code> (de 0,5 a {self.cfg.raio_maximo_km:g} km).")
        if not 0.5 <= r <= self.cfg.raio_maximo_km:
            return self.tg.enviar(chat_id, f"O raio vai de 0,5 a {self.cfg.raio_maximo_km:g} km.")
        self.db.ajustar(chat_id, raio_km=r)
        self.tg.enviar(chat_id, f"✅ Raio: {km(r)}")

    def cmd_modo(self, chat_id, _=""):
        self.tg.enviar(chat_id, "⚡ <b>Rápido</b>: ~20 lugares por tipo em cada área, sem ler avaliações.\n"
                                "🔬 <b>Completo</b>: ~60 por tipo, áreas menores e 3 avaliações por lugar (acha "
                                "sinais de necessidade). Leva várias vezes mais tempo.",
                       {"inline_keyboard": [[{"text": "⚡ Rápido", "callback_data": "modo:rapido"},
                                             {"text": "🔬 Completo", "callback_data": "modo:completo"}]]})

    def cmd_empresa(self, chat_id, texto):
        if "|" not in texto:
            return self.tg.enviar(chat_id, "Use: <code>/empresa Seu Nome | Nome da Empresa</code>")
        nome, _, empresa = texto.partition("|")
        self.db.ajustar(chat_id, meu_nome=nome.strip()[:60], minha_empresa=empresa.strip()[:80])
        self.tg.enviar(chat_id, f"✅ Mensagens serão assinadas por {e(nome.strip())}, da {e(empresa.strip())}.")

    def cmd_base(self, chat_id, texto):
        if not texto:
            self.aguardando[chat_id] = ("base",)
            return self.tg.enviar(chat_id, "Mande o endereço da sua empresa (ou <code>/base limpar</code> para usar o "
                                           "endereço de cada busca como ponto de partida).")
        if texto.lower() == "limpar":
            self.db.ajustar(chat_id, base="")
            return self.tg.enviar(chat_id, "✅ As rotas vão sair do endereço de cada busca.")
        try:
            local = self.geo.buscar(texto)
        except ErroRede as ex:
            return self.tg.enviar(chat_id, f"⚠️ O serviço de mapas não respondeu ({e(ex)}).")
        if not local:
            return self.tg.enviar(chat_id, "Não achei esse endereço. Tente com rua, número e cidade, ou um CEP.")
        self.db.ajustar(chat_id, base=f"{local.lat}|{local.lon}|{local.descricao}")
        self.tg.enviar(chat_id, f"✅ Base das rotas: {e(local.descricao)}")

    def cmd_novos(self, chat_id, _=""):
        novo = 0 if self.db.chat(chat_id)["so_novos"] else 1
        self.db.ajustar(chat_id, so_novos=novo)
        self.tg.enviar(chat_id, "✅ Vou mostrar só prospects que você ainda não recebeu." if novo
                       else "✅ Vou mostrar todos os prospects, inclusive os já recebidos.")

    def cmd_cancelar(self, chat_id, _=""):
        ev = self.cancelar.get(chat_id)
        if ev and not ev.is_set():
            ev.set()
            return self.tg.enviar(chat_id, "⏹️ Cancelando a busca…")
        self.tg.enviar(chat_id, "Nenhuma busca em andamento.")

    def cmd_lista(self, chat_id, texto=""):
        b = self.db.busca(chat_id)
        if not b:
            return self.tg.enviar(chat_id, "Você ainda não fez nenhuma busca. Mande um endereço.")
        pagina = int(texto) - 1 if texto.isdigit() and int(texto) > 0 else 0
        self._pagina(chat_id, b, pagina)

    def cmd_rota(self, chat_id, texto=""):
        b = self.db.busca(chat_id)
        if not b:
            return self.tg.enviar(chat_id, "Faça uma busca primeiro: mande um endereço.")
        n = int(texto) if texto.isdigit() else 8
        self._rota(chat_id, b, max(1, min(n, 25)))

    def cmd_planilha(self, chat_id, _=""):
        b = self.db.busca(chat_id)
        if not b:
            return self.tg.enviar(chat_id, "Faça uma busca primeiro: mande um endereço.")
        self._arquivos(chat_id, b)

    def cmd_funil(self, chat_id, _=""):
        contagem, ativos = self.db.funil(chat_id)
        linhas = [f"{STATUS[k]}: {contagem.get(k, 0)}" for k in STATUS]
        txt = "📊 <b>Seu funil</b>\n" + "\n".join(linhas)
        txt += f"\nAinda sem status: {contagem.get('', 0)}"
        if ativos:
            txt += "\n\n<b>Em andamento</b>\n" + "\n".join(
                f"{STATUS.get(a['status'], '')} {e(a['nome'])}" + (f" — <i>{e(a['obs'][:80])}</i>" if a["obs"] else "")
                for a in ativos)
        self.tg.enviar(chat_id, txt)

    # ── botões ──
    def _botao(self, q):
        chat_id = q["message"]["chat"]["id"]
        msg_id = q["message"]["message_id"]
        self.tg.responder_botao(q["id"])
        if not self.permitido((q.get("from") or {}).get("id"), chat_id):
            return
        partes = (q.get("data") or "").split(":")
        acao = partes[0]
        if acao == "ir":
            return self._enfileirar(chat_id, msg_id)
        if acao == "raio":
            self.db.ajustar(chat_id, raio_km=float(partes[1]))
            if chat_id in self.pendentes:
                return self._confirmar(chat_id, self.pendentes[chat_id], msg_id)
            return
        if acao == "modo":
            self.db.ajustar(chat_id, modo=partes[1] if partes[1] in busca.MODOS else "rapido")
            if len(partes) > 2 and chat_id in self.pendentes:
                return self._confirmar(chat_id, self.pendentes[chat_id], msg_id)
            return self.tg.editar(chat_id, msg_id, f"✅ Modo {busca.MODOS[self.db.chat(chat_id)['modo']]['nome']}.")
        if acao == "menu" and partes[1] == "perfil":
            return self.cmd_perfil(chat_id)
        if acao == "perfil":
            p = self.perfis.get(partes[1])
            if not p:
                return
            self.db.ajustar(chat_id, perfil=p.chave, alvos="")
            self.tg.editar(chat_id, msg_id, f"✅ Serviço: <b>{e(p.nome)}</b>\nVou procurar: {e(', '.join(p.alvos))}")
            if chat_id in self.pendentes:
                self._confirmar(chat_id, self.pendentes[chat_id])
            return
        if acao == "cancelar":
            return self.cmd_cancelar(chat_id)
        if acao in ("pg", "p", "st", "obs", "rota", "mapa", "arq"):
            b = self.db.busca(chat_id, int(partes[1]))
            if not b:
                return self.tg.enviar(chat_id, "Essa busca não existe mais.")
            if acao == "pg":
                return self._pagina(chat_id, b, int(partes[2]), msg_id)
            if acao == "rota":
                return self._rota(chat_id, b, int(partes[2]))
            if acao == "arq":
                return self._arquivos(chat_id, b)
            idx = int(partes[2])
            if not 0 <= idx < len(b["itens"]):
                return
            if acao == "p":
                return self._detalhe(chat_id, b, idx)
            if acao == "mapa":
                p = b["itens"][idx]
                return self.tg.local(chat_id, p["lat"], p["lon"], p["nome"], p["endereco"])
            if acao == "st":
                self.db.marcar(chat_id, b["itens"][idx]["chave"], status=partes[3] if partes[3] in STATUS else "")
                return self._detalhe(chat_id, b, idx, msg_id)
            if acao == "obs":
                self.aguardando[chat_id] = ("obs", b["id"], idx)
                return self.tg.enviar(chat_id, f"📝 Escreva a observação sobre <b>{e(b['itens'][idx]['nome'])}</b>:")

    def _salvar_obs(self, chat_id, busca_id, idx, texto):
        b = self.db.busca(chat_id, busca_id)
        if b and 0 <= idx < len(b["itens"]):
            self.db.marcar(chat_id, b["itens"][idx]["chave"], obs=texto)
            self.tg.enviar(chat_id, "✅ Observação salva.")
            self._detalhe(chat_id, b, idx)

    # ── busca em segundo plano ──
    def _enfileirar(self, chat_id, msg_id):
        local = self.pendentes.pop(chat_id, None)
        if not local:
            return self.tg.editar(chat_id, msg_id, "Mande o endereço de novo, por favor.")
        ev = self.cancelar.get(chat_id)
        if ev and not ev.is_set():
            return self.tg.enviar(chat_id, "Você já tem uma busca em andamento. /cancelar para interrompê-la.")
        if self.db.buscas_hoje(chat_id) >= self.cfg.buscas_por_dia:
            return self.tg.enviar(chat_id, f"Limite de {self.cfg.buscas_por_dia} buscas por dia atingido. "
                                           "Isso protege seu IP de bloqueios do Google.")
        self.cancelar[chat_id] = threading.Event()
        pos = self.fila.qsize()
        self.fila.put((chat_id, local))
        self.tg.editar(chat_id, msg_id, f"⏳ Busca em {e(local.descricao)} " +
                       (f"na fila (posição {pos + 1})." if pos else "começando…"))

    def _trabalhar(self):
        while True:
            chat_id, local = self.fila.get()
            try:
                self._executar(chat_id, local)
            except Exception:
                log.exception("busca falhou")
                try:
                    self.tg.enviar(chat_id, "❌ Algo deu errado nesta busca. Tente de novo; se repetir, avise o "
                                            "administrador.")
                except ErroTelegram:
                    pass
            finally:
                self.cancelar.pop(chat_id, None)
                self.fila.task_done()

    def _executar(self, chat_id, local):
        ev = self.cancelar.get(chat_id) or threading.Event()
        if ev.is_set():
            return self.tg.enviar(chat_id, "⏹️ Busca cancelada.")
        c = self.db.chat(chat_id)
        perfil = self._perfil(c)
        raio_m = c["raio_km"] * 1000
        cancelar_btn = {"inline_keyboard": [[{"text": "⏹️ Cancelar", "callback_data": "cancelar"}]]}
        msg = self.tg.enviar(chat_id, "🔎 Buscando… 0%", cancelar_btn)
        ultimo = [0.0]

        def progresso(feitos, total, lugares):
            agora = time.monotonic()
            if agora - ultimo[0] < 6:
                return
            ultimo[0] = agora
            pct = int(100 * feitos / max(total, 1))
            barra = "▓" * (pct // 10) + "░" * (10 - pct // 10)
            try:
                self.tg.editar(chat_id, msg["message_id"], f"🔎 Buscando {e(perfil.nome)}…\n{barra} {pct}%\n"
                               f"Área {min(int(feitos) + 1, total)} de {total} · {lugares} lugares lidos",
                               cancelar_btn)
            except ErroTelegram:
                pass

        try:
            res = busca.prospectar(self.motor, local, raio_m, perfil, c["modo"], progresso, ev)
        except Cancelado:
            return self.tg.editar(chat_id, msg["message_id"], "⏹️ Busca cancelada.")
        except ErroMotor as ex:
            return self.tg.editar(chat_id, msg["message_id"], f"❌ {e(ex)}")
        prospects, ocultos = res.prospects, 0
        if c["so_novos"]:
            vistos = self.db.ja_vistos(chat_id, [p.chave for p in prospects])
            ocultos = sum(p.chave in vistos for p in prospects)
            prospects = [p for p in prospects if p.chave not in vistos]
        busca_id = self.db.salvar_busca(chat_id, asdict(local), c["raio_km"], perfil.nome, prospects, res.avisos)
        self.tg.editar(chat_id, msg["message_id"], "✅ Busca concluída.")
        self.tg.enviar(chat_id, self._resumo(local, c, perfil, res, prospects, ocultos))
        b = self.db.busca(chat_id, busca_id)
        if prospects:
            self._pagina(chat_id, b, 0)
            self._arquivos(chat_id, b)

    def _resumo(self, local, c, perfil, res, prospects, ocultos):
        cont = {k: sum(p.prioridade == k for p in prospects) for k in "ABC"}
        wa = sum(bool(p.whatsapp) for p in prospects)
        wa_ok = sum(p.whatsapp_status == "confirmado" for p in prospects)
        em = sum(bool(p.emails) for p in prospects)
        ig = sum(bool(p.instagram) for p in prospects)
        sem_site = sum(not p.site_proprio for p in prospects)
        txt = (f"✅ <b>{len(prospects)} prospects</b> até {km(c['raio_km'])} de <i>{e(local.descricao)}</i>\n"
               f"Serviço: {e(perfil.nome)}\n\n"
               f"🟢 A: {cont['A']} · 🟡 B: {cont['B']} · ⚪ C: {cont['C']}\n"
               f"📱 WhatsApp: {wa} (confirmado no site: {wa_ok})\n✉️ E-mail: {em} · 📸 Instagram: {ig}\n"
               f"🌐 Sem site próprio: {sem_site}\n"
               f"⏱️ {round(res.segundos / 60) or 1} min · {res.pontos_feitos}/{res.pontos_total} áreas · "
               f"{res.brutos} resultados lidos")
        if ocultos:
            txt += f"\n🙈 {ocultos} já recebidos antes foram ocultados (/novos para mudar)"
        for a in res.avisos:
            txt += f"\n⚠️ {e(a)}"
        if not prospects:
            txt += "\n\nNada encontrado. Tente um raio maior (/raio) ou outros tipos de negócio (/alvos)."
        return txt

    # ── apresentação ──
    def _pagina(self, chat_id, b, pagina, msg_id=None):
        itens = b["itens"]
        total_pg = max(1, -(-len(itens) // POR_PAGINA))
        pagina = max(0, min(pagina, total_pg - 1))
        ini = pagina * POR_PAGINA
        linhas = []
        for i, p in enumerate(itens[ini:ini + POR_PAGINA], start=ini):
            contato = "💬" if p["whatsapp"] else ("📞" if p["telefone"] else "—")
            linhas.append(f"<b>{i + 1}.</b> {COR.get(p['prioridade'], '')}{p['nota']} {e(p['nome'])}\n"
                          f"     {km(p['distancia_m'] / 1000)} · {e(p['bairro'] or p['categoria'])} · {contato} "
                          f"{e(p['telefone'])}")
        txt = (f"📋 <b>Prospects</b> (página {pagina + 1}/{total_pg})\n"
               "🟢 alta · 🟡 média · ⚪ baixa prioridade · 💬 tem WhatsApp\n\n" + "\n".join(linhas) +
               "\n\nToque no número para ver detalhes, WhatsApp e rota.")
        nums = [{"text": str(i + 1), "callback_data": f"p:{b['id']}:{i}"} for i in range(ini, min(ini + POR_PAGINA, len(itens)))]
        teclado = [nums[:5], nums[5:]]
        nav = []
        if pagina > 0:
            nav.append({"text": "◀️ Anterior", "callback_data": f"pg:{b['id']}:{pagina - 1}"})
        if pagina < total_pg - 1:
            nav.append({"text": "Próxima ▶️", "callback_data": f"pg:{b['id']}:{pagina + 1}"})
        teclado.append(nav)
        teclado.append([{"text": "🗺️ Rota top 8", "callback_data": f"rota:{b['id']}:8"},
                        {"text": "📄 Planilha + mapa", "callback_data": f"arq:{b['id']}"}])
        teclado = {"inline_keyboard": [linha for linha in teclado if linha]}
        if msg_id:
            self.tg.editar(chat_id, msg_id, txt, teclado)
        else:
            self.tg.enviar(chat_id, txt, teclado)

    def _base(self, chat_id, b):
        base = self.db.chat(chat_id)["base"]
        if base.count("|") >= 2:
            lat, lon, desc = base.split("|", 2)
            return geo.Local(float(lat), float(lon), desc)
        L = b["local"]
        return geo.Local(L["lat"], L["lon"], L["descricao"], L.get("bairro", ""), L.get("cidade", ""))

    def _perfil_da_busca(self, chat_id, b):
        c = self.db.chat(chat_id)
        p = self._perfil(c)
        return p, c

    def _detalhe(self, chat_id, b, idx, msg_id=None):
        p = busca.Prospect.de_dict(b["itens"][idx])
        perfil, c = self._perfil_da_busca(chat_id, b)
        base = self._base(chat_id, b)
        reg = self.db.prospect(chat_id, p.chave) or {}
        linhas = [f"{COR.get(p.prioridade, '')} <b>{e(p.nome)}</b> — nota {p.nota} ({p.prioridade})",
                  f"🏷️ {e(p.categoria)}" + (f" · buscado como “{e(p.alvo)}”" if p.alvo else ""),
                  f"📍 {e(p.endereco) or 'endereço não informado'} · {km(p.distancia_km)} da busca"]
        if p.telefone:
            linhas.append(f"📞 {e(p.telefone)} ({e(p.telefone_tipo)})")
        if p.whatsapp:
            linhas.append(f"💬 WhatsApp {e(p.whatsapp_status)}")
        if p.emails:
            linhas.append(f"✉️ {e(p.emails)}")
        if p.site and p.site_proprio:
            linhas.append(f"🌐 {e(p.site)}")
        if p.instagram:
            linhas.append(f"📸 {e(p.instagram)}")
        if p.nota_google:
            linhas.append(f"⭐ {e(p.nota_google)} no Google ({e(p.avaliacoes or '?')} avaliações)")
        if p.sinais:
            linhas.append(f"🔥 Sinais nas avaliações: {e(', '.join(p.sinais))}")
        if p.horario:
            linhas.append(f"🕒 {e(p.horario[:200])}")
        if reg.get("status"):
            linhas.append(f"\nStatus: {STATUS.get(reg['status'], reg['status'])}")
        if reg.get("obs"):
            linhas.append(f"📝 {e(reg['obs'])}")
        msg = busca.mensagem_para(p, perfil, c["meu_nome"], c["minha_empresa"])
        if p.whatsapp:
            linhas.append(f"\n<b>Mensagem sugerida</b> (abre pronta no botão WhatsApp):\n<i>{e(msg)}</i>")
        links = []
        if p.whatsapp:
            links.append({"text": "💬 WhatsApp", "url": telefone.link_whatsapp(p.whatsapp, msg)})
        links.append({"text": "🗺️ Rota", "url": rotas.link_ate((base.lat, base.lon), p.lat, p.lon)})
        links.append({"text": "🚗 Waze", "url": rotas.link_waze(p.lat, p.lon)})
        teclado = [links]
        if p.link_maps.startswith("https://"):
            teclado.append([{"text": "📍 Ficha no Google Maps", "url": p.link_maps}])
        st = list(STATUS.items())
        teclado.append([{"text": v, "callback_data": f"st:{b['id']}:{idx}:{k}"} for k, v in st[:3]])
        teclado.append([{"text": v, "callback_data": f"st:{b['id']}:{idx}:{k}"} for k, v in st[3:]] +
                       [{"text": "📝 Obs.", "callback_data": f"obs:{b['id']}:{idx}"}])
        teclado.append([{"text": "📌 Ver no mapa", "callback_data": f"mapa:{b['id']}:{idx}"},
                        {"text": "⬅️ Lista", "callback_data": f"pg:{b['id']}:{idx // POR_PAGINA}"}])
        if msg_id:
            self.tg.editar(chat_id, msg_id, "\n".join(linhas), {"inline_keyboard": teclado})
        else:
            self.tg.enviar(chat_id, "\n".join(linhas), {"inline_keyboard": teclado})

    def _rota(self, chat_id, b, n):
        itens = [busca.Prospect.de_dict(d) for d in b["itens"]]
        if not itens:
            return self.tg.enviar(chat_id, "Esta busca não tem prospects.")
        # as melhores notas, sem quem já marcou "sem interesse" ou já é cliente
        status = self.db.status_de(chat_id)
        fora = {STATUS["sem_interesse"], STATUS["cliente"]}
        escolhidos = [p for p in itens if status.get(p.chave, ("",))[0] not in fora][:n]
        base = self._base(chat_id, b)
        r = rotas.planejar(base, escolhidos, volta=True, osrm_url=self.cfg.osrm_url)
        linhas = [f"{i}. {e(p.nome)} — {e(p.bairro or p.endereco[:40])}" for i, p in enumerate(r["ordem"], 1)]
        txt = (f"🗺️ <b>Rota de visitas</b> ({len(escolhidos)} paradas, saindo de {e(base.descricao[:60])})\n\n"
               + "\n".join(linhas) +
               f"\n\n🚗 {km(r['km'])} · ~{r['minutos_carro']} min dirigindo"
               f"{' (estimado)' if r['estimado'] else ''} · ~{r['minutos']} min com visitas de "
               f"{rotas.MINUTOS_POR_VISITA} min")
        teclado = {"inline_keyboard": [[{"text": f"Abrir trecho {i} no Google Maps" if len(r["links"]) > 1
                                         else "Abrir rota no Google Maps", "url": link}]
                                       for i, link in enumerate(r["links"], 1)] +
                   [[{"text": f"Rota top {m}", "callback_data": f"rota:{b['id']}:{m}"} for m in (5, 10, 15) if m != n]]}
        self.tg.enviar(chat_id, txt, teclado)

    def _arquivos(self, chat_id, b):
        itens = [busca.Prospect.de_dict(d) for d in b["itens"]]
        if not itens:
            return self.tg.enviar(chat_id, "Esta busca não tem prospects.")
        perfil, c = self._perfil_da_busca(chat_id, b)
        base = self._base(chat_id, b)
        rota = rotas.planejar(base, itens[:10], osrm_url=self.cfg.osrm_url)
        dados = exporta.linhas(itens, base, perfil, c["meu_nome"], c["minha_empresa"], self.db.status_de(chat_id))
        data = time.strftime("%Y-%m-%d", time.localtime(b["criada"]))
        nome = f"prospects-{data}-{b['id']}"
        resumo = {"Endereço da busca": b["local"]["descricao"], "Raio (km)": b["raio_km"], "Serviço": b["perfil"],
                  "Data": time.strftime("%d/%m/%Y %H:%M", time.localtime(b["criada"])), "Prospects": len(itens),
                  "Base das rotas": base.descricao,
                  "Origem dos dados": "Google Maps (dados públicos) + sites das empresas",
                  "LGPD": "Use só para contato comercial B2B e atenda pedidos de exclusão."}
        planilha = exporta.salvar_xlsx(self.pasta / f"{nome}.xlsx", dados, resumo, rota)
        mapa = exporta.salvar_kml(self.pasta / f"{nome}.kml", itens, base, f"Prospects {b['perfil']} {data}")
        self.tg.documento(chat_id, planilha, "📄 Planilha com todos os prospects, links de WhatsApp, rotas e colunas "
                                             "para acompanhar os contatos.")
        self.tg.documento(chat_id, mapa, "🗺️ Mapa: importe em mymaps.google.com (Criar mapa → Importar) para ver "
                                         "todos os pontos coloridos por prioridade.")
