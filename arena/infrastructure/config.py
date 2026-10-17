import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = Path(os.environ.get("ARENA_DATA_DIR", str(PROJECT_ROOT / "data")))
REDIS_URL = os.environ.get("REDIS_URL", "")
HOST = os.environ.get("ARENA_HOST", "127.0.0.1")
PORT = int(os.environ.get("ARENA_PORT", "8010"))
EXECUTION_MODE = os.environ.get("ARENA_EXECUTION", "embedded")

MODEL_DEFAULTS = {
    "base_url": os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1"),
    "model": os.environ.get("MODEL_NAME", ""),
    "api_key": os.environ.get("MODEL_API_KEY", ""),
    "temperature": 0.5,
    "timeout": 60,
    "max_steps": 10,
}
