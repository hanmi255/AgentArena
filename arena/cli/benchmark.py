"""Free, fixed-seed smoke benchmark. Does not call a model provider."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from arena.api.app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("test-results/rule-baseline.json"))
    args = parser.parse_args()
    with TemporaryDirectory(prefix="arena-benchmark-") as directory:
        with TestClient(create_app(Path(directory), seed_demo=False, redis_url="")) as client:
            response = client.post("/api/experiments", json={
                "name": "固定规则基线", "rounds": 6, "scenario": "neighborhood",
                "seeds": [11, 23, 37, 41, 53], "split": "development",
                "variants": [
                    {"name": "直接决策", "strategy_id": "balanced", "workflow": "direct"},
                    {"name": "每轮多候选审核", "strategy_id": "balanced", "workflow": "reviewed"},
                    {"name": "按风险展开", "strategy_id": "balanced", "workflow": "adaptive"},
                ],
            })
            response.raise_for_status()
            experiment = response.json()
            service = client.app.state.service
            for arena in experiment["arenas"]:
                for number in range(6):
                    service.advance(arena["id"], number)
                service.db.set_status(arena["id"], "completed")
            report = client.get(f"/api/experiments/{experiment['id']}").json()
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            for score in report["scores"]:
                print(f"{score['name']}: {score['samples']} samples, mean profit {score['average_profit'] / 100:.2f}, stockout {score['stockout_rate']}%")
            print(f"Report: {args.report}. Rule-only samples do not establish LLM effectiveness.")


if __name__ == "__main__":
    main()
