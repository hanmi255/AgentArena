"""Bounded selection on development outcomes, followed by untouched validation seeds."""

from arena.domain.models import ExperimentInput, ExperimentVariant
from arena.infrastructure.database import encode
from arena.domain.procurement import LEGACY_POLICY


def select_and_validate(service, experiment_id, request):
    development = service.experiment(experiment_id)
    if development["config"].get("split") != "development" or development["status"] != "completed":
        raise ValueError("只能从已完成的开发集实验筛选策略")
    if set(development["config"]["seeds"]) & set(request.seeds):
        raise ValueError("独立验证不能复用开发种子")
    eligible = [item for item in development["scores"] if item["bankruptcy_rate"] == 0]
    if not eligible:
        raise ValueError("开发集所有方案均有破产记录，请先调整候选策略")
    selected = max(eligible, key=lambda item: (item["average_profit"], -item["total_tokens"]))
    variants = development["config"]["variants"]
    winner = next(item for item in variants if item["id"] == selected["variant_id"])
    baseline = variants[0] if variants[0]["id"] != winner["id"] else variants[1]
    required = development["config"]["rounds"] * len(request.seeds) * 2
    if required > request.round_budget:
        raise ValueError(f"本次验证需要 {required} 个商店回合，超过预算 {request.round_budget}")
    config = ExperimentInput(name=development["name"][:40] + " · 独立验证", scenario=development["config"]["scenario"],
                             rounds=development["config"]["rounds"], seeds=request.seeds, split="holdout",
                             variants=[ExperimentVariant.model_validate(item) for item in [baseline, winner]])
    validation = service.create_experiment(config, strategy_configs=development["config"]["strategies"], profile_configs=[item["model_config"] for item in [baseline, winner]],
                                           supply_policy=development["config"].get("supply_policy", LEGACY_POLICY))
    stored = validation["config"]
    stored["selection"] = {"development_id": experiment_id, "selected_variant": winner["name"], "rule": "无破产方案中开发集平均收益最大；同收益选 Token 更少者", "round_budget": request.round_budget,
                           "required_store_rounds": required, "warning": "开发集选择有偏；是否有效以独立验证结果为准"}
    with service.db.connect() as conn:
        conn.execute("UPDATE experiments SET config=? WHERE id=?", (encode(stored), validation["id"]))
    return service.experiment(validation["id"])
