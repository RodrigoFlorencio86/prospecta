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
"""

STATUS = {"interessado": "⭐ Interessado", "contatado": "📨 Contatado", "visitar": "📍 Visitar",
          "cliente": "🤝 Cliente", "sem_interesse": "🚫 Sem interesse"}
PADROES = {"perfil": "refrigeracao", "alvos": "", "raio_km": 3.0, "modo": "rapido", "meu_nome": "",
           "minha_empresa": "", "so_novos": 0, "base": ""}


class Banco:
    def __init__(self, caminho):
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.trava = threading.Lock()
        with self.trava, self.con:
            self.con.executescript(ESQUEMA)

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
