import os
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from arena.api.app import create_app
from arena.infrastructure.config import PROJECT_ROOT
from arena.execution.tasks import LeaseLost, TaskStore


def wait_until(work, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = work()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("execution condition did not become true")


def test_fencing_rejects_old_worker_and_outbox_commits_with_job(tmp_path, arena_config):
    with TestClient(create_app(tmp_path, seed_demo=False, execution_mode="external")) as client:
        arena_id = client.post("/api/arenas", json=arena_config).json()["id"]
        store = TaskStore(client.app.state.database)
        job_id = store.enqueue(arena_id, 0)
        first = store.claim("worker-one", job_id)
        assert first and store.claim("worker-two", job_id) is None
        with client.app.state.database.connect() as connection:
            connection.execute("UPDATE execution_jobs SET lease_until=0 WHERE id=?", (job_id,))
        second = store.claim("worker-two", job_id)
        assert second["lease_version"] == first["lease_version"] + 1
        with pytest.raises(LeaseLost):
            client.app.state.service.advance(arena_id, 0, first)
        assert client.get(f"/api/arenas/{arena_id}").json()["current_round"] == 0
        client.app.state.service.advance(arena_id, 0, second)
        assert client.get(f"/api/arenas/{arena_id}").json()["current_round"] == 1
        jobs = client.get(f"/api/arenas/{arena_id}/tasks").json()
        assert jobs[0]["attempts"] == 2
        with client.app.state.database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM command_outbox WHERE job_id=?", (job_id,)).fetchone()[0] == 1


def test_killed_worker_is_replaced_and_financial_effects_remain_unique(tmp_path, arena_config):
    environment = {**os.environ, "ARENA_DATA_DIR": str(tmp_path), "REDIS_URL": "", "PYTHONIOENCODING": "utf-8"}
    workers = []
    with TestClient(create_app(tmp_path, seed_demo=False, execution_mode="external")) as client:
        arena_id = client.post("/api/arenas", json=arena_config).json()["id"]
        client.post(f"/api/arenas/{arena_id}/run", json={"interval": 0.4})

        def spawn_worker():
            process = subprocess.Popen([sys.executable, "-m", "arena.worker", "--lease-seconds", "1.5", "--idle-exit", "5"],
                                       cwd=PROJECT_ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            workers.append(process)
            return process

        try:
            first = spawn_worker()
            wait_until(lambda: client.get(f"/api/arenas/{arena_id}").json()["current_round"] >= 1)
            first.kill()
            first.communicate(timeout=5)
            second = spawn_worker()
            wait_until(lambda: client.get(f"/api/arenas/{arena_id}").json()["status"] == "completed")
            jobs = client.get(f"/api/arenas/{arena_id}/tasks").json()
            assert jobs[0]["attempts"] >= 2
            exported = client.get(f"/api/arenas/{arena_id}/export").json()
            assert len(exported["snapshots"]) == 6 and len(exported["decisions"]) == 15
            for merchant in exported["arena"]["snapshot"]["merchants"]:
                initial = next(item for item in exported["snapshots"][0]["merchants"] if item["id"] == merchant["id"])
                entries = [item for item in exported["ledger"] if item["merchant_id"] == merchant["id"]]
                assert initial["cash"] + sum(item["amount"] for item in entries) == merchant["cash"]
        finally:
            for process in workers:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=5)


def test_lease_loss_after_planning_cannot_commit_any_financial_writes(tmp_path, arena_config, monkeypatch):
    with TestClient(create_app(tmp_path, seed_demo=False, execution_mode="external")) as client:
        service = client.app.state.service
        arena = client.post("/api/arenas", json=arena_config).json()
        store = TaskStore(client.app.state.database)
        job_id = store.enqueue(arena["id"], 0)
        first = store.claim("old-worker", job_id)
        original = service.agents.run
        last_id = arena["snapshot"]["merchants"][-1]["id"]

        def lose_lease_after_last_plan(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[2] == last_id:
                with client.app.state.database.connect() as connection:
                    connection.execute("UPDATE execution_jobs SET lease_until=0 WHERE id=?", (job_id,))
                store.claim("new-worker", job_id)
            return result

        monkeypatch.setattr(service.agents, "run", lose_lease_after_last_plan)
        with pytest.raises(LeaseLost):
            service.advance(arena["id"], 0, first)
        assert service.db.arena(arena["id"])["current_round"] == 0
        assert service.ledger(arena["id"]) == []
        with service.db.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM supplier_reservations").fetchone()[0] == 0
