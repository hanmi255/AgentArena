import os
import sqlite3
import stat

import pytest
from fastapi.testclient import TestClient

from arena.api.app import create_app
from arena.infrastructure.database import Database
from arena.infrastructure.storage_permissions import SQLITE_FILES, prepare_sqlite_files


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only file attributes")
def test_readonly_runtime_files_are_repaired_without_changing_other_files(tmp_path):
    expected = {}
    for name in (*SQLITE_FILES, "keep.txt"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        expected[name] = path.read_bytes()
        path.chmod(stat.S_IREAD)
    try:
        assert {path.name for path in prepare_sqlite_files(tmp_path)} == set(SQLITE_FILES)
        for name in SQLITE_FILES:
            path = tmp_path / name
            assert not path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
            assert path.read_bytes() == expected[name]
        assert (tmp_path / "keep.txt").stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
        assert prepare_sqlite_files(tmp_path) == []
    finally:
        for path in tmp_path.iterdir():
            path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(os.name != "nt", reason="Windows read-only file attributes")
def test_application_restarts_with_readonly_databases_and_preserves_data(tmp_path):
    with TestClient(create_app(tmp_path, seed_demo=False)) as client:
        assert client.get("/api/health").status_code == 200
    db = Database(tmp_path)
    with db.connect() as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM strategies ORDER BY id")]
    for name in SQLITE_FILES:
        path = tmp_path / name
        if path.exists():
            path.chmod(stat.S_IREAD)
    try:
        with TestClient(create_app(tmp_path, seed_demo=False)) as client:
            assert client.get("/api/health").status_code == 200
            with client.app.state.database.connect() as connection:
                assert [tuple(row) for row in connection.execute("SELECT * FROM strategies ORDER BY id")] == before
                connection.execute("INSERT INTO settings(key,value) VALUES('readonly-restart-test','ok')")
            with sqlite3.connect(tmp_path / "checkpoints.sqlite") as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS restart_check(value INTEGER)")
                connection.execute("INSERT INTO restart_check VALUES(1)")
    finally:
        for name in SQLITE_FILES:
            path = tmp_path / name
            if path.exists():
                path.chmod(stat.S_IREAD | stat.S_IWRITE)
