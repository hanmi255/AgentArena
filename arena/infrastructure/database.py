import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from arena.domain.catalog import STRATEGIES
from arena.infrastructure.config import MODEL_DEFAULTS
from arena.domain.models import ModelSettings
from arena.infrastructure.storage_permissions import prepare_sqlite_files


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Database:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        prepare_sqlite_files(directory)
        self.path = directory / "arena.sqlite"

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS strategies (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL,
                    built_in INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS model_profiles (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, config TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS execution_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id),
                    state TEXT NOT NULL, interval REAL NOT NULL, owner TEXT NOT NULL DEFAULT '',
                    lease_version INTEGER NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0, error TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_active_arena ON execution_jobs(arena_id) WHERE state IN ('queued','running');
                CREATE TABLE IF NOT EXISTS command_outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL UNIQUE REFERENCES execution_jobs(id), published_at REAL
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, config TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS arenas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, scenario TEXT NOT NULL,
                    seed INTEGER NOT NULL, total_rounds INTEGER NOT NULL, current_round INTEGER NOT NULL DEFAULT 0,
                    initial_capital INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'ready',
                    experiment_id INTEGER REFERENCES experiments(id), error TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE TABLE IF NOT EXISTS merchants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id) ON DELETE CASCADE,
                    slot INTEGER NOT NULL, name TEXT NOT NULL, color TEXT NOT NULL,
                    strategy_id TEXT NOT NULL, strategy_config TEXT NOT NULL, mode TEXT NOT NULL,
                    cash INTEGER NOT NULL CHECK(cash >= 0), memory TEXT NOT NULL DEFAULT '',
                    UNIQUE(arena_id,slot)
                );
                CREATE TABLE IF NOT EXISTS inventory (
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity >= 0),
                    book_value INTEGER NOT NULL CHECK(book_value >= 0), price INTEGER NOT NULL CHECK(price > 0),
                    PRIMARY KEY(merchant_id,product_id)
                );
                CREATE TABLE IF NOT EXISTS rounds (
                    arena_id INTEGER NOT NULL REFERENCES arenas(id) ON DELETE CASCADE,
                    number INTEGER NOT NULL, snapshot TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(arena_id,number)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id) ON DELETE CASCADE,
                    round_number INTEGER NOT NULL, merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
                    plan TEXT NOT NULL, observation TEXT NOT NULL, tools TEXT NOT NULL, stages TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
                    UNIQUE(arena_id,round_number,merchant_id)
                );
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id) ON DELETE CASCADE,
                    round_number INTEGER NOT NULL, merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, product_id TEXT NOT NULL DEFAULT '', quantity INTEGER NOT NULL,
                    amount INTEGER NOT NULL, balance INTEGER NOT NULL CHECK(balance >= 0),
                    UNIQUE(arena_id,round_number,merchant_id,kind,product_id)
                );
                CREATE INDEX IF NOT EXISTS ledger_arena ON ledger(arena_id,round_number);
                CREATE INDEX IF NOT EXISTS decisions_arena ON decisions(arena_id,round_number);
                CREATE TABLE IF NOT EXISTS decision_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id),
                    round_number INTEGER NOT NULL, merchant_id INTEGER, node TEXT NOT NULL,
                    status TEXT NOT NULL, label TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                );
                CREATE INDEX IF NOT EXISTS events_cursor ON decision_events(arena_id,id);
                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id),
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id), round_number INTEGER NOT NULL,
                    context TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL,
                    UNIQUE(arena_id,merchant_id,round_number)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id),
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id), round_number INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', proposal TEXT NOT NULL, response TEXT,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    resolved_at TEXT,
                    UNIQUE(arena_id,merchant_id,round_number)
                );
                CREATE TABLE IF NOT EXISTS negotiation_sessions (
                    arena_id INTEGER NOT NULL REFERENCES arenas(id), round_number INTEGER NOT NULL,
                    merchant_id INTEGER NOT NULL REFERENCES merchants(id), result TEXT NOT NULL,
                    PRIMARY KEY(arena_id,round_number,merchant_id)
                );
                CREATE TABLE IF NOT EXISTS supplier_reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, arena_id INTEGER NOT NULL REFERENCES arenas(id),
                    round_number INTEGER NOT NULL, merchant_id INTEGER NOT NULL REFERENCES merchants(id),
                    product_id TEXT NOT NULL, supplier_id TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0),
                    unit_price INTEGER NOT NULL CHECK(unit_price>0), status TEXT NOT NULL DEFAULT 'reserved',
                    expires_round INTEGER NOT NULL,
                    UNIQUE(arena_id,round_number,merchant_id,product_id)
                );
            """)
            for strategy in STRATEGIES:
                connection.execute("INSERT OR IGNORE INTO strategies(id,name,config,built_in) VALUES(?,?,?,1)",
                                   (strategy["id"], strategy["name"], encode(strategy)))
            connection.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('model',?)", (encode(MODEL_DEFAULTS),))
            columns = {
                "merchants": {"model_profile_id": "TEXT", "model_config": "TEXT NOT NULL DEFAULT '{}'", "workflow": "TEXT NOT NULL DEFAULT 'direct'", "agent_options": "TEXT NOT NULL DEFAULT '{}'"},
                "decisions": {"model_config": "TEXT NOT NULL DEFAULT '{}'", "trace": "TEXT NOT NULL DEFAULT '{}'"},
                "arenas": {"approval_policy": "TEXT NOT NULL DEFAULT 'off'", "parent_arena_id": "INTEGER", "fork_round": "INTEGER", "supply_policy": "TEXT NOT NULL DEFAULT 'sequential_v1'"},
                "approvals": {"version": "INTEGER NOT NULL DEFAULT 0"},
            }
            for table, additions in columns.items():
                existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                for name, declaration in additions.items():
                    if name not in existing:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            legacy = json.loads(connection.execute("SELECT value FROM settings WHERE key='model'").fetchone()[0])
            config = ModelSettings.model_validate(legacy).model_dump()
            connection.execute("INSERT OR IGNORE INTO model_profiles(id,name,config) VALUES('default','默认连接',?)", (encode(config),))
            connection.execute("UPDATE arenas SET status='paused' WHERE status IN ('running','stepping') AND NOT EXISTS (SELECT 1 FROM execution_jobs WHERE arena_id=arenas.id AND state IN ('queued','running'))")

    def strategies(self):
        with self.connect() as connection:
            return [dict(json.loads(row["config"]), built_in=bool(row["built_in"]))
                    for row in connection.execute("SELECT * FROM strategies ORDER BY built_in DESC,created_at,id")]

    def strategy(self, strategy_id):
        with self.connect() as connection:
            row = connection.execute("SELECT config FROM strategies WHERE id=?", (strategy_id,)).fetchone()
        if row is None:
            raise KeyError("策略不存在")
        return json.loads(row["config"])

    def model_settings(self, profile_id="default"):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM model_profiles WHERE id=?", (profile_id or "default",)).fetchone()
        if row is None:
            raise KeyError("模型连接不存在")
        return {**json.loads(row["config"]), "id": row["id"], "name": row["name"], "enabled": bool(row["enabled"])}

    def save_model_settings(self, settings):
        current = self.model_settings()
        if settings["api_key"] is None:
            settings["api_key"] = current["api_key"]
        with self.connect() as connection:
            connection.execute("UPDATE settings SET value=? WHERE key='model'", (encode(settings),))
            connection.execute("UPDATE model_profiles SET config=? WHERE id='default'", (encode(settings),))

    def model_profiles(self):
        with self.connect() as connection:
            ids = [row["id"] for row in connection.execute("SELECT id FROM model_profiles ORDER BY created_at,id")]
        return [self.public_model(self.model_settings(profile_id)) for profile_id in ids]

    @staticmethod
    def public_model(config):
        result = {key: value for key, value in config.items() if key != "api_key"}
        result["has_key"] = bool(config.get("api_key"))
        return result

    def save_profile(self, config, profile_id=None):
        values = dict(config)
        if values["api_key"] is None:
            values["api_key"] = self.model_settings(profile_id)["api_key"] if profile_id else ""
        with self.connect() as connection:
            if profile_id:
                self.model_settings(profile_id)
                connection.execute("UPDATE model_profiles SET name=?,config=?,enabled=? WHERE id=?",
                                   (values["name"], encode(values), values["enabled"], profile_id))
            else:
                connection.execute("BEGIN IMMEDIATE")
                number = connection.execute("SELECT COALESCE(MAX(CAST(SUBSTR(id,7) AS INTEGER)),0)+1 FROM model_profiles WHERE id LIKE 'model-%'").fetchone()[0]
                profile_id = f"model-{number}"
                connection.execute("INSERT INTO model_profiles(id,name,config,enabled) VALUES(?,?,?,?)",
                                   (profile_id, values["name"], encode(values), values["enabled"]))
        return self.public_model(self.model_settings(profile_id))

    def resolve_model(self, snapshot=None):
        if not snapshot:
            return self.model_settings()
        current = self.model_settings(snapshot["id"])
        return {**current, **snapshot, "api_key": current["api_key"]}

    def model_secrets(self):
        with self.connect() as connection:
            return [json.loads(row["config"]).get("api_key", "") for row in connection.execute("SELECT config FROM model_profiles")]

    def arena(self, arena_id):
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM arenas WHERE id=?", (arena_id,)).fetchone()
        if row is None:
            raise KeyError("比赛不存在")
        return dict(row)

    def snapshot(self, arena_id, round_number=None):
        with self.connect() as connection:
            if round_number is None:
                row = connection.execute("SELECT snapshot FROM rounds WHERE arena_id=? ORDER BY number DESC LIMIT 1", (arena_id,)).fetchone()
            else:
                row = connection.execute("SELECT snapshot FROM rounds WHERE arena_id=? AND number=?", (arena_id, round_number)).fetchone()
        if row is None:
            raise KeyError("回合不存在")
        return json.loads(row["snapshot"])

    def set_status(self, arena_id, status, error=None):
        with self.connect() as connection:
            connection.execute("UPDATE arenas SET status=?,error=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (status, error, arena_id))
