import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.errors import GraphRecursionError
from openai import APIError

from arena.agents.engine import AgentEngine
from arena.domain.catalog import COLORS, MERCHANT_NAMES, PRODUCTS, SCENARIOS
from arena.infrastructure.config import DATA_DIR, EXECUTION_MODE, PROJECT_ROOT, REDIS_URL
from arena.infrastructure.database import Database, encode
from arena.domain.models import AdvanceInput, ArenaInput, ExperimentInput, MerchantInput, ModelProfileInput, ModelSettings, RunInput, StrategyInput, ApprovalInput, ForkInput, SelectionInput
from arena.evaluation.selection import select_and_validate
from arena.agents.providers import model_error as provider_error, test_connection
from arena.execution.runner import Runner
from arena.application.service import ArenaService, ConflictError


def create_app(data_dir: Path = DATA_DIR, seed_demo: bool = True, redis_url: str = REDIS_URL, execution_mode: str = EXECUTION_MODE):
    @asynccontextmanager
    async def lifespan(app):
        database = Database(data_dir)
        database.initialize()
        agents = AgentEngine(data_dir, database.resolve_model)
        service = ArenaService(database, agents)
        runner = Runner(service, redis_url, consume=execution_mode != "external", shutdown_pause=execution_mode != "external")
        app.state.database, app.state.service, app.state.runner = database, service, runner
        await runner.open()
        if seed_demo and not service.listing():
            merchants = [MerchantInput(name=name, strategy_id=strategy, color=color)
                         for name, strategy, color in zip(MERCHANT_NAMES, ["balanced", "discount", "premium"], COLORS)]
            demo = service.create(ArenaInput(name="周末市集 · 揭幕战", scenario="festival", total_rounds=12, seed=42, merchants=merchants))
            for number in range(12):
                await asyncio.to_thread(service.advance, demo["id"], number)
            service.create(ArenaInput(name="街区新赛季", scenario="neighborhood", total_rounds=20, seed=2026, merchants=merchants))
        yield
        await runner.close()
        agents.close()

    app = FastAPI(title="AgentArena", version="1.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    @app.exception_handler(KeyError)
    async def not_found(request, error):
        return JSONResponse(status_code=404, content={"detail": error.args[0]})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(status_code=422, content={"detail": [{"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in error.errors()]})

    @app.exception_handler(ConflictError)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(APIError)
    async def model_error(request, error):
        return JSONResponse(status_code=400, content={"detail": provider_error(error, app.state.database.model_secrets())})

    @app.exception_handler(GraphRecursionError)
    async def step_limit(request, error):
        return JSONResponse(status_code=400, content={"detail": "Agent 已达到本轮执行步数上限"})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "storage": "sqlite", "queue": "redis" if redis_url else "sqlite", "execution": execution_mode,
                "features": ["adaptive-planning", "negotiation", "episodic-memory", "human-approval", "decision-events", "counterfactual-forks", "capability-evaluation"]}

    @app.get("/api/arenas/{arena_id}/tasks")
    def execution_tasks(arena_id: int):
        app.state.database.arena(arena_id)
        return app.state.runner.store.listing(arena_id)

    @app.get("/api/catalog")
    def catalog():
        return {"products": PRODUCTS, "scenarios": SCENARIOS, "merchant_names": MERCHANT_NAMES, "colors": COLORS}

    @app.get("/api/overview")
    def overview():
        arenas = app.state.service.listing()
        return {"arenas": arenas, "strategies": app.state.database.strategies(), "stats": {
            "arenas": len(arenas), "completed": sum(item["status"] == "completed" for item in arenas),
            "rounds": sum(item["current_round"] for item in arenas), "revenue": sum(item["total_revenue"] for item in arenas),
            "active": sum(item["status"] == "running" for item in arenas),
        }}

    @app.get("/api/arenas")
    def listing():
        return app.state.service.listing()

    @app.post("/api/arenas", status_code=201)
    def create(config: ArenaInput):
        return app.state.service.create(config)

    @app.get("/api/arenas/{arena_id}")
    def detail(arena_id: int, round: int | None = Query(None, ge=0)):
        return app.state.service.detail(arena_id, round)

    @app.post("/api/arenas/{arena_id}/step")
    async def step(arena_id: int, body: AdvanceInput):
        await app.state.runner.step(arena_id, body.expected_round)
        return app.state.service.detail(arena_id)

    @app.post("/api/arenas/{arena_id}/run")
    async def run(arena_id: int, body: RunInput):
        await app.state.runner.start(arena_id, body.interval)
        return app.state.service.detail(arena_id)

    @app.post("/api/arenas/{arena_id}/pause")
    async def pause(arena_id: int):
        await app.state.runner.pause(arena_id)
        return app.state.service.detail(arena_id)

    @app.post("/api/arenas/{arena_id}/fork", status_code=201)
    def fork(arena_id: int, body: ForkInput | None = None):
        return app.state.service.fork_at(arena_id, body) if body else app.state.service.fork(arena_id)

    @app.get("/api/arenas/{arena_id}/comparison")
    def comparison(arena_id: int):
        return app.state.service.comparison(arena_id)

    @app.get("/api/arenas/{arena_id}/timeline")
    def timeline(arena_id: int, after: int = Query(0, ge=0), round: int | None = Query(None, ge=1), limit: int = Query(500, ge=1, le=1000)):
        app.state.database.arena(arena_id)
        return app.state.service.events.listing(arena_id, after, round, limit)

    @app.get("/api/arenas/{arena_id}/memories/{merchant_id}")
    def memories(arena_id: int, merchant_id: int):
        app.state.database.arena(arena_id)
        return app.state.service.memory.listing(arena_id, merchant_id)

    @app.post("/api/arenas/{arena_id}/approvals/{approval_id}")
    async def resolve_approval(arena_id: int, approval_id: int, body: ApprovalInput):
        app.state.service.approvals.resolve(arena_id, approval_id, body.model_dump())
        await app.state.runner.step(arena_id, app.state.database.arena(arena_id)["current_round"])
        return app.state.service.detail(arena_id)

    @app.get("/api/arenas/{arena_id}/ledger")
    def ledger(arena_id: int, round: int | None = Query(None, ge=0), merchant: int | None = Query(None, ge=1)):
        return app.state.service.ledger(arena_id, round, merchant)

    @app.get("/api/arenas/{arena_id}/export")
    def export(arena_id: int, format: str = Query("json", pattern="^(json|csv)$")):
        service = app.state.service
        arena = service.detail(arena_id)
        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["回合", "商店", "类型", "商品", "数量", "金额（元）", "余额（元）"])
            labels = {"purchase": "采购", "sale": "销售", "marketing": "营销", "operations": "经营费用"}
            for item in reversed(service.ledger(arena_id)):
                name = item["merchant_name"]
                if name.startswith(("=", "+", "-", "@")):
                    name = "'" + name
                writer.writerow([item["round_number"], name, labels[item["kind"]], item["product_id"], item["quantity"], item["amount"] / 100, item["balance"] / 100])
            return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="arena-{arena_id}-ledger.csv"'})
        with app.state.database.connect() as connection:
            snapshots = [json.loads(row["snapshot"]) for row in connection.execute("SELECT snapshot FROM rounds WHERE arena_id=? ORDER BY number", (arena_id,))]
            events = [{**dict(row), "payload": json.loads(row["payload"])} for row in connection.execute("SELECT * FROM decision_events WHERE arena_id=? ORDER BY id", (arena_id,))]
            contracts = [dict(row) for row in connection.execute("SELECT * FROM supplier_reservations WHERE arena_id=? ORDER BY id", (arena_id,))]
        result = {"arena": arena, "snapshots": snapshots, "decisions": [decision for number in range(1, arena["current_round"] + 1) for decision in service.decisions(arena_id, number)], "ledger": service.ledger(arena_id),
                  "events": events, "contracts": contracts, "experiences": [item for merchant in arena["snapshot"]["merchants"] for item in service.memory.listing(arena_id, merchant["id"])]}
        return Response(content=json.dumps(result, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="arena-{arena_id}.json"'})

    @app.get("/api/arenas/{arena_id}/events")
    async def events(arena_id: int, request: Request, after: int = Query(0, ge=0)):
        app.state.database.arena(arena_id)

        async def stream():
            revision = None
            header = request.headers.get("last-event-id", "")
            cursor = max(after, int(header) if header.isdigit() else 0)
            while not await request.is_disconnected():
                batch = app.state.service.events.listing(arena_id, cursor)
                for event in batch:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: decision\ndata: " + encode(event) + "\n\n"
                arena = app.state.database.arena(arena_id)
                current = (arena["updated_at"], arena["current_round"], arena["status"])
                if current != revision:
                    yield "event: state\ndata: " + encode(app.state.service.detail(arena_id)) + "\n\n"
                    revision = current
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.15 if batch else 0.6)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/strategies")
    def strategies():
        return app.state.database.strategies()

    @app.post("/api/strategies", status_code=201)
    def create_strategy(body: StrategyInput):
        with app.state.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            number = connection.execute("SELECT COALESCE(MAX(CAST(SUBSTR(id,10) AS INTEGER)),0)+1 FROM strategies WHERE id LIKE 'strategy-%'").fetchone()[0]
            config = {**body.model_dump(), "id": f"strategy-{number}"}
            connection.execute("INSERT INTO strategies(id,name,config) VALUES(?,?,?)", (config["id"], config["name"], encode(config)))
        return config

    @app.put("/api/strategies/{strategy_id}")
    def update_strategy(strategy_id: str, body: StrategyInput):
        app.state.database.strategy(strategy_id)
        config = {**body.model_dump(), "id": strategy_id}
        with app.state.database.connect() as connection:
            connection.execute("UPDATE strategies SET name=?,config=? WHERE id=?", (config["name"], encode(config), strategy_id))
        return config

    @app.get("/api/experiments")
    def experiments():
        return app.state.service.experiments()

    @app.post("/api/experiments", status_code=201)
    def create_experiment(body: ExperimentInput):
        return app.state.service.create_experiment(body)

    @app.get("/api/experiments/{experiment_id}")
    def experiment(experiment_id: int):
        return app.state.service.experiment(experiment_id)

    @app.get("/api/experiments/{experiment_id}/export")
    def export_experiment(experiment_id: int):
        result = app.state.service.experiment(experiment_id)
        return Response(content=json.dumps(result, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="experiment-{experiment_id}.json"'})

    @app.post("/api/experiments/{experiment_id}/run")
    async def run_experiment(experiment_id: int):
        experiment = app.state.service.experiment(experiment_id)
        for arena in experiment["arenas"]:
            if arena["status"] != "completed":
                await app.state.runner.start(arena["id"], 0)
        return app.state.service.experiment(experiment_id)

    @app.post("/api/experiments/{experiment_id}/select", status_code=201)
    async def select_strategy(experiment_id: int, body: SelectionInput):
        validation = select_and_validate(app.state.service, experiment_id, body)
        for arena in validation["arenas"]:
            await app.state.runner.start(arena["id"], 0)
        return validation

    @app.get("/api/settings")
    def settings():
        config = app.state.database.model_settings()
        api_key = config.pop("api_key")
        return {**config, "has_key": bool(api_key), "queue": "redis" if redis_url else "sqlite", "storage": "SQLite", "execution": execution_mode, "queue_error": app.state.runner.queue_error}

    @app.put("/api/settings")
    def save_settings(body: ModelSettings):
        app.state.database.save_model_settings(body.model_dump())
        return settings()

    @app.post("/api/settings/test")
    def test_model(body: ModelSettings | None = None):
        config = app.state.database.model_settings()
        if body:
            values = body.model_dump()
            if values["api_key"] is None:
                values["api_key"] = config["api_key"]
            config = values
        return check_connection(config)

    def check_connection(config):
        try:
            return test_connection(config)
        except APIError as error:
            return JSONResponse(status_code=400, content={"detail": provider_error(error, [config["api_key"]])})

    @app.get("/api/model-profiles")
    def model_profiles():
        return app.state.database.model_profiles()

    @app.post("/api/model-profiles", status_code=201)
    def create_profile(body: ModelProfileInput):
        return app.state.database.save_profile(body.model_dump())

    @app.put("/api/model-profiles/{profile_id}")
    def update_profile(profile_id: str, body: ModelProfileInput):
        return app.state.database.save_profile(body.model_dump(), profile_id)

    @app.post("/api/model-profiles/test")
    def test_new_profile(body: ModelProfileInput):
        return check_connection(body.model_dump())

    @app.post("/api/model-profiles/{profile_id}/test")
    def test_profile(profile_id: str, body: ModelProfileInput | None = None):
        config = app.state.database.model_settings(profile_id)
        if body:
            values = body.model_dump()
            if values["api_key"] is None:
                values["api_key"] = config["api_key"]
            config = values
        return check_connection(config)

    @app.post("/api/model-profiles/{profile_id}/copy", status_code=201)
    def copy_profile(profile_id: str):
        config = app.state.database.model_settings(profile_id)
        config["name"] += " · 副本"
        return app.state.database.save_profile(ModelProfileInput.model_validate(config).model_dump())

    distribution = PROJECT_ROOT / "frontend" / "dist"
    if distribution.exists():
        app.mount("/assets", StaticFiles(directory=distribution / "assets"), name="assets")

        @app.get("/favicon.svg", include_in_schema=False)
        def favicon():
            return FileResponse(distribution / "favicon.svg")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "接口不存在"})
            return FileResponse(distribution / "index.html")

    return app
