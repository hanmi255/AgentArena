import json
import time

from fastapi.testclient import TestClient

from arena.api.app import create_app


def wait_completed(client, arena_id):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        arena = client.get(f"/api/arenas/{arena_id}").json()
        if arena["status"] == "completed":
            return arena
        assert arena["error"] is None, arena["error"]
        time.sleep(0.03)
    raise AssertionError("比赛未按时完成")


def test_run_replay_fork_and_export(client, arena_config):
    arena_id = client.post("/api/arenas", json=arena_config).json()["id"]
    assert client.post(f"/api/arenas/{arena_id}/run", json={"interval": 0}).status_code == 200
    arena = wait_completed(client, arena_id)
    historical = client.get(f"/api/arenas/{arena_id}?round=2").json()
    assert historical["snapshot"]["round"] == 2
    assert all(item["round_number"] == 2 for item in historical["decisions"])
    assert client.get(f"/api/arenas/{arena_id}?round=9").status_code == 404
    exported = client.get(f"/api/arenas/{arena_id}/export").json()
    assert len(exported["snapshots"]) == 6
    assert len(exported["decisions"]) == 15
    assert len(exported["ledger"]) > 0
    csv = client.get(f"/api/arenas/{arena_id}/export?format=csv")
    assert csv.status_code == 200 and "回合" in csv.text and "交易金额" not in csv.text
    fork = client.post(f"/api/arenas/{arena_id}/fork").json()
    assert fork["id"] != arena_id and fork["current_round"] == 0
    assert fork["seed"] == arena["seed"]
    assert [item["strategy_id"] for item in fork["snapshot"]["merchants"]] == [item["strategy_id"] for item in arena["snapshot"]["merchants"]]


def test_restart_keeps_snapshots_and_recovers_running_as_paused(tmp_path, arena_config):
    with TestClient(create_app(tmp_path, seed_demo=False)) as first:
        arena_id = first.post("/api/arenas", json=arena_config).json()["id"]
        first.post(f"/api/arenas/{arena_id}/step", json={"expected_round": 0})
        saved = first.get(f"/api/arenas/{arena_id}").json()["snapshot"]
        first.app.state.database.set_status(arena_id, "running")
    with TestClient(create_app(tmp_path, seed_demo=False)) as second:
        restored = second.get(f"/api/arenas/{arena_id}").json()
        assert restored["status"] == "paused" and restored["current_round"] == 1
        assert restored["snapshot"] == saved
        second.post(f"/api/arenas/{arena_id}/run", json={"interval": 0})
        assert wait_completed(second, arena_id)["current_round"] == 5


def test_strategy_snapshots_and_model_secrets(client, arena_config):
    strategy = client.get("/api/strategies").json()[0]
    strategy["name"] = "自定义现金策略"
    created = client.post("/api/strategies", json=strategy).json()
    assert created["id"].startswith("strategy-")
    arena_config["merchants"][0]["strategy_id"] = created["id"]
    arena = client.post("/api/arenas", json=arena_config).json()
    created["name"] = "新版本策略"
    assert client.put(f"/api/strategies/{created['id']}", json=created).status_code == 200
    assert client.get(f"/api/arenas/{arena['id']}").json()["snapshot"]["merchants"][0]["strategy_name"] == "自定义现金策略"
    replayed = client.post(f"/api/arenas/{arena['id']}/fork").json()
    assert replayed["snapshot"]["merchants"][0]["strategy_name"] == "自定义现金策略"
    settings = {"base_url": "http://127.0.0.1:9991/v1", "model": "test-model", "api_key": "secret-test-key", "temperature": 0.5, "timeout": 5, "max_steps": 10}
    response = client.put("/api/settings", json=settings)
    assert response.status_code == 200
    assert response.json()["has_key"] is True
    assert "secret-test-key" not in response.text
    settings["api_key"] = None
    client.put("/api/settings", json=settings)
    assert client.app.state.database.model_settings()["api_key"] == "secret-test-key"
    settings["api_key"] = ""
    assert client.put("/api/settings", json=settings).json()["has_key"] is False


def test_experiment_rotates_seats_and_aggregates_real_outcomes(client):
    response = client.post("/api/experiments", json={"name": "对照实验", "strategy_ids": ["balanced", "discount", "adaptive"], "rounds": 3, "seeds": [11, 23], "mode": "rule"})
    assert response.status_code == 201, response.text
    experiment = response.json()
    assert len(experiment["arenas"]) == 2
    first, second = experiment["arenas"]
    assert first["merchants"][0]["strategy_id"] != second["merchants"][0]["strategy_id"]
    client.post(f"/api/experiments/{experiment['id']}/run")
    for arena in experiment["arenas"]:
        wait_completed(client, arena["id"])
    result = client.get(f"/api/experiments/{experiment['id']}").json()
    assert result["status"] == "completed" and result["completed"] == 2
    assert all(item["samples"] == 2 for item in result["scores"])
    assert sum(item["win_rate"] for item in result["scores"]) == 100
    assert client.get(f"/api/experiments/{experiment['id']}/export").status_code == 200


def test_boundary_validation_and_missing_resources(client, arena_config):
    assert client.get("/api/arenas/999").status_code == 404
    arena_config["merchants"][0]["strategy_id"] = "missing"
    assert client.post("/api/arenas", json=arena_config).status_code == 404
    arena_config["merchants"][0]["strategy_id"] = "balanced"
    arena_config["merchants"][0]["mode"] = "llm"
    assert client.post("/api/arenas", json=arena_config).status_code == 400
    assert client.post("/api/experiments", json={"name": "重复策略", "strategy_ids": ["balanced", "balanced"]}).status_code == 422
    arena_config["merchants"][0]["mode"] = "rule"
    arena_config["total_rounds"] = 0
    assert client.post("/api/arenas", json=arena_config).status_code == 422
