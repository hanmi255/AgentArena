"""Durable, public business events. Never persist raw model reasoning or credentials."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

from arena.infrastructure.database import encode

_sink: ContextVar[Callable | None] = ContextVar("arena_event_sink", default=None)


def emit(node: str, status: str, label: str, **payload):
    sink = _sink.get()
    if sink:
        sink(node, status, label, payload)


@contextmanager
def event_scope(sink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


class EventStore:
    def __init__(self, database):
        self.db = database

    def append(self, arena_id, round_number, merchant_id, node, status, label, payload=None, connection=None):
        values = (arena_id, round_number, merchant_id, node, status, label, encode(payload or {}))
        query = "INSERT INTO decision_events(arena_id,round_number,merchant_id,node,status,label,payload) VALUES(?,?,?,?,?,?,?)"
        if connection is not None:
            return connection.execute(query, values).lastrowid
        with self.db.connect() as conn:
            return conn.execute(query, values).lastrowid

    def listing(self, arena_id, after=0, round_number=None, limit=500):
        query = "SELECT * FROM decision_events WHERE arena_id=? AND id>?"
        values = [arena_id, after]
        if round_number is not None:
            query += " AND round_number=?"
            values.append(round_number)
        with self.db.connect() as conn:
            rows = conn.execute(query + " ORDER BY id LIMIT ?", (*values, limit)).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
