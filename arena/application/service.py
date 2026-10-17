import json
import statistics
import threading
import copy
from collections import defaultdict

from arena.domain.catalog import COLORS, MERCHANT_NAMES, PRODUCTS
from arena.infrastructure.database import encode
from arena.domain.market import conditions, settle
from arena.domain.models import ArenaInput, ExperimentVariant, MerchantInput
from arena.execution.tasks import TaskStore
from arena.evaluation.metrics import evaluate_experiment
from arena.agents.approval import ApprovalCoordinator
from arena.agents.memory import ExperienceStore
from arena.agents.negotiation import Negotiator
from arena.agents.tool_records import tool_records
from arena.domain.procurement import POLICY, allocate_orders, purchase_outcomes
from arena.infrastructure.events import EventStore, event_scope
from arena.execution.context import current_job


class ConflictError(Exception):
    pass


class ArenaService:
    def __init__(self, database, agents):
        self.db = database
        self.agents = agents
        self.locks = defaultdict(threading.Lock)
        self.events = EventStore(database)
        self.memory = ExperienceStore(database)
        self.approvals = ApprovalCoordinator(database)
        if hasattr(agents, "checkpointer"):
            agents.approvals = self.approvals
            agents.negotiator = Negotiator(database, database.resolve_model, agents.checkpointer)

    def create(self, config: ArenaInput, experiment_id=None, strategy_configs=None, model_configs=None, supply_policy=POLICY):
        strategies = strategy_configs if strategy_configs is not None else {item.strategy_id: self.db.strategy(item.strategy_id) for item in config.merchants}
        models = model_configs if model_configs is not None else {index: self.require_model(item.model_profile_id) for index, item in enumerate(config.merchants) if item.mode == "llm"}
        with self.db.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO arenas(name,scenario,seed,total_rounds,initial_capital,experiment_id,approval_policy,supply_policy) VALUES(?,?,?,?,?,?,?,?)",
                (config.name, config.scenario, config.seed, config.total_rounds, config.initial_capital, experiment_id, config.approval_policy, supply_policy),
            )
            arena_id = cursor.lastrowid
            merchants = []
            initial_stock_value = sum(item["initial_stock"] * item["cost"] for item in PRODUCTS)
            for slot, item in enumerate(config.merchants):
                strategy = strategies[item.strategy_id]
                cash = config.initial_capital - initial_stock_value
                cursor = connection.execute(
                    "INSERT INTO merchants(arena_id,slot,name,color,strategy_id,strategy_config,mode,cash,model_profile_id,model_config,workflow,agent_options) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (arena_id, slot, item.name, item.color, item.strategy_id, encode(strategy), item.mode, cash,
                     models[slot]["id"] if slot in models else None, encode(models.get(slot, {})), item.workflow, encode(item.agent_options.model_dump())),
                )
                merchant_id = cursor.lastrowid
                inventory = []
                for product in PRODUCTS:
                    stock = {"product_id": product["id"], "name": product["name"], "quantity": product["initial_stock"],
                             "book_value": product["initial_stock"] * product["cost"], "price": product["reference_price"]}
                    inventory.append(stock)
                    connection.execute("INSERT INTO inventory(merchant_id,product_id,quantity,book_value,price) VALUES(?,?,?,?,?)",
                                       (merchant_id, product["id"], stock["quantity"], stock["book_value"], stock["price"]))
                merchants.append({"id": merchant_id, "slot": slot, "name": item.name, "color": item.color,
                                  "strategy_id": item.strategy_id, "strategy_name": strategy["name"], "mode": item.mode,
                                  "model_config": models.get(slot, {}), "workflow": item.workflow,
                                  "agent_options": item.agent_options.model_dump(),
                                  "entrant_id": item.entrant_id or item.strategy_id,
                                  "cash": cash, "equity": config.initial_capital, "profit": 0, "roi": 0,
                                  "inventory": inventory, "total_revenue": 0, "total_sold": 0, "reputation": 1,
                                  "memory": "", "bankrupt": False, "metrics": {"revenue": 0, "sold": 0, "profit": 0, "marketing": 0, "procurement": 0, "operating_cost": 0, "cost_of_goods": 0, "purchased": 0, "missed": 0}})
            snapshot = {"round": 0, "market": conditions(config.scenario, config.seed, 1), "merchants": merchants,
                        "totals": {"revenue": 0, "sold": 0, "demand": 0, "profit": 0}}
            connection.execute("INSERT INTO rounds(arena_id,number,snapshot) VALUES(?,0,?)", (arena_id, encode(snapshot)))
        return self.detail(arena_id)

    def require_model(self, profile_id=None):
        settings = self.db.model_settings(profile_id)
        if not settings["model"] or not settings["api_key"]:
            raise ValueError("请先在运行设置中配置模型和 API Key")
        if not settings["enabled"]:
            raise ValueError("所选模型连接已停用")
        return {key: value for key, value in settings.items() if key != "api_key"}

    def observation(self, arena, previous, merchant, market):
        with self.db.connect() as connection:
            rows = connection.execute("SELECT snapshot FROM rounds WHERE arena_id=? AND number>0 ORDER BY number DESC LIMIT 5", (arena["id"],)).fetchall()
        history = []
        for row in reversed(rows):
            snapshot = json.loads(row["snapshot"])
            own = next(item for item in snapshot["merchants"] if item["id"] == merchant["id"])
            history.append({"round": snapshot["round"], **own["metrics"]})
        competitors = [{"name": other["name"], "prices": [{"product_id": stock["product_id"], "price": stock["price"]} for stock in other["inventory"]]}
                       for other in previous["merchants"] if other["id"] != merchant["id"]]
        options = merchant.get("agent_options", {})
        store = copy.deepcopy(merchant)
        if options.get("memory") == "none":
            store["memory"] = ""
            history = []
        experiences = self.memory.recall(arena["id"], merchant["id"], market["round"], market, store) if options.get("memory") == "episodic" else []
        return {"store": store, "market": market, "competitors": competitors, "history": history,
                "arena_id": arena["id"], "supply_policy": arena["supply_policy"], "approval_policy": arena.get("approval_policy", "off"), "agent_options": options, "experiences": experiences,
                "merchant_count": len(previous["merchants"]), "remaining_rounds": arena["total_rounds"] - arena["current_round"]}

    def advance(self, arena_id, expected_round, job=None):
        with self.locks[arena_id]:
            arena = self.db.arena(arena_id)
            if arena["current_round"] != expected_round:
                raise ConflictError("该回合已经结算，请刷新赛场")
            if arena["status"] == "completed":
                raise ConflictError("比赛已结束")
            previous = self.db.snapshot(arena_id)
            number = arena["current_round"] + 1
            market = conditions(arena["scenario"], arena["seed"], number)
            with self.db.connect() as connection:
                rows = connection.execute("SELECT id,strategy_config,model_config,workflow FROM merchants WHERE arena_id=? ORDER BY slot", (arena_id,)).fetchall()
            configs = {row["id"]: dict(row) for row in rows}
            results = {}
            offset = (arena["seed"] + number - 1) % len(previous["merchants"])
            ordered = previous["merchants"][offset:] + previous["merchants"][:offset]
            for merchant in ordered:
                if job:
                    with self.db.connect() as connection:
                        TaskStore.assert_lease(connection, job)
                observation = self.observation(arena, previous, merchant, market)
                config = configs[merchant["id"]]
                def sink(node, status, label, payload):
                    with self.db.connect() as conn:
                        if job:
                            TaskStore.assert_lease(conn, job)
                        self.events.append(arena_id, number, merchant["id"], node, status, label, payload, connection=conn)
                token = current_job.set(job)
                try:
                    with event_scope(sink):
                        results[merchant["id"]] = self.agents.run(arena_id, number, merchant["id"], observation,
                                                                 json.loads(config["strategy_config"]), merchant["mode"],
                                                                 json.loads(config["model_config"]), config["workflow"])
                finally:
                    current_job.reset(token)
            plans = {merchant_id: result["plan"] for merchant_id, result in results.items()}
            contracts = {merchant_id: {item["product_id"]: item for item in result["trace"].get("negotiation", {}).get("contracts", [])}
                         for merchant_id, result in results.items() if result["observation"].get("agent_options", {}).get("negotiation")}
            if arena["supply_policy"] == POLICY:
                contracts = allocate_orders(previous, plans, market, contracts, arena["seed"])
            snapshot, entries = settle(previous, plans, market, arena["initial_capital"], arena["seed"], contracts,
                                       reserve_marketing=arena["supply_policy"] == POLICY)
            for merchant in snapshot["merchants"]:
                result = results[merchant["id"]]
                negotiation = result["trace"].get("negotiation", {})
                merchant["procurement"] = purchase_outcomes(merchant, result["plan"], market, negotiation.get("contracts", []), entries)
                if arena["supply_policy"] == POLICY and negotiation:
                    result["trace"]["negotiation"] = {**negotiation, "contracts": list(contracts[merchant["id"]].values())}
            with self.db.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                if job:
                    TaskStore.assert_lease(connection, job)
                current = connection.execute("SELECT current_round,status FROM arenas WHERE id=?", (arena_id,)).fetchone()
                if current["current_round"] != expected_round:
                    raise ConflictError("该回合已经结算")
                if arena["supply_policy"] == POLICY:
                    for merchant_id, items in contracts.items():
                        for order in items.values():
                            connection.execute("INSERT INTO supplier_reservations(arena_id,round_number,merchant_id,product_id,supplier_id,quantity,unit_price,expires_round,status) VALUES(?,?,?,?,?,?,?,?,?)",
                                               (arena_id, number, merchant_id, order["product_id"], order["supplier_id"], order["quantity"], order["unit_price"], number, order["status"]))
                for merchant in snapshot["merchants"]:
                    connection.execute("UPDATE merchants SET cash=?,memory=? WHERE id=?", (merchant["cash"], merchant["memory"], merchant["id"]))
                    for stock in merchant["inventory"]:
                        connection.execute("UPDATE inventory SET quantity=?,book_value=?,price=? WHERE merchant_id=? AND product_id=?",
                                           (stock["quantity"], stock["book_value"], stock["price"], merchant["id"], stock["product_id"]))
                    result = results[merchant["id"]]
                    self.memory.record(connection, arena_id, number, merchant, result, market)
                    self.events.append(arena_id, number, merchant["id"], "settle", "completed", "经营结果已结算",
                                       {"merchant": merchant, "metrics": merchant["metrics"], "cash": merchant["cash"], "projection": result["trace"].get("projection"),
                                        "plan": result["plan"], "supply_policy": arena["supply_policy"]}, connection=connection)
                    connection.execute(
                        "INSERT INTO decisions(arena_id,round_number,merchant_id,plan,observation,tools,stages,input_tokens,output_tokens,duration_ms,model_config,trace) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (arena_id, number, merchant["id"], encode(result["plan"]), encode(result["observation"]), encode(result["tools"]), encode(result["stages"]), result["input_tokens"], result["output_tokens"], result["duration_ms"], encode(result.get("model_config", {})), encode(result.get("trace", {}))),
                    )
                for entry in entries:
                    connection.execute("INSERT INTO ledger(arena_id,round_number,merchant_id,kind,product_id,quantity,amount,balance) VALUES(?,?,?,?,?,?,?,?)",
                                       (arena_id, number, entry["merchant_id"], entry["kind"], entry["product_id"], entry["quantity"], entry["amount"], entry["balance"]))
                connection.execute("INSERT INTO rounds(arena_id,number,snapshot) VALUES(?,?,?)", (arena_id, number, encode(snapshot)))
                connection.execute("UPDATE supplier_reservations SET status='fulfilled' WHERE arena_id=? AND round_number=? AND status='reserved'", (arena_id, number))
                status = "completed" if number == arena["total_rounds"] else current["status"]
                connection.execute("UPDATE arenas SET current_round=?,status=?,error=NULL,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (number, status, arena_id))
            return snapshot

    def decisions(self, arena_id, round_number):
        with self.db.connect() as connection:
            rows = connection.execute("SELECT d.*,m.name,m.color,m.mode FROM decisions d JOIN merchants m ON m.id=d.merchant_id WHERE d.arena_id=? AND d.round_number=? ORDER BY m.slot", (arena_id, round_number)).fetchall()
        return [{**dict(row), "plan": json.loads(row["plan"]), "observation": json.loads(row["observation"]),
                 "tools": tool_records(json.loads(row["tools"])), "stages": json.loads(row["stages"]),
                 "model_config": json.loads(row["model_config"]), "trace": json.loads(row["trace"])} for row in rows]

    def detail(self, arena_id, round_number=None):
        arena = self.db.arena(arena_id)
        snapshot = self.db.snapshot(arena_id, round_number)
        with self.db.connect() as connection:
            rows = connection.execute("SELECT number,snapshot FROM rounds WHERE arena_id=? ORDER BY number", (arena_id,)).fetchall()
            tokens = connection.execute("SELECT COALESCE(SUM(input_tokens),0) AS input,COALESCE(SUM(output_tokens),0) AS output FROM decisions WHERE arena_id=?", (arena_id,)).fetchone()
        history = []
        for row in rows:
            item = json.loads(row["snapshot"])
            history.append({"round": row["number"], "event": item["market"]["event"]["name"],
                            "merchants": [{"id": merchant["id"], "profit": merchant["profit"], "revenue": merchant["metrics"]["revenue"], "sold": merchant["metrics"]["sold"], "equity": merchant["equity"]} for merchant in item["merchants"]]})
        decisions = self.decisions(arena_id, snapshot["round"])
        if decisions:
            with self.db.connect() as connection:
                entries = [dict(row) for row in connection.execute("SELECT * FROM ledger WHERE arena_id=? AND round_number=?", (arena_id, snapshot["round"]))]
            for merchant, decision in zip(snapshot["merchants"], decisions):
                if "procurement" not in merchant:
                    merchant["procurement"] = purchase_outcomes(merchant, decision["plan"], snapshot["market"], decision["trace"].get("negotiation", {}).get("contracts", []), entries)
        return {**arena, "snapshot": snapshot, "history": history, "decisions": decisions, "tokens": dict(tokens), "approvals": self.approvals.pending(arena_id)}

    def listing(self):
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM arenas ORDER BY id DESC").fetchall()
        result = []
        for row in rows:
            snapshot = self.db.snapshot(row["id"])
            merchants = snapshot["merchants"]
            leader = max(merchants, key=lambda item: item["equity"])
            result.append({**dict(row), "merchants": merchants, "leader": leader["name"], "leader_profit": leader["profit"],
                           "total_revenue": sum(item["total_revenue"] for item in merchants), "total_sold": sum(item["total_sold"] for item in merchants)})
        return result

    def fork(self, arena_id):
        arena = self.db.arena(arena_id)
        with self.db.connect() as connection:
            merchants = connection.execute("SELECT name,strategy_id,mode,color,strategy_config,model_profile_id,model_config,workflow,agent_options FROM merchants WHERE arena_id=? ORDER BY slot", (arena_id,)).fetchall()
        configs = {item["strategy_id"]: json.loads(item["strategy_config"]) for item in merchants}
        models = {index: json.loads(item["model_config"]) or self.require_model(item["model_profile_id"]) for index, item in enumerate(merchants) if item["mode"] == "llm"}
        return self.create(ArenaInput(name=arena["name"][:50] + " · 再赛", scenario=arena["scenario"], total_rounds=arena["total_rounds"], seed=arena["seed"],
                                      initial_capital=arena["initial_capital"], merchants=[MerchantInput(**{**dict(item), "agent_options": json.loads(item["agent_options"])}) for item in merchants]), strategy_configs=configs, model_configs=models)

    def fork_at(self, arena_id, config):
        source = self.db.arena(arena_id)
        number = config.round
        if number >= source["total_rounds"]:
            raise ValueError("请选择尚有后续回合的分叉点")
        snapshot = self.db.snapshot(arena_id, number)
        with self.db.connect() as conn:
            originals = [dict(row) for row in conn.execute("SELECT * FROM merchants WHERE arena_id=? ORDER BY slot", (arena_id,))]
        merchants = config.merchants or [MerchantInput(**{**item, "agent_options": json.loads(item["agent_options"])}) for item in originals]
        if len(merchants) != len(originals):
            raise ValueError("分叉必须保留商店数量和席位")
        strategies = {item["strategy_id"]: json.loads(item["strategy_config"]) for item in originals}
        if config.merchants:
            strategies.update({item.strategy_id: self.db.strategy(item.strategy_id) for index, item in enumerate(merchants) if item.strategy_id != originals[index]["strategy_id"]})
        models = {index: self.require_model(item.model_profile_id) if config.merchants and item.model_profile_id != originals[index]["model_profile_id"] else json.loads(originals[index]["model_config"])
                  for index, item in enumerate(merchants) if item.mode == "llm"}
        fork = self.create(ArenaInput(name=source["name"][:40] + f" · 第{number}轮分叉", scenario=source["scenario"], seed=source["seed"],
                                     total_rounds=source["total_rounds"], initial_capital=source["initial_capital"], merchants=merchants, approval_policy=config.approval_policy),
                           strategy_configs=strategies, model_configs=models, supply_policy=source["supply_policy"])
        new_merchants = fork["snapshot"]["merchants"]
        mapping = {old["id"]: new["id"] for old, new in zip(originals, new_merchants)}
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM rounds WHERE arena_id=? AND number=0", (fork["id"],))
            for row in conn.execute("SELECT * FROM rounds WHERE arena_id=? AND number<=? ORDER BY number", (arena_id, number)).fetchall():
                copied = json.loads(row["snapshot"])
                for index, store in enumerate(copied["merchants"]):
                    store["id"] = mapping[store["id"]]
                    if row["number"] == number:
                        store.update({key: new_merchants[index][key] for key in ["name", "color", "strategy_id", "strategy_name", "mode", "model_config", "workflow", "agent_options", "entrant_id"]})
                conn.execute("INSERT INTO rounds(arena_id,number,snapshot) VALUES(?,?,?)", (fork["id"], row["number"], encode(copied)))
            evidence_mapping = {}
            for row in conn.execute("SELECT * FROM experiences WHERE arena_id=? AND round_number<=?", (arena_id, number)).fetchall():
                copied = conn.execute("INSERT INTO experiences(arena_id,merchant_id,round_number,context,action,outcome) VALUES(?,?,?,?,?,?)", (fork["id"], mapping[row["merchant_id"]], row["round_number"], row["context"], row["action"], row["outcome"]))
                evidence_mapping[row["id"]] = copied.lastrowid
            def remap_evidence(items):
                for item in items:
                    item["evidence_id"] = evidence_mapping.get(item["evidence_id"], item["evidence_id"])
            for row in conn.execute("SELECT * FROM decisions WHERE arena_id=? AND round_number<=? ORDER BY round_number,merchant_id", (arena_id, number)).fetchall():
                observation = json.loads(row["observation"])
                observation["arena_id"] = fork["id"]
                observation["store"]["id"] = mapping[row["merchant_id"]]
                remap_evidence(observation.get("experiences", []))
                trace = json.loads(row["trace"])
                remap_evidence(trace.get("memory", []))
                conn.execute("INSERT INTO decisions(arena_id,round_number,merchant_id,plan,observation,tools,stages,input_tokens,output_tokens,duration_ms,model_config,trace) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                             (fork["id"], row["round_number"], mapping[row["merchant_id"]], row["plan"], encode(observation), row["tools"], row["stages"], row["input_tokens"], row["output_tokens"], row["duration_ms"], row["model_config"], encode(trace)))
            for row in conn.execute("SELECT * FROM decision_events WHERE arena_id=? AND round_number<=? ORDER BY id", (arena_id, number)).fetchall():
                payload = {**json.loads(row["payload"]), "origin_event_id": row["id"], "origin_arena_id": arena_id}
                if "merchant" in payload:
                    payload["merchant"]["id"] = mapping[payload["merchant"]["id"]]
                remap_evidence(payload.get("evidence", {}).get("experiences", []))
                conn.execute("INSERT INTO decision_events(arena_id,round_number,merchant_id,node,status,label,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",
                             (fork["id"], row["round_number"], mapping.get(row["merchant_id"]), row["node"], row["status"], row["label"], encode(payload), row["created_at"]))
            for row in conn.execute("SELECT * FROM ledger WHERE arena_id=? AND round_number<=? ORDER BY id", (arena_id, number)).fetchall():
                conn.execute("INSERT INTO ledger(arena_id,round_number,merchant_id,kind,product_id,quantity,amount,balance) VALUES(?,?,?,?,?,?,?,?)", (fork["id"], row["round_number"], mapping[row["merchant_id"]], row["kind"], row["product_id"], row["quantity"], row["amount"], row["balance"]))
            for old in snapshot["merchants"]:
                merchant_id = mapping[old["id"]]
                conn.execute("UPDATE merchants SET cash=?,memory=? WHERE id=?", (old["cash"], old["memory"], merchant_id))
                for stock in old["inventory"]:
                    conn.execute("UPDATE inventory SET quantity=?,book_value=?,price=? WHERE merchant_id=? AND product_id=?", (stock["quantity"], stock["book_value"], stock["price"], merchant_id, stock["product_id"]))
            conn.execute("UPDATE arenas SET current_round=?,parent_arena_id=?,fork_round=? WHERE id=?", (number, arena_id, number, fork["id"]))
        return self.detail(fork["id"])

    def comparison(self, arena_id):
        fork = self.detail(arena_id)
        if not fork.get("parent_arena_id"):
            return {"parent": None, "fork_round": None, "points": []}
        parent = self.detail(fork["parent_arena_id"])
        points = []
        for item in fork["history"]:
            original = next((point for point in parent["history"] if point["round"] == item["round"]), None)
            if original:
                points.append({"round": item["round"], "merchants": [{"name": store["name"], "parent_profit": original["merchants"][index]["profit"], "fork_profit": item["merchants"][index]["profit"], "difference": item["merchants"][index]["profit"] - original["merchants"][index]["profit"]} for index, store in enumerate(fork["snapshot"]["merchants"])]})
        return {"parent": {"id": parent["id"], "name": parent["name"], "current_round": parent["current_round"]}, "fork_round": fork["fork_round"], "points": points}

    def ledger(self, arena_id, round_number=None, merchant_id=None):
        self.db.arena(arena_id)
        query = "SELECT l.*,m.name AS merchant_name FROM ledger l JOIN merchants m ON l.merchant_id=m.id WHERE l.arena_id=?"
        parameters = [arena_id]
        if round_number is not None:
            query += " AND l.round_number=?"
            parameters.append(round_number)
        if merchant_id is not None:
            query += " AND l.merchant_id=?"
            parameters.append(merchant_id)
        with self.db.connect() as connection:
            return [dict(row) for row in connection.execute(query + " ORDER BY l.id DESC", parameters)]

    def create_experiment(self, config, strategy_configs=None, profile_configs=None, supply_policy=POLICY):
        with self.db.connect() as connection:
            existing = [json.loads(row["config"]) for row in connection.execute("SELECT config FROM experiments")]
        for previous in existing:
            if previous.get("split") and previous["split"] != config.split and previous["scenario"] == config.scenario:
                overlap = set(previous["seeds"]) & set(config.seeds)
                if overlap:
                    raise ValueError("开发集与保留集不能共用种子：" + ", ".join(str(seed) for seed in sorted(overlap)))
        variants = config.variants or [ExperimentVariant(name=self.db.strategy(strategy_id)["name"], strategy_id=strategy_id,
                                                        mode=config.mode, model_profile_id=config.model_profile_id, workflow=config.workflow) for strategy_id in config.strategy_ids]
        strategy_configs = strategy_configs or {item.strategy_id: self.db.strategy(item.strategy_id) for item in variants}
        stored_variants = [{**item.model_dump(), "id": f"variant-{index + 1}", "model_config": profile_configs[index] if profile_configs is not None else self.require_model(item.model_profile_id) if item.mode == "llm" else {}} for index, item in enumerate(variants)]
        with self.db.connect() as connection:
            stored_config = {**config.model_dump(), "strategies": strategy_configs, "variants": stored_variants, "supply_policy": supply_policy}
            cursor = connection.execute("INSERT INTO experiments(name,config) VALUES(?,?)", (config.name, encode(stored_config)))
            experiment_id = cursor.lastrowid
        for index, seed in enumerate(config.seeds):
            offset = index % len(stored_variants)
            rotated = stored_variants[offset:] + stored_variants[:offset]
            merchants = [MerchantInput(name=item["name"][:20], strategy_id=item["strategy_id"], color=COLORS[slot], mode=item["mode"],
                                      model_profile_id=item["model_profile_id"], workflow=item["workflow"], entrant_id=item["id"], agent_options=item["agent_options"]) for slot, item in enumerate(rotated)]
            models = {slot: item["model_config"] for slot, item in enumerate(rotated) if item["mode"] == "llm"}
            self.create(ArenaInput(name=f"{config.name[:50]} · {index + 1}", scenario=config.scenario, total_rounds=config.rounds, seed=seed, merchants=merchants), experiment_id, strategy_configs, models, supply_policy=supply_policy)
        return self.experiment(experiment_id)

    def experiment(self, experiment_id):
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
            arenas = connection.execute("SELECT id FROM arenas WHERE experiment_id=? ORDER BY id", (experiment_id,)).fetchall()
        if row is None:
            raise KeyError("实验不存在")
        arena_ids = {item["id"] for item in arenas}
        matches = [item for item in self.listing() if item["id"] in arena_ids]
        config = json.loads(row["config"])
        if config.get("variants"):
            evaluation = evaluate_experiment(self.db, matches, config)
            completed = sum(item["status"] == "completed" for item in matches)
            status = "completed" if completed == len(matches) else "running" if any(item["status"] == "running" for item in matches) else "ready"
            return {**dict(row), "config": config, "arenas": matches, **evaluation, "completed": completed, "status": status}
        outcomes = defaultdict(list)
        wins = defaultdict(float)
        for arena in matches:
            if arena["status"] != "completed":
                continue
            highest = max(item["profit"] for item in arena["merchants"])
            winners = [item for item in arena["merchants"] if item["profit"] == highest]
            for merchant in arena["merchants"]:
                outcomes[merchant["strategy_id"]].append(merchant["profit"])
            for merchant in winners:
                wins[merchant["strategy_id"]] += 1 / len(winners)
        scores = []
        for strategy_id in config["strategy_ids"]:
            values = outcomes[strategy_id]
            strategy = config["strategies"][strategy_id]
            scores.append({"strategy_id": strategy_id, "name": strategy["name"], "color": strategy["color"], "samples": len(values),
                           "average_profit": round(statistics.mean(values)) if values else 0,
                           "deviation": round(statistics.pstdev(values)) if values else 0,
                           "win_rate": round(wins[strategy_id] / len(values) * 100, 1) if values else 0})
        completed = sum(item["status"] == "completed" for item in matches)
        status = "completed" if completed == len(matches) else "running" if any(item["status"] == "running" for item in matches) else "ready"
        return {**dict(row), "config": config, "arenas": matches, "scores": sorted(scores, key=lambda item: item["average_profit"], reverse=True), "completed": completed, "status": status}

    def experiments(self):
        with self.db.connect() as connection:
            ids = [row["id"] for row in connection.execute("SELECT id FROM experiments ORDER BY id DESC")]
        return [self.experiment(item) for item in ids]
