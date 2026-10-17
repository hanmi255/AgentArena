"""Run independently: python -m arena.worker --idle-exit 0."""

import argparse
import asyncio
import time

from arena.agents.engine import AgentEngine
from arena.infrastructure.config import DATA_DIR, REDIS_URL
from arena.infrastructure.database import Database
from arena.execution.runner import Runner
from arena.application.service import ArenaService


async def run(args):
    database = Database(DATA_DIR)
    database.initialize()
    agents = AgentEngine(DATA_DIR, database.resolve_model)
    runner = Runner(ArenaService(database, agents), REDIS_URL, shutdown_pause=False, lease_seconds=args.lease_seconds)
    await runner.open()
    idle_since = time.monotonic()
    print(f"Worker ready: {runner.owner}", flush=True)
    try:
        while True:
            if any(not item["task"].done() for item in runner.tasks.values()):
                idle_since = time.monotonic()
            if args.idle_exit and time.monotonic() - idle_since > args.idle_exit:
                break
            await asyncio.sleep(0.1)
    finally:
        await runner.close()
        agents.close()


def main():
    parser = argparse.ArgumentParser(description="AgentArena durable execution worker")
    parser.add_argument("--idle-exit", type=float, default=0)
    parser.add_argument("--lease-seconds", type=float, default=15)
    args = parser.parse_args()
    if args.lease_seconds < 1:
        parser.error("lease-seconds must be at least 1")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
