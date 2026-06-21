"""Estado persistente (SQLite): binding sessão↔chat, dedup por uuid, kv simples."""
import sqlite3
import threading
import time


class State:
    def __init__(self, path: str) -> None:
        self.path = path
        self._local = threading.local()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn = conn
        return conn

    def _init(self) -> None:
        self._conn().executescript(
            """
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS session_bindings(
                session_id TEXT PRIMARY KEY, chat_id INTEGER, cwd TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS emit_offsets(
                session_id TEXT PRIMARY KEY, last_uuid TEXT);
            """
        )
        self._conn().commit()

    # --- kv ---
    def set_kv(self, key: str, value) -> None:
        c = self._conn()
        c.execute(
            "INSERT INTO kv(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        c.commit()

    def get_kv(self, key: str, default=None):
        row = self._conn().execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # --- session bindings ---
    def bind_session(self, session_id: str, chat_id: int, cwd: str = "") -> None:
        c = self._conn()
        c.execute(
            "INSERT INTO session_bindings(session_id,chat_id,cwd,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET chat_id=excluded.chat_id, "
            "cwd=excluded.cwd, updated_at=excluded.updated_at",
            (session_id, chat_id, cwd, str(time.time())),
        )
        c.commit()

    def chat_for_session(self, session_id: str):
        row = self._conn().execute(
            "SELECT chat_id FROM session_bindings WHERE session_id=?", (session_id,)
        ).fetchone()
        return row["chat_id"] if row else None

    def clear_session(self, session_id: str) -> None:
        c = self._conn()
        c.execute("DELETE FROM session_bindings WHERE session_id=?", (session_id,))
        c.commit()

    # --- dedup ---
    def last_uuid(self, session_id: str):
        row = self._conn().execute(
            "SELECT last_uuid FROM emit_offsets WHERE session_id=?", (session_id,)
        ).fetchone()
        return row["last_uuid"] if row else None

    def set_last_uuid(self, session_id: str, uuid: str) -> None:
        c = self._conn()
        c.execute(
            "INSERT INTO emit_offsets(session_id,last_uuid) VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET last_uuid=excluded.last_uuid",
            (session_id, uuid),
        )
        c.commit()
