"""SQLite: preferências de cada chat, histórico de buscas e um mini-CRM de status dos prospects."""
import json
import sqlite3
import threading
import time
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    perfil TEXT DEFAULT 'refrigeracao',
    alvos TEXT DEFAULT '',
    raio_km REAL DEFAULT 3,
    modo TEXT DEFAULT 'rapido',
    meu_nome TEXT DEFAULT '',
    minha_empresa TEXT DEFAULT '',
    so_novos INTEGER DEFAULT 0,
    base TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS buscas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    criada REAL NOT NULL,
    local TEXT NOT NULL,
    raio_km REAL NOT NULL,
    perfil TEXT NOT NULL,
    itens TEXT NOT NULL,
    avisos TEXT DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS prospects (
    chat_id INTEGER NOT NULL,
    chave TEXT NOT NULL,
    nome TEXT,
    dados TEXT,
    status TEXT DEFAULT '',
    obs TEXT DEFAULT '',
    visto_em REAL,
    atualizado REAL,
    PRIMARY KEY (chat_id, chave)
);
CREATE INDEX IF NOT EXISTS buscas_chat ON buscas(chat_id, criada);
CREATE TABLE IF NOT EXISTS tarefas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    criada REAL NOT NULL,
    atualizada REAL NOT NULL,
    estado TEXT NOT NULL,          -- fila, rodando, ok, erro, cancelar, cancelada
    parametros TEXT NOT NULL,
    descricao TEXT DEFAULT '',
    progresso REAL DEFAULT 0,
    lugares INTEGER DEFAULT 0,
    mensagem TEXT DEFAULT '',
    busca_id INTEGER,
    dono TEXT DEFAULT ''
);
"""
CONVERSAS = """
CREATE TABLE IF NOT EXISTS conversas (
    id TEXT PRIMARY KEY,
    chat_id INTEGER NOT NULL,
    criada REAL NOT NULL,
    atualizada REAL NOT NULL,
    titulo TEXT DEFAULT '',
    busca_id INTEGER,
    modelo TEXT DEFAULT '',
    historico TEXT NOT NULL,
    mensagens TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conversas_chat ON conversas(chat_id, atualizada);
"""
FINAIS = ("ok", "erro", "cancelada")

STATUS = {"interessado": "⭐ Interessado", "contatado": "📨 Contatado", "visitar": "📍 Visitar",
          "cliente": "🤝 Cliente", "sem_interesse": "🚫 Sem interesse"}
PADROES = {"perfil": "refrigeracao", "alvos": "", "raio_km": 3.0, "modo": "rapido", "meu_nome": "",
           "minha_empresa": "", "so_novos": 0, "base": ""}


class Banco:
    def __init__(self, caminho):
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(caminho), check_same_thread=False, timeout=15)
        self.con.row_factory = sqlite3.Row
        try:  # painel, MCP e linha de comando podem abrir o mesmo arquivo ao mesmo tempo
            self.con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            pass
        self.trava = threading.Lock()
        with self.trava, self.con:
            self.con.executescript(ESQUEMA)
            self.con.executescript(CONVERSAS)

    def fechar(self):
        with self.trava:
            self.con.close()

    # ── preferências ──
    def chat(self, chat_id):
        with self.trava:
            r = self.con.execute("SELECT * FROM chats WHERE chat_id=?", (chat_id,)).fetchone()
        d = dict(PADROES, **(dict(r) if r else {}))
        d["chat_id"] = chat_id
        return d

    def ajustar(self, chat_id, **campos):
        campos = {k: v for k, v in campos.items() if k in PADROES}
        if not campos:
            return
        cols = ", ".join(campos)
        marcas = ", ".join("?" for _ in campos)
        atualiza = ", ".join(f"{k}=excluded.{k}" for k in campos)
        with self.trava, self.con:
            self.con.execute(f"INSERT INTO chats (chat_id, {cols}) VALUES (?, {marcas}) "
                             f"ON CONFLICT(chat_id) DO UPDATE SET {atualiza}", (chat_id, *campos.values()))

    # ── buscas ──
    def salvar_busca(self, chat_id, local, raio_km, perfil, prospects, avisos):
        agora = time.time()
        itens = [p.como_dict() for p in prospects]
        with self.trava, self.con:
            cur = self.con.execute(
                "INSERT INTO buscas (chat_id, criada, local, raio_km, perfil, itens, avisos) VALUES (?,?,?,?,?,?,?)",
                (chat_id, agora, json.dumps(local, ensure_ascii=False), raio_km, perfil,
                 json.dumps(itens, ensure_ascii=False), json.dumps(avisos, ensure_ascii=False)))
            for p in itens:
                self.con.execute(
                    "INSERT INTO prospects (chat_id, chave, nome, dados, visto_em, atualizado) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(chat_id, chave) DO UPDATE SET dados=excluded.dados, nome=excluded.nome",
                    (chat_id, p["chave"], p["nome"], json.dumps(p, ensure_ascii=False), agora, agora))
            return cur.lastrowid

    def busca(self, chat_id, busca_id=None):
        """A busca pedida (ou a última do chat) -> dict com local, itens, ... ou None."""
        with self.trava:
            if busca_id is None:
                r = self.con.execute("SELECT * FROM buscas WHERE chat_id=? ORDER BY id DESC LIMIT 1",
                                     (chat_id,)).fetchone()
            else:
                r = self.con.execute("SELECT * FROM buscas WHERE chat_id=? AND id=?", (chat_id, busca_id)).fetchone()
        if not r:
            return None
        d = dict(r)
        for k in ("local", "itens", "avisos"):
            d[k] = json.loads(d[k])
        return d

    def buscas_hoje(self, chat_id):
        inicio = time.time() - 86400
        with self.trava:
            return self.con.execute("SELECT COUNT(*) FROM buscas WHERE chat_id=? AND criada>?",
                                    (chat_id, inicio)).fetchone()[0]

    def ja_vistos(self, chat_id, chaves):
        if not chaves:
            return set()
        with self.trava:
            vistos = set()
            lista = list(chaves)
            for i in range(0, len(lista), 500):
                parte = lista[i:i + 500]
                q = f"SELECT chave FROM prospects WHERE chat_id=? AND chave IN ({','.join('?' * len(parte))})"
                vistos |= {r[0] for r in self.con.execute(q, (chat_id, *parte))}
        return vistos

    # ── mini-CRM ──
    def marcar(self, chat_id, chave, status=None, obs=None):
        sets, vals = ["atualizado=?"], [time.time()]
        if status is not None:
            sets.append("status=?")
            vals.append(status)
        if obs is not None:
            sets.append("obs=?")
            vals.append(obs[:1000])
        with self.trava, self.con:
            n = self.con.execute(f"UPDATE prospects SET {', '.join(sets)} WHERE chat_id=? AND chave=?",
                                 (*vals, chat_id, chave)).rowcount
        return n > 0

    def prospect(self, chat_id, chave):
        with self.trava:
            r = self.con.execute("SELECT * FROM prospects WHERE chat_id=? AND chave=?", (chat_id, chave)).fetchone()
        return dict(r) if r else None

    def status_de(self, chat_id):
        """{chave: (status legível, data, obs)} para a planilha."""
        with self.trava:
            rs = self.con.execute("SELECT chave, status, obs, atualizado FROM prospects WHERE chat_id=? AND "
                                  "(status != '' OR obs != '')", (chat_id,)).fetchall()
        return {r["chave"]: (STATUS.get(r["status"], r["status"]), time.strftime("%d/%m/%Y",
                time.localtime(r["atualizado"])) if r["atualizado"] else "", r["obs"] or "") for r in rs}

    def funil(self, chat_id):
        with self.trava:
            contagem = dict(self.con.execute("SELECT status, COUNT(*) FROM prospects WHERE chat_id=? GROUP BY status",
                                             (chat_id,)).fetchall())
            ativos = self.con.execute("SELECT chave, nome, status, obs FROM prospects WHERE chat_id=? AND status IN "
                                      "('interessado','visitar','contatado') ORDER BY atualizado DESC LIMIT 30",
                                      (chat_id,)).fetchall()
        return contagem, [dict(r) for r in ativos]

    # ── tarefas (buscas em segundo plano, visíveis para painel, chat e MCP) ──
    def criar_tarefa(self, chat_id, parametros, descricao, dono):
        agora = time.time()
        with self.trava, self.con:
            return self.con.execute(
                "INSERT INTO tarefas (chat_id, criada, atualizada, estado, parametros, descricao, dono) "
                "VALUES (?,?,?,?,?,?,?)", (chat_id, agora, agora, "fila", json.dumps(parametros, ensure_ascii=False),
                                         descricao, dono)).lastrowid

    def tarefa(self, tarefa_id):
        with self.trava:
            r = self.con.execute("SELECT * FROM tarefas WHERE id=?", (tarefa_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["parametros"] = json.loads(d["parametros"])
        return d

    def tarefas(self, chat_id, limite=20):
        with self.trava:
            rs = self.con.execute("SELECT * FROM tarefas WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                                  (chat_id, limite)).fetchall()
        saida = []
        for r in rs:
            d = dict(r)
            d["parametros"] = json.loads(d["parametros"])
            saida.append(d)
        return saida

    def atualizar_tarefa(self, tarefa_id, **campos):
        campos["atualizada"] = time.time()
        sets = ", ".join(f"{k}=?" for k in campos)
        with self.trava, self.con:
            self.con.execute(f"UPDATE tarefas SET {sets} WHERE id=?", (*campos.values(), tarefa_id))

    def pedir_cancelamento(self, tarefa_id):
        with self.trava, self.con:
            n = self.con.execute("UPDATE tarefas SET estado = CASE estado WHEN 'fila' THEN 'cancelada' ELSE 'cancelar' "
                                 "END, atualizada=? WHERE id=? AND estado IN ('fila','rodando')",
                                 (time.time(), tarefa_id)).rowcount
        return n > 0

    def outra_rodando(self, tarefa_id, validade=90):
        """Há outra busca rodando (com sinal de vida recente), em qualquer processo?"""
        with self.trava:
            return self.con.execute("SELECT COUNT(*) FROM tarefas WHERE id!=? AND estado IN ('rodando','cancelar') "
                                    "AND atualizada>?", (tarefa_id, time.time() - validade)).fetchone()[0] > 0

    def encerrar_orfas(self, validade=120):
        """Buscas que pararam de dar sinal de vida (o processo que as rodava foi fechado)."""
        with self.trava, self.con:
            self.con.execute("UPDATE tarefas SET estado='erro', mensagem='interrompida: o programa que fazia a busca "
                             "foi fechado' WHERE estado IN ('rodando','cancelar') AND atualizada<?",
                             (time.time() - validade,))

    def tem_fila(self, chat_id):
        with self.trava:
            return self.con.execute("SELECT COUNT(*) FROM tarefas WHERE chat_id=? AND estado='fila'",
                                    (chat_id,)).fetchone()[0] > 0

    def pegar_proxima(self, chat_id):
        """Reserva a busca mais antiga da fila (de forma atômica entre processos) -> id ou None."""
        with self.trava, self.con:
            for (tid,) in self.con.execute("SELECT id FROM tarefas WHERE chat_id=? AND estado='fila' ORDER BY id LIMIT 5",
                                           (chat_id,)).fetchall():
                if self.con.execute("UPDATE tarefas SET estado='rodando', atualizada=? WHERE id=? AND estado='fila'",
                                    (time.time(), tid)).rowcount:
                    return tid
        return None

    def sinal_de_vida(self, dono):
        """Mantém vivas as buscas na fila deste processo (as que rodam já se atualizam sozinhas)."""
        with self.trava, self.con:
            self.con.execute("UPDATE tarefas SET atualizada=? WHERE dono=? AND estado='fila'", (time.time(), dono))

    def proxima_tarefa(self, dono):
        with self.trava:
            r = self.con.execute("SELECT id FROM tarefas WHERE dono=? AND estado='fila' ORDER BY id LIMIT 1",
                                 (dono,)).fetchone()
        return r[0] if r else None

    # ── conversas do chat do painel ──
    def salvar_conversa(self, chat_id, c):
        with self.trava, self.con:
            self.con.execute(
                "INSERT INTO conversas (id, chat_id, criada, atualizada, titulo, busca_id, modelo, historico, mensagens) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET atualizada=excluded.atualizada, "
                "titulo=excluded.titulo, busca_id=excluded.busca_id, modelo=excluded.modelo, "
                "historico=excluded.historico, mensagens=excluded.mensagens",
                (c["id"], chat_id, c["criada"], time.time(), c.get("titulo", ""), c.get("busca_id"), c.get("modelo", ""),
                 json.dumps(c["historico"], ensure_ascii=False), json.dumps(c["mensagens"], ensure_ascii=False)))

    def conversa_salva(self, chat_id, cid):
        with self.trava:
            r = self.con.execute("SELECT * FROM conversas WHERE chat_id=? AND id=?", (chat_id, cid)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["historico"], d["mensagens"] = json.loads(d["historico"]), json.loads(d["mensagens"])
        return d

    def conversas_salvas(self, chat_id, limite=50):
        with self.trava:
            rs = self.con.execute("SELECT id, criada, atualizada, titulo, busca_id, modelo, "
                                  "json_array_length(mensagens) AS n FROM conversas WHERE chat_id=? "
                                  "ORDER BY atualizada DESC LIMIT ?", (chat_id, int(limite))).fetchall()
        return [dict(r) for r in rs]

    def apagar_conversa(self, chat_id, cid):
        with self.trava, self.con:
            return self.con.execute("DELETE FROM conversas WHERE chat_id=? AND id=?", (chat_id, cid)).rowcount > 0
