import json

from arena.infrastructure.database import Database


def profile(base_url, name="Flash", model="deepseek-flash"):
    return {"name": name, "base_url": base_url, "model": model, "api_key": "profile-secret", "provider": "deepseek",
            "thinking": "enabled", "timeout": 5, "max_steps": 15}


def test_profiles_use_form_values_preserve_secrets_and_roundtrip_reasoning(client, model_server):
    settings = profile(model_server + "/chat/completions ")
    # The connection check must work without saving, including provider reasoning round-trip.
    response = client.post("/api/model-profiles/test", json=settings)
    assert response.status_code == 200, response.text
    assert response.json()["tool_calling"] is True
    assert client.get("/api/settings").json()["has_key"] is False
    saved = client.post("/api/model-profiles", json=settings).json()
    assert saved["base_url"] == model_server
    assert saved["has_key"] and "api_key" not in saved
    settings.update(api_key=None, model="deepseek-v4-pro")
    assert client.put(f"/api/model-profiles/{saved['id']}", json=settings).json()["has_key"]
    assert client.post(f"/api/model-profiles/{saved['id']}/test", json=settings).status_code == 200
    copied = client.post(f"/api/model-profiles/{saved['id']}/copy").json()
    assert copied["id"] != saved["id"] and copied["has_key"]
    assert "profile-secret" not in client.get("/api/model-profiles").text


def test_each_store_uses_its_own_model_and_immutable_parameters(client, arena_config, model_server):
    flash = client.post("/api/model-profiles", json=profile(model_server)).json()
    pro = client.post("/api/model-profiles", json=profile(model_server, "Pro", "deepseek-v4-pro")).json()
    arena_config["merchants"] = arena_config["merchants"][:2]
    for merchant, connection in zip(arena_config["merchants"], [flash, pro]):
        merchant.update(mode="llm", model_profile_id=connection["id"])
    arena = client.post("/api/arenas", json=arena_config).json()
    updated = profile(model_server, "Flash changed", "changed-model")
    client.put(f"/api/model-profiles/{flash['id']}", json=updated)
    result = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert result.status_code == 200, result.text
    decisions = result.json()["decisions"]
    assert [item["model_config"]["model"] for item in decisions] == ["deepseek-flash", "deepseek-v4-pro"]
    assert "profile-secret" not in result.text
    assert "private protocol state" not in result.text


def test_existing_database_migrates_without_losing_history_or_key(tmp_path, arena_config):
    db = Database(tmp_path)
    # Construct the original settings table to exercise the additive migration.
    with db.connect() as connection:
        connection.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        connection.execute("INSERT INTO settings VALUES('model',?)", (json.dumps(profile("https://api.deepseek.com")),))
    db.initialize()
    assert db.model_settings()["api_key"] == "profile-secret"
    assert db.model_profiles()[0]["model"] == "deepseek-flash"
    db.initialize()
    assert len(db.model_profiles()) == 1


def test_invalid_model_form_never_echoes_credentials(client, model_server):
    config = profile(model_server)
    config["name"] = ""
    response = client.post("/api/model-profiles", json=config)
    assert response.status_code == 422
    assert "profile-secret" not in response.text
