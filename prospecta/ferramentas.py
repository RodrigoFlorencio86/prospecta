"""As operações do Prospecta num só lugar, usadas pelo painel, pelo chat com ChatGPT, pelo servidor MCP
(Claude Code / Codex) e pela linha de comando.

Buscas rodam em segundo plano (levam minutos): `iniciar_busca` devolve na hora o número da tarefa e
o andamento fica no banco, visível de qualquer lugar. Tudo é de um único usuário local (id 0)."""
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

from . import busca, exporta, geo, kit, perfis as perfis_mod, relatorio, rotas, telefone
from .banco import STATUS, Banco
from .config import RAIZ
from .motor import Cancelado, ErroMotor, Motor
from .rede import ErroRede

EU = 0  # usuário local


class ErroFerramenta(ValueError):
    """Erro com mensagem para o usuário (vira resposta de ferramenta, não exceção)."""


def _slug(texto, n=40):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:n] or "busca"


def _perfil_dict(p):
    return {"chave": p.chave, "nome": p.nome, "alvos": p.alvos, "sinais": p.sinais, "mensagem": p.mensagem,
            "descricao": p.descricao}


def _perfil_de(d):
    return perfis_mod.Perfil(chave=d.get("chave", "personalizado"), nome=d.get("nome", "Personalizado"),
                             alvos=list(d.get("alvos") or []), descricao=d.get("descricao", ""),
                             sinais=list(d.get("sinais") or []), mensagem=d.get("mensagem") or perfis_mod.MENSAGEM_PADRAO)


class Prospecta:
    def __init__(self, cfg, banco=None, motor=None, geocoder=None, log=None, ligar_motor=True, disparar=None):
        """disparar: como acordar o trabalhador das buscas. Padrão: um processo separado e independente,
        para a busca continuar mesmo se o painel, o Claude Code ou o Codex forem fechados."""
        self.cfg = cfg
        self.db = banco or Banco(Path(cfg.pasta_dados) / "prospecta-local.db")
        self.motor = motor or Motor(cfg.motor_url, cfg.motor_chave)
        self.geo = geocoder or geo.Geocodificador(cfg.nominatim_url, cfg.contato_geocoder)
        self.log = log or (lambda *a: None)
        self.ligar_motor = ligar_motor
        self.saida = Path(getattr(cfg, "pasta_resultados", None) or RAIZ / "resultados")
        self.trava_trabalho = Path(cfg.pasta_dados) / "trabalhador.lock"
        self.disparar = disparar or self._disparar_processo
        self.db.encerrar_orfas()

    # ── configuração ──
    def configuracao(self):
        c = self.db.chat(EU)
        base = None
        if c["base"].count("|") >= 2:
            lat, lon, desc = c["base"].split("|", 2)
            base = {"lat": float(lat), "lon": float(lon), "descricao": desc}
        return {"meu_nome": c["meu_nome"], "minha_empresa": c["minha_empresa"], "base": base,
                "raio_km": c["raio_km"], "modo": c["modo"], "perfil": c["perfil"], "alvos": c["alvos"]}

    def configurar(self, meu_nome=None, minha_empresa=None, base_endereco=None, raio_km=None, modo=None,
                   perfil=None):
        campos = {}
        if meu_nome is not None:
            campos["meu_nome"] = meu_nome.strip()[:60]
        if minha_empresa is not None:
            campos["minha_empresa"] = minha_empresa.strip()[:80]
        if raio_km is not None:
            campos["raio_km"] = self._raio(raio_km)
        if modo is not None:
            if modo not in busca.MODOS:
                raise ErroFerramenta("modo deve ser 'rapido' ou 'completo'")
            campos["modo"] = modo
        if perfil is not None:
            if perfil and perfil not in perfis_mod.carregar():
                raise ErroFerramenta(f"perfil desconhecido: {perfil}")
            campos["perfil"] = perfil
        if base_endereco is not None:
            if base_endereco.strip():
                local = self._geocodificar(base_endereco)
                campos["base"] = f"{local.lat}|{local.lon}|{local.descricao}"
            else:
                campos["base"] = ""
        self.db.ajustar(EU, **campos)
        return self.configuracao()

    def listar_perfis(self):
        return [{"chave": k, "nome": p.nome, "descricao": p.descricao, "alvos": p.alvos}
                for k, p in perfis_mod.carregar().items()]

    # ── buscas ──
    def _raio(self, raio_km):
        try:
            r = float(raio_km)
        except (TypeError, ValueError):
            raise ErroFerramenta("raio_km deve ser um número") from None
        if not 0.3 <= r <= self.cfg.raio_maximo_km:
            raise ErroFerramenta(f"o raio vai de 0,3 a {self.cfg.raio_maximo_km:g} km")
        return r

    def _geocodificar(self, texto):
        try:
            local = self.geo.buscar(texto)
        except ErroRede as ex:
            raise ErroFerramenta(f"o serviço de mapas não respondeu ({ex}); tente de novo ou use 'latitude, longitude'")
        if not local:
            raise ErroFerramenta("endereço não encontrado; tente rua, número e cidade, um CEP ou 'latitude, longitude'")
        return local

    def _montar_perfil(self, perfil=None, alvos=None, servico=None, sinais=None, mensagem=None):
        todos = perfis_mod.carregar()
        base = todos.get(perfil) if perfil else None
        if perfil and not base and not alvos:
            raise ErroFerramenta(f"perfil desconhecido: {perfil}. Use listar_perfis ou informe alvos.")
        if isinstance(alvos, list):
            alvos = ", ".join(alvos)
        if alvos:
            p = perfis_mod.personalizado(perfis_mod.separar_alvos(alvos), base.mensagem if base else None)
            p.sinais = list(base.sinais) if base else []
            p.nome = servico or (base.nome if base else "Personalizado")
        elif base:
            p = perfis_mod.Perfil(**{k: getattr(base, k) for k in ("chave", "nome", "alvos", "descricao", "sinais",
                                                                     "mensagem")})
        else:
            padrao = todos.get(self.db.chat(EU)["perfil"])
            if not padrao:
                raise ErroFerramenta("informe um perfil (listar_perfis) ou os tipos de negócio em alvos")
            p = padrao
        if isinstance(sinais, list):
            sinais = ", ".join(sinais)
        if sinais:
            p.sinais = [s.lower() for s in perfis_mod.separar_alvos(sinais)]
        if mensagem:
            p.mensagem = mensagem
        if not p.alvos:
            raise ErroFerramenta("nenhum tipo de negócio para procurar")
        return p

    def preparar_busca(self, endereco, raio_km=None, perfil=None, alvos=None, servico=None, sinais=None,
                       mensagem=None, modo=None, so_novos=False):
        """Valida e geocodifica -> parâmetros completos da busca (sem rodar)."""
        c = self.db.chat(EU)
        raio = self._raio(raio_km if raio_km is not None else c["raio_km"])
        modo = modo or c["modo"]
        if modo not in busca.MODOS:
            raise ErroFerramenta("modo deve ser 'rapido' ou 'completo'")
        p = self._montar_perfil(perfil, alvos, servico, sinais, mensagem)
        local = self._geocodificar(endereco)
        minutos, areas = busca.estimar_minutos(raio * 1000, modo, len(p.alvos))
        return {"local": {"lat": local.lat, "lon": local.lon, "descricao": local.descricao, "bairro": local.bairro,
                          "cidade": local.cidade},
                "raio_km": raio, "modo": modo, "so_novos": bool(so_novos), "perfil": _perfil_dict(p),
                "estimativa_min": minutos, "areas": areas}

    def iniciar_busca(self, endereco, **opcoes):
        params = self.preparar_busca(endereco, **opcoes)
        desc = f"{params['perfil']['nome']} · {params['raio_km']:g} km · {params['local']['descricao'][:60]}"
        tid = self.db.criar_tarefa(EU, params, desc, "")
        self.disparar()
        fila = sum(t["estado"] in ("fila", "rodando", "cancelar") for t in self.db.tarefas(EU)) - 1
        return {"tarefa_id": tid, "local": params["local"]["descricao"], "procurando": params["perfil"]["alvos"],
                "raio_km": params["raio_km"], "estimativa_min": params["estimativa_min"], "areas": params["areas"],
                "buscas_na_frente": max(0, fila),
                "aviso": "A busca roda em segundo plano, mesmo se esta janela for fechada. Consulte com estado_busca."}

    def estado_busca(self, tarefa_id=None):
        self._vigiar_fila()
        t = self.db.tarefa(int(tarefa_id)) if tarefa_id else (self.db.tarefas(EU, 1) or [None])[0]
        if not t:
            raise ErroFerramenta("nenhuma busca encontrada")
        return self._tarefa_publica(t)

    def listar_tarefas(self, limite=10):
        self._vigiar_fila()
        return [self._tarefa_publica(t) for t in self.db.tarefas(EU, int(limite))]

    @staticmethod
    def _tarefa_publica(t):
        return {"tarefa_id": t["id"], "estado": t["estado"], "descricao": t["descricao"],
                "progresso_pct": int(round(100 * (t["progresso"] or 0))), "lugares_lidos": t["lugares"],
                "mensagem": t["mensagem"], "busca_id": t["busca_id"],
                "estimativa_min": t["parametros"].get("estimativa_min"),
                "criada": time.strftime("%d/%m %H:%M", time.localtime(t["criada"]))}

    def cancelar_busca(self, tarefa_id):
        if not self.db.pedir_cancelamento(int(tarefa_id)):
            raise ErroFerramenta("essa busca não está na fila nem rodando")
        return {"tarefa_id": int(tarefa_id), "estado": "cancelando"}

    # ── trabalhador: um só por computador, em processo próprio ──
    def _vigiar_fila(self):
        """Buscas na fila sem trabalhador (ele morreu ou nunca subiu): acorda um."""
        self.db.encerrar_orfas()
        if self.db.tem_fila(EU) and not TravaArquivo(self.trava_trabalho).ocupada():
            self.disparar()

    def _disparar_processo(self):
        log = Path(self.cfg.pasta_dados) / "trabalhador.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        extra = {}
        if os.name == "nt":
            extra["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            extra["start_new_session"] = True
        with open(log, "ab") as saida:
            subprocess.Popen([sys.executable, "-m", "prospecta", "trabalhar"], cwd=str(RAIZ),
                             stdin=subprocess.DEVNULL, stdout=saida, stderr=saida, close_fds=True, **extra)

    def trabalhar_fila(self, ocioso=2.0):
        """Executa as buscas da fila, uma por vez, até ela esvaziar. Só um trabalhador por vez."""
        trava = TravaArquivo(self.trava_trabalho)
        while True:
            if not trava.tentar():
                return
            try:
                while True:
                    tid = self.db.pegar_proxima(EU)
                    if tid is None:
                        time.sleep(ocioso)
                        tid = self.db.pegar_proxima(EU)
                        if tid is None:
                            break
                    try:
                        self.executar_tarefa(tid)
                    except Exception as ex:  # nunca deixar a tarefa presa em "rodando"
                        self.db.atualizar_tarefa(tid, estado="erro", mensagem=f"erro inesperado: {ex}")
            finally:
                trava.liberar()
            if not self.db.tem_fila(EU):  # nada entrou entre esvaziar e soltar a trava
                return

    def executar_tarefa(self, tid):
        t = self.db.tarefa(tid)
        p = t["parametros"]
        cancelar = threading.Event()
        if t["estado"] == "cancelar":
            self.db.atualizar_tarefa(tid, estado="cancelada", mensagem="cancelada")
            return
        self.db.atualizar_tarefa(tid, estado="rodando", mensagem="começando")
        ultimo = [0.0]

        def progresso(feitos, total, lugares):
            agora = time.monotonic()
            if agora - ultimo[0] < 2:
                return
            ultimo[0] = agora
            if self.db.tarefa(tid)["estado"] == "cancelar":
                cancelar.set()
            self.db.atualizar_tarefa(tid, progresso=min(0.99, feitos / max(total, 1)), lugares=lugares,
                                     mensagem=f"área {min(int(feitos) + 1, total)} de {total}")

        try:
            if self.ligar_motor:
                try:
                    kit.garantir(self.motor, self.cfg.motor_url, log=self.log, saida=kit.SAIDA_ERRO)
                except kit.ErroKit as ex:
                    raise ErroMotor(str(ex)) from ex
            busca_id, info = self._rodar(p, progresso, cancelar)
        except Cancelado:
            self.db.atualizar_tarefa(tid, estado="cancelada", mensagem="cancelada")
            return
        except (ErroMotor, ErroFerramenta) as ex:
            self.db.atualizar_tarefa(tid, estado="erro", mensagem=str(ex))
            return
        self.db.atualizar_tarefa(tid, estado="ok", progresso=1.0, busca_id=busca_id, mensagem=info)

    def _rodar(self, p, progresso, cancelar):
        L = p["local"]
        local = geo.Local(L["lat"], L["lon"], L["descricao"], L.get("bairro", ""), L.get("cidade", ""))
        perfil = _perfil_de(p["perfil"])
        res = busca.prospectar(self.motor, local, p["raio_km"] * 1000, perfil, p["modo"], progresso, cancelar)
        prospects, ocultos = res.prospects, 0
        if p.get("so_novos"):
            vistos = self.db.ja_vistos(EU, [x.chave for x in prospects])
            ocultos = sum(x.chave in vistos for x in prospects)
            prospects = [x for x in prospects if x.chave not in vistos]
        meta = dict(L, perfil=p["perfil"], modo=p["modo"], ocultos=ocultos, brutos=res.brutos,
                    areas=f"{res.pontos_feitos}/{res.pontos_total}", minutos=max(1, round(res.segundos / 60)))
        busca_id = self.db.salvar_busca(EU, meta, p["raio_km"], perfil.nome, prospects, res.avisos)
        info = f"{len(prospects)} prospects" + (f" ({ocultos} já vistos ocultados)" if ocultos else "")
        if res.avisos:
            info += " · avisos: " + "; ".join(res.avisos)[:300]
        return busca_id, info

    def rodar(self, params, progresso=None, cancelar=None):
        """Versão síncrona (linha de comando) de uma busca já preparada -> (busca_id, info)."""
        return self._rodar(params, progresso, cancelar or threading.Event())

    # ── resultados ──
    def _busca(self, busca_id=None):
        b = self.db.busca(EU, int(busca_id) if busca_id else None)
        if not b:
            raise ErroFerramenta("nenhuma busca concluída ainda" if not busca_id else f"busca {busca_id} não existe")
        return b

    def listar_buscas(self, limite=10):
        with self.db.trava:
            rs = self.db.con.execute("SELECT id, criada, local, raio_km, perfil, itens FROM buscas WHERE chat_id=? "
                                     "ORDER BY id DESC LIMIT ?", (EU, int(limite))).fetchall()
        saida = []
        for r in rs:
            itens, L = json.loads(r["itens"]), json.loads(r["local"])
            saida.append({"busca_id": r["id"], "data": time.strftime("%d/%m/%Y %H:%M", time.localtime(r["criada"])),
                          "local": L.get("descricao", ""), "raio_km": r["raio_km"], "servico": r["perfil"],
                          "total": len(itens), "prioridade_A": sum(i["prioridade"] == "A" for i in itens),
                          "com_whatsapp": sum(bool(i["whatsapp"]) for i in itens)})
        return saida

    def _base(self, b):
        cfg = self.configuracao()
        if cfg["base"]:
            return geo.Local(cfg["base"]["lat"], cfg["base"]["lon"], cfg["base"]["descricao"])
        L = b["local"]
        return geo.Local(L["lat"], L["lon"], L["descricao"], L.get("bairro", ""), L.get("cidade", ""))

    def _perfil_busca(self, b):
        if isinstance(b["local"].get("perfil"), dict):
            return _perfil_de(b["local"]["perfil"])
        return perfis_mod.personalizado([b["perfil"]])

    def _status(self):
        with self.db.trava:
            rs = self.db.con.execute("SELECT chave, status, obs FROM prospects WHERE chat_id=?", (EU,)).fetchall()
        return {r["chave"]: (r["status"] or "", r["obs"] or "") for r in rs}

    def consultar_prospects(self, busca_id=None, prioridade=None, com_whatsapp=None, com_email=None, texto=None,
                            bairro=None, status=None, max_km=None, min_avaliacoes=None, ordenar="nota", limite=20,
                            pagina=1):
        b = self._busca(busca_id)
        st = self._status()
        itens = []
        for i, d in enumerate(b["itens"]):
            s, obs = st.get(d["chave"], ("", ""))
            itens.append((i, d, s, obs))

        def ok(i, d, s, obs):
            if prioridade and d["prioridade"] not in str(prioridade).upper():
                return False
            if com_whatsapp is not None and bool(d["whatsapp"]) != bool(com_whatsapp):
                return False
            if com_email is not None and bool(d["emails"]) != bool(com_email):
                return False
            if texto and str(texto).lower() not in " ".join(str(d.get(k, "")) for k in
                                                              ("nome", "categoria", "alvo", "endereco", "bairro")).lower():
                return False
            if bairro and str(bairro).lower() not in (d.get("bairro") or "").lower():
                return False
            if status is not None and s != ("" if status in ("", "sem_status", "nenhum") else status):
                return False
            if max_km is not None and d["distancia_m"] > float(max_km) * 1000:
                return False
            if min_avaliacoes is not None and _num(d.get("avaliacoes")) < float(min_avaliacoes):
                return False
            return True

        filtrados = [x for x in itens if ok(*x)]
        chaves = {"nota": lambda x: (-x[1]["nota"], x[1]["distancia_m"]), "distancia": lambda x: x[1]["distancia_m"],
                  "avaliacoes": lambda x: -_num(x[1].get("avaliacoes"))}
        filtrados.sort(key=chaves.get(ordenar, chaves["nota"]))
        limite = max(1, min(int(limite or 20), 100))
        ini = (max(1, int(pagina or 1)) - 1) * limite
        return {"busca_id": b["id"], "total_na_busca": len(b["itens"]), "total_filtrado": len(filtrados),
                "pagina": max(1, int(pagina or 1)),
                "prospects": [_compacto(i, d, s, obs) for i, d, s, obs in filtrados[ini:ini + limite]]}

    def busca_completa(self, busca_id=None):
        """Tudo de uma busca para o painel: itens com status, mensagem e links prontos."""
        b = self._busca(busca_id)
        perfil = self._perfil_busca(b)
        cfg = self.configuracao()
        base = self._base(b)
        st = self._status()
        itens = []
        for d in b["itens"]:
            p = busca.Prospect.de_dict(d)
            msg = busca.mensagem_para(p, perfil, cfg["meu_nome"], cfg["minha_empresa"])
            s, obs = st.get(p.chave, ("", ""))
            itens.append(dict(d, status=s, obs=obs,
                              link_whatsapp=telefone.link_whatsapp(p.whatsapp, msg) if p.whatsapp else "",
                              link_rota=rotas.link_ate((base.lat, base.lon), p.lat, p.lon),
                              link_waze=rotas.link_waze(p.lat, p.lon)))
        L = b["local"]
        return {"busca_id": b["id"], "data": time.strftime("%d/%m/%Y %H:%M", time.localtime(b["criada"])),
                "local": {k: L.get(k) for k in ("lat", "lon", "descricao", "bairro", "cidade")},
                "base": {"lat": base.lat, "lon": base.lon, "descricao": base.descricao},
                "raio_km": b["raio_km"], "servico": perfil.nome, "alvos": perfil.alvos, "avisos": b.get("avisos") or [],
                "ocultos": L.get("ocultos") or 0, "itens": itens}

    def detalhar_prospect(self, chave, busca_id=None):
        b, d = self._achar(chave, busca_id)
        p = busca.Prospect.de_dict(d)
        perfil = self._perfil_busca(b)
        cfg = self.configuracao()
        base = self._base(b)
        msg = busca.mensagem_para(p, perfil, cfg["meu_nome"], cfg["minha_empresa"])
        reg = self.db.prospect(EU, chave) or {}
        return dict(d, status=reg.get("status", ""), obs=reg.get("obs", ""), mensagem_sugerida=msg,
                    link_whatsapp=telefone.link_whatsapp(p.whatsapp, msg) if p.whatsapp else "",
                    link_rota=rotas.link_ate((base.lat, base.lon), p.lat, p.lon), link_waze=rotas.link_waze(p.lat, p.lon),
                    busca_id=b["id"])

    def _achar(self, chave, busca_id=None):
        if busca_id:
            b = self._busca(busca_id)
            for d in b["itens"]:
                if d["chave"] == chave:
                    return b, d
        else:
            with self.db.trava:
                ids = [r[0] for r in self.db.con.execute("SELECT id FROM buscas WHERE chat_id=? ORDER BY id DESC LIMIT 50",
                                                         (EU,))]
            for bid in ids:
                b = self.db.busca(EU, bid)
                for d in b["itens"]:
                    if d["chave"] == chave:
                        return b, d
        raise ErroFerramenta(f"prospect {chave} não encontrado")

    def marcar_prospect(self, chave, status=None, observacao=None):
        if status is not None and status not in STATUS and status != "":
            raise ErroFerramenta(f"status deve ser um de: {', '.join(STATUS)} (ou vazio para limpar)")
        self._achar(chave)
        self.db.marcar(EU, chave, status=status, obs=observacao)
        reg = self.db.prospect(EU, chave)
        return {"chave": chave, "nome": reg["nome"], "status": reg["status"], "observacao": reg["obs"]}

    def mensagem_whatsapp(self, chave, modelo=None):
        b, d = self._achar(chave)
        p = busca.Prospect.de_dict(d)
        perfil = self._perfil_busca(b)
        if modelo:
            perfil.mensagem = modelo
        cfg = self.configuracao()
        msg = busca.mensagem_para(p, perfil, cfg["meu_nome"], cfg["minha_empresa"])
        return {"chave": chave, "nome": p.nome, "mensagem": msg, "whatsapp": p.whatsapp_status or "sem WhatsApp",
                "link": telefone.link_whatsapp(p.whatsapp, msg) if p.whatsapp else "",
                "aviso": "O link só abre a conversa; quem envia é o usuário."}

    def planejar_rota(self, busca_id=None, quantidade=8, chaves=None, prioridade=None):
        b = self._busca(busca_id)
        st = self._status()
        fora = {"sem_interesse", "cliente"}
        itens = [busca.Prospect.de_dict(d) for d in b["itens"]]
        if chaves:
            pedidas = list(chaves)
            itens = sorted([p for p in itens if p.chave in pedidas], key=lambda p: pedidas.index(p.chave))
        else:
            itens = [p for p in itens if st.get(p.chave, ("",))[0] not in fora
                     and (not prioridade or p.prioridade in str(prioridade).upper())]
        itens = itens[:max(1, min(int(quantidade or 8), 25))]
        if not itens:
            raise ErroFerramenta("nenhum prospect para a rota com esses critérios")
        base = self._base(b)
        r = rotas.planejar(base, itens, volta=True, osrm_url=self.cfg.osrm_url)
        return {"saida": base.descricao, "paradas": [{"ordem": i, "chave": p.chave, "nome": p.nome, "bairro": p.bairro,
                                                       "endereco": p.endereco, "telefone": p.telefone}
                                                      for i, p in enumerate(r["ordem"], 1)],
                "km": r["km"], "minutos_dirigindo": r["minutos_carro"], "minutos_com_visitas": r["minutos"],
                "estimado": r["estimado"], "links_google_maps": r["links"]}

    def resumo_funil(self):
        contagem, ativos = self.db.funil(EU)
        return {"por_status": {STATUS.get(k, "sem status") if k else "sem status": v for k, v in contagem.items()},
                "em_andamento": [{"chave": a["chave"], "nome": a["nome"], "status": a["status"], "observacao": a["obs"]}
                                 for a in ativos]}

    def exportar(self, busca_id=None, top=15):
        """Gera relatório HTML, planilha, KML, JSON e resumo.md da busca -> caminhos."""
        b = self._busca(busca_id)
        itens = [busca.Prospect.de_dict(d) for d in b["itens"]]
        perfil = self._perfil_busca(b)
        cfg = self.configuracao()
        base = self._base(b)
        L = b["local"]
        pasta = self.saida / (time.strftime("%Y-%m-%d_%H%M", time.localtime(b["criada"]))
                              + f"_{_slug(b['perfil'], 25)}_{_slug(L.get('descricao'), 30)}_{b['id']}")
        pasta.mkdir(parents=True, exist_ok=True)
        st = {k: (STATUS.get(s, s), "", o) for k, (s, o) in self._status().items() if s or o}
        rota = rotas.planejar(base, itens[:10], osrm_url=self.cfg.osrm_url) if itens else None
        dados = exporta.linhas(itens, base, perfil, cfg["meu_nome"], cfg["minha_empresa"], st)
        resumo = {"Endereço": L.get("descricao", ""), "Raio (km)": b["raio_km"], "Serviço": perfil.nome,
                  "Procurado": ", ".join(perfil.alvos), "Data": time.strftime("%d/%m/%Y %H:%M", time.localtime(b["criada"])),
                  "Base das rotas": base.descricao, "Origem dos dados": "Google Maps (dados públicos) e sites das empresas",
                  "LGPD": "Use só para contato comercial B2B, identifique-se e atenda pedidos de exclusão."}
        arquivos = {
            "relatorio": relatorio.gerar(pasta / "relatorio.html", itens, base, perfil, b["raio_km"] * 1000,
                                         cfg["meu_nome"], cfg["minha_empresa"], rota,
                                         f"{perfil.nome} — {L.get('bairro') or L.get('cidade') or 'busca'}"),
            "planilha": exporta.salvar_xlsx(pasta / "prospects.xlsx", dados, resumo, rota),
            "mapa": exporta.salvar_kml(pasta / "prospects.kml", itens, base, f"Prospects {perfil.nome}"),
        }
        (pasta / "prospects.json").write_text(json.dumps(b["itens"], ensure_ascii=False, indent=1), encoding="utf-8")
        arquivos["json"] = pasta / "prospects.json"
        arquivos["resumo"] = exporta.salvar_resumo_md(pasta / "resumo.md", b, perfil, base, itens, dados, rota, top)
        return {"busca_id": b["id"], "pasta": str(pasta.resolve()),
                "arquivos": {k: str(Path(v).resolve()) for k, v in arquivos.items()}}


class TravaArquivo:
    """Trava entre processos num arquivo (fcntl no Linux/Mac, msvcrt no Windows)."""

    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self.f = None

    def tentar(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.caminho, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self.f = f
        return True

    def liberar(self):
        if not self.f:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()
            self.f = None

    def ocupada(self):
        if self.tentar():
            self.liberar()
            return False
        return True


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _compacto(i, d, status, obs):
    return {"n": i + 1, "chave": d["chave"], "nome": d["nome"], "categoria": d["categoria"], "bairro": d["bairro"],
            "distancia_km": round(d["distancia_m"] / 1000, 1), "telefone": d["telefone"],
            "whatsapp": d["whatsapp_status"] or "", "email": d["emails"], "instagram": bool(d["instagram"]),
            "site_proprio": d["site_proprio"], "nota": d["nota"], "prioridade": d["prioridade"],
            "nota_google": d["nota_google"], "avaliacoes": d["avaliacoes"], "sinais": d["sinais"],
            "status": status, "observacao": obs}


# ── Definição das ferramentas (mesmas para o chat do ChatGPT e para o MCP) ──

_TXT = {"type": "string"}
FERRAMENTAS = [
    {"nome": "listar_perfis", "metodo": "listar_perfis",
     "descricao": "Lista os serviços prontos (perfis) com os tipos de negócio que cada um procura.",
     "parametros": {}},
    {"nome": "ver_configuracao", "metodo": "configuracao",
     "descricao": "Mostra a configuração do usuário: nome, empresa, endereço-base das rotas, raio e modo padrão.",
     "parametros": {}},
    {"nome": "configurar", "metodo": "configurar",
     "descricao": "Salva preferências do usuário. Só mude o que ele pediu.",
     "parametros": {"meu_nome": dict(_TXT, description="nome de quem assina as mensagens"),
                    "minha_empresa": dict(_TXT, description="nome da empresa do usuário"),
                    "base_endereco": dict(_TXT, description="endereço da empresa, ponto de partida das rotas ('' limpa)"),
                    "raio_km": {"type": "number", "description": "raio padrão em km (0,3 a 15)"},
                    "modo": {"type": "string", "enum": ["rapido", "completo"]},
                    "perfil": dict(_TXT, description="chave do perfil padrão")}},
    {"nome": "iniciar_busca", "metodo": "iniciar_busca",
     "descricao": ("Começa uma busca de prospects num raio em volta de um endereço. Roda em segundo plano e leva de "
                   "5 a 30 minutos: devolve na hora o tarefa_id e a estimativa. Antes, confirme com o usuário o "
                   "endereço, o raio e o que procurar. Uma busca por vez."),
     "parametros": {"endereco": dict(_TXT, description="rua e número com cidade, CEP ou 'latitude, longitude'"),
                    "raio_km": {"type": "number", "description": "raio em km; padrão do usuário (em geral 3). Sugira 1 a 5"},
                    "perfil": dict(_TXT, description="chave de um serviço pronto (veja listar_perfis)"),
                    "alvos": {"type": "array", "items": _TXT,
                              "description": "tipos de negócio a procurar, como digitados no Google Maps, em português (5 a 12)"},
                    "servico": dict(_TXT, description="nome do serviço do usuário, quando usar alvos"),
                    "sinais": {"type": "array", "items": _TXT,
                               "description": "palavras nas avaliações que indicam necessidade do serviço"},
                    "mensagem": dict(_TXT, description="modelo da mensagem de WhatsApp com {prospect} {bairro} {meu_nome} {minha_empresa}"),
                    "modo": {"type": "string", "enum": ["rapido", "completo"],
                             "description": "completo acha mais e lê avaliações, mas demora várias vezes mais"},
                    "so_novos": {"type": "boolean", "description": "esconder empresas já vistas em buscas anteriores"}},
     "obrigatorios": ["endereco"]},
    {"nome": "estado_busca", "metodo": "estado_busca",
     "descricao": "Andamento de uma busca (sem tarefa_id: a mais recente). Quando estado='ok', traz o busca_id.",
     "parametros": {"tarefa_id": {"type": "integer"}}},
    {"nome": "listar_tarefas", "metodo": "listar_tarefas", "descricao": "Buscas recentes e em andamento, com o estado.",
     "parametros": {"limite": {"type": "integer"}}},
    {"nome": "cancelar_busca", "metodo": "cancelar_busca", "descricao": "Cancela uma busca na fila ou rodando.",
     "parametros": {"tarefa_id": {"type": "integer"}}, "obrigatorios": ["tarefa_id"]},
    {"nome": "listar_buscas", "metodo": "listar_buscas", "descricao": "Buscas concluídas, da mais nova para a mais antiga.",
     "parametros": {"limite": {"type": "integer"}}},
    {"nome": "consultar_prospects", "metodo": "consultar_prospects",
     "descricao": ("Lista e filtra os prospects de uma busca (sem busca_id: a última). Devolve dados resumidos; "
                   "use detalhar_prospect para links e mensagem."),
     "parametros": {"busca_id": {"type": "integer"},
                    "prioridade": dict(_TXT, description="A, B, C ou combinação como 'AB'"),
                    "com_whatsapp": {"type": "boolean"}, "com_email": {"type": "boolean"},
                    "texto": dict(_TXT, description="trecho do nome, categoria, endereço ou bairro"),
                    "bairro": _TXT,
                    "status": {"type": "string", "enum": ["", "interessado", "contatado", "visitar", "cliente",
                                                          "sem_interesse"],
                               "description": "'' = sem status"},
                    "max_km": {"type": "number"}, "min_avaliacoes": {"type": "number"},
                    "ordenar": {"type": "string", "enum": ["nota", "distancia", "avaliacoes"]},
                    "limite": {"type": "integer", "description": "até 100, padrão 20"}, "pagina": {"type": "integer"}}},
    {"nome": "detalhar_prospect", "metodo": "detalhar_prospect",
     "descricao": "Ficha completa de um prospect: contatos, links de WhatsApp (com mensagem), rota, Waze, status.",
     "parametros": {"chave": _TXT, "busca_id": {"type": "integer"}}, "obrigatorios": ["chave"]},
    {"nome": "marcar_prospect", "metodo": "marcar_prospect",
     "descricao": "Registra o status e/ou uma observação de um prospect (mini-CRM).",
     "parametros": {"chave": _TXT,
                    "status": {"type": "string", "enum": ["", "interessado", "contatado", "visitar", "cliente",
                                                          "sem_interesse"]},
                    "observacao": _TXT}, "obrigatorios": ["chave"]},
    {"nome": "mensagem_whatsapp", "metodo": "mensagem_whatsapp",
     "descricao": ("Monta a mensagem de abordagem e o link wa.me para um prospect. Nunca envia: o usuário clica e "
                   "envia. 'modelo' pode reescrever o texto com {prospect} {bairro} {meu_nome} {minha_empresa}."),
     "parametros": {"chave": _TXT, "modelo": _TXT}, "obrigatorios": ["chave"]},
    {"nome": "planejar_rota", "metodo": "planejar_rota",
     "descricao": ("Rota otimizada de visitas saindo da base do usuário, com links do Google Maps. Escolhe os "
                   "melhores por nota (sem 'cliente' e 'sem interesse') ou as chaves informadas, na ordem."),
     "parametros": {"busca_id": {"type": "integer"}, "quantidade": {"type": "integer", "description": "1 a 25"},
                    "chaves": {"type": "array", "items": _TXT}, "prioridade": _TXT}},
    {"nome": "resumo_funil", "metodo": "resumo_funil", "descricao": "Contagem por status e prospects em andamento.",
     "parametros": {}},
    {"nome": "exportar", "metodo": "exportar",
     "descricao": "Gera relatório HTML, planilha Excel, mapa KML e resumo de uma busca; devolve os caminhos.",
     "parametros": {"busca_id": {"type": "integer"}}},
]


def schema(f):
    return {"type": "object", "properties": f["parametros"], "required": f.get("obrigatorios", []),
            "additionalProperties": False}


def chamar(app, nome, argumentos):
    """Executa uma ferramenta -> (resultado_dict, erro_bool). Erros viram texto para o modelo."""
    f = next((x for x in FERRAMENTAS if x["nome"] == nome), None)
    if not f:
        return {"erro": f"ferramenta desconhecida: {nome}"}, True
    if not isinstance(argumentos, dict):
        return {"erro": "argumentos devem ser um objeto JSON"}, True
    args = {k: v for k, v in argumentos.items() if k in f["parametros"] and v is not None}
    faltando = [k for k in f.get("obrigatorios", []) if k not in args]
    if faltando:
        return {"erro": f"faltou: {', '.join(faltando)}"}, True
    try:
        return getattr(app, f["metodo"])(**args), False
    except (ErroFerramenta, ErroMotor, ErroRede) as ex:
        return {"erro": str(ex)}, True
    except (TypeError, ValueError) as ex:
        return {"erro": f"argumentos inválidos: {ex}"}, True
