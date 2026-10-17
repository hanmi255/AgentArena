"""AgentArena application packages."""
import sys
from arena.domain import models
sys.modules.setdefault("arena.models", models)
