import asyncio

from fakeredis.aioredis import FakeRedis
from redis.exceptions import ConnectionError

from arena.execution.runner import Runner


def test_redis_stream_queue_executes_and_acknowledges(client, arena_config):
    service = client.app.state.service
    arena_id = client.post("/api/arenas", json=arena_config).json()["id"]
    client.portal.call(client.app.state.runner.close)

    async def scenario():
        runner = Runner(service)
        runner.redis = FakeRedis(decode_responses=True)
        await runner.open()
        try:
            await runner.start(arena_id, 0)
            for _ in range(300):
                if service.db.arena(arena_id)["status"] == "completed":
                    break
                await asyncio.sleep(0.02)
            assert service.db.arena(arena_id)["status"] == "completed"
            await asyncio.gather(*(entry["task"] for entry in runner.tasks.values()))
            assert await runner.redis.xlen("arena:commands") == 1
            pending = await runner.redis.xpending("arena:commands", "arena-workers")
            assert pending["pending"] == 0
        finally:
            await runner.close()

    asyncio.run(scenario())


def test_outbox_survives_redis_publish_failure_and_reconnects(client, arena_config):
    client.portal.call(client.app.state.runner.close)
    service = client.app.state.service
    arena_id = client.post("/api/arenas", json=arena_config).json()["id"]

    async def scenario():
        runner = Runner(service)
        runner.redis = FakeRedis(decode_responses=True)
        original = runner.redis.xadd
        attempts = 0

        async def disconnected_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("test connection dropped")
            return await original(*args, **kwargs)

        runner.redis.xadd = disconnected_once
        await runner.open()
        try:
            await runner.start(arena_id, 0)
            for _ in range(100):
                if runner.queue_error:
                    break
                await asyncio.sleep(0.02)
            assert runner.queue_error and runner.store.pending_events()
            for _ in range(300):
                if service.db.arena(arena_id)["status"] == "completed":
                    break
                await asyncio.sleep(0.02)
            assert service.db.arena(arena_id)["status"] == "completed"
            assert runner.store.pending_events() == []
            assert await runner.redis.xlen("arena:commands") == 1
        finally:
            await runner.close()

    asyncio.run(scenario())
