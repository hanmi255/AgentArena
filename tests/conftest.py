import pytest
from fastapi.testclient import TestClient

from arena.api.app import create_app
from tests.test_model import model_server
from arena.infrastructure.config import MODEL_DEFAULTS


@pytest.fixture(autouse=True)
def isolated_model_defaults(monkeypatch):
    monkeypatch.setitem(MODEL_DEFAULTS, "api_key", "")
    monkeypatch.setitem(MODEL_DEFAULTS, "model", "")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, seed_demo=False)) as test_client:
        yield test_client


@pytest.fixture
def arena_config():
    return {
        "name": "测试市场", "scenario": "neighborhood", "seed": 42, "total_rounds": 5,
        "initial_capital": 1000000,
        "merchants": [
            {"name": "北辰商店", "strategy_id": "balanced", "mode": "rule", "color": "violet"},
            {"name": "橙子补给", "strategy_id": "discount", "mode": "rule", "color": "orange"},
            {"name": "青禾市集", "strategy_id": "premium", "mode": "rule", "color": "teal"},
        ],
    }
