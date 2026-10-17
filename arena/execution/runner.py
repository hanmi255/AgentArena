import asyncio
import os
import socket
from collections import defaultdict
from contextlib import suppress

from openai import APIConnectionError, APIStatusError, APITimeoutError
from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from arena.agents.providers import model_error
from arena.application.service import ConflictError
from arena.execution.tasks import LeaseLost, TaskStore
from arena.agents.approval import ApprovalRequired


class Runner:
    def __init__(self, service, redis_url="", consume=True, shutdown_pause=True, lease_seconds=15):
        self.service, self.db = service, service.db
        self.redis = Redis.from_url(redis_url, decode_responses=True) if redis_url else None
        self.store = TaskStore(self.db, lease_seconds)
        self.consume, self.shutdown_pause = consume, shutdown_pause
        self.owner = f"{socket.gethostname()}/worker-{os.getpid()}"
        self.tasks = {}
        self.operations = defaultdict(asyncio.Lock)
        self.dispatcher = None
        self.closing = False
        self.queue_error = None

    async def open(self):
        if self.redis:
            await self.redis.ping()
            try:
                await self.redis.xgroup_create("arena:commands", "arena-workers", id="0", mkstream=True)
            except ResponseError as error:
                if "BUSYGROUP" not in str(error):
                    raise
        self.dispatcher = asyncio.create_task(self.dispatch())

    async def close(self):
        self.closing = True
        self.dispatcher.cancel()
        if self.shutdown_pause:
            for job in self.tasks.values():
                if not job["task"].done():
                    self.store.pause(job["arena_id"])
        await asyncio.gather(self.dispatcher, *(entry["task"] for entry in self.tasks.values()), return_exceptions=True)
        if self.redis:
            await self.redis.aclose()

    async def publish(self):
        for event in self.store.pending_events():
            if self.redis:
                await self.redis.xadd("arena:commands", {"job_id": event["job_id"]})
            self.store.published(event["id"])

    async def dispatch(self):
        while True:
            try:
                await self.dispatch_once()
                self.queue_error = None
            except RedisError:
                self.queue_error = "Redis 连接中断，正在重连"
                await asyncio.sleep(1)

    async def dispatch_once(self):
        await self.publish()
        self.tasks = {job_id: entry for job_id, entry in self.tasks.items() if not entry["task"].done()}
        if not self.consume or len(self.tasks) >= 2:
            await asyncio.sleep(0.05)
            return
        message_id = None
        job = None
        if self.redis:
            messages = await self.redis.xreadgroup("arena-workers", self.owner, {"arena:commands": ">"}, count=1, block=100)
            items = messages[0][1] if messages else []
            if not items:
                reclaimed = await self.redis.xautoclaim("arena:commands", "arena-workers", self.owner, min_idle_time=15000, start_id="0-0", count=1)
                items = reclaimed[1]
            if items:
                message_id, message = items[0]
                job = self.store.claim(self.owner, int(message["job_id"]))
                if job is None:
                    await self.redis.xack("arena:commands", "arena-workers", message_id)
                    message_id = None
        if job is None:
            job = self.store.claim(self.owner)
        if job:
            self.tasks[job["id"]] = {"arena_id": job["arena_id"], "task": asyncio.create_task(self.execute(job, message_id))}
        else:
            await asyncio.sleep(0.05)

    async def start(self, arena_id, interval):
        async with self.operations[arena_id]:
            arena = self.db.arena(arena_id)
            if arena["status"] == "completed":
                raise ConflictError("比赛已结束")
            if self.service.approvals.pending(arena_id):
                raise ConflictError("请先处理待审批的经营方案")
            if arena["status"] == "stepping":
                raise ConflictError("本轮正在结算")
            self.store.enqueue(arena_id, interval)

    async def pause(self, arena_id):
        self.db.arena(arena_id)
        self.store.pause(arena_id)

    async def step(self, arena_id, expected_round):
        async with self.operations[arena_id]:
            arena = self.db.arena(arena_id)
            if arena["status"] in ("running", "stepping"):
                raise ConflictError("请先暂停比赛")
            with self.db.connect() as connection:
                pending = connection.execute("SELECT 1 FROM execution_jobs WHERE arena_id=? AND state='running'", (arena_id,)).fetchone()
            if pending:
                raise ConflictError("本轮正在结束，请稍后单步执行")
            if arena["status"] == "completed":
                raise ConflictError("比赛已结束")
            self.db.set_status(arena_id, "stepping")
            try:
                await asyncio.to_thread(self.service.advance, arena_id, expected_round)
            except ApprovalRequired:
                self.db.set_status(arena_id, "awaiting_approval")
                return
            except Exception as error:
                self.record_error(arena_id, error)
                raise
            if self.db.arena(arena_id)["status"] != "completed":
                self.db.set_status(arena_id, "paused")

    async def heartbeat(self, job):
        while True:
            await asyncio.sleep(self.store.lease_seconds / 3)
            self.store.heartbeat(job)

    async def execute(self, job, message_id):
        heartbeat = asyncio.create_task(self.heartbeat(job))
        try:
            while True:
                arena = self.db.arena(job["arena_id"])
                if arena["status"] != "running":
                    if self.store.finish(job, "completed" if arena["status"] == "completed" else "paused"):
                        break
                    continue
                if self.closing and not self.shutdown_pause:
                    self.store.retry(job, "worker 正常退出，等待接管")
                    break
                await asyncio.to_thread(self.service.advance, arena["id"], arena["current_round"], job)
                await asyncio.sleep(job["interval"])
        except ApprovalRequired:
            with suppress(LeaseLost):
                self.store.suspend_for_approval(job)
        except LeaseLost:
            pass
        except Exception as error:
            message = model_error(error, self.db.model_secrets())
            transient = isinstance(error, (APIConnectionError, APITimeoutError)) or isinstance(error, APIStatusError) and (error.status_code == 429 or error.status_code >= 500)
            with suppress(LeaseLost):
                if transient and job["attempts"] < 3 and self.db.arena(job["arena_id"])["status"] == "running":
                    self.store.retry(job, message)
                else:
                    self.store.finish(job, "failed", message)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, LeaseLost):
                await heartbeat
            if self.redis and message_id:
                with suppress(RedisError):
                    await self.redis.xack("arena:commands", "arena-workers", message_id)

    def record_error(self, arena_id, error):
        self.db.set_status(arena_id, "paused", model_error(error, self.db.model_secrets()))
