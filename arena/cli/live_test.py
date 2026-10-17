"""Opt-in paid provider check; credentials and databases live only during the test."""

import argparse
import getpass
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from arena.api.app import create_app
from arena.domain.models import Decision
from arena.infrastructure.database import Database
from arena.infrastructure.config import DATA_DIR


def main():
    parser = argparse.ArgumentParser(description="Run a three-round real-model competition")
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--models", help="Comma-separated models, one per store")
    parser.add_argument("--thinking", choices=["disabled", "enabled"], default="disabled")
    parser.add_argument("--workflow", choices=["direct", "reviewed", "adaptive"], default="direct")
    parser.add_argument("--negotiation", action="store_true")
    parser.add_argument("--memory", choices=["none", "recent", "episodic"], default="recent")
    parser.add_argument("--key-file", type=Path, help="Read a local key file without echoing it")
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--tool-budget", type=int, choices=range(1, 11), default=4)
    parser.add_argument("--workspace-key", action="store_true", help="Use the saved default connection key without printing it")
    parser.add_argument("--steps", type=int, choices=[1, 2, 3], default=3)
    parser.add_argument("--report", type=Path, default=Path("test-results/live-model-report.json"))
    args = parser.parse_args()
    if args.key_file:
        api_key = args.key_file.read_text(encoding="utf-8").strip()
    elif args.workspace_key:
        api_key = Database(DATA_DIR).model_settings()["api_key"]
    else:
        api_key = os.environ.get("LIVE_MODEL_API_KEY") or getpass.getpass("Model API key: ")
    models = args.models.split(",") if args.models else [args.model]
    if not 1 <= len(models) <= 4:
        parser.error("Choose between one and four models")
    started = time.monotonic()
    with TemporaryDirectory(prefix="agent-arena-live-") as directory:
        with TestClient(create_app(Path(directory), seed_demo=False, redis_url="", execution_mode="embedded")) as client:
            merchants = []
            for index, model in enumerate(models):
                response = client.post("/api/model-profiles", json={
                    "name": model, "base_url": args.base_url, "model": model, "api_key": api_key,
                    "temperature": 0.4, "timeout": 120, "max_steps": 20, "provider": "deepseek",
                    "thinking": args.thinking, "max_tokens": args.max_tokens,
                })
                response.raise_for_status()
                merchants.append({"name": f"模型商店 {index + 1}", "strategy_id": "adaptive", "mode": "llm", "color": ["violet", "orange", "teal", "blue"][index],
                                  "model_profile_id": response.json()["id"], "workflow": args.workflow,
                                  "agent_options": {"memory": args.memory, "negotiation": args.negotiation, "tool_budget": args.tool_budget}})
            if len(merchants) == 1:
                merchants.append({"name": "规则商店", "strategy_id": "balanced", "mode": "rule", "color": "teal"})
            config = {
                "name": "真实模型验收", "scenario": "festival", "seed": 73,
                "total_rounds": 3, "initial_capital": 1000000,
                "merchants": merchants,
            }
            response = client.post("/api/arenas", json=config)
            response.raise_for_status()
            arena_id = response.json()["id"]
            decisions = []
            usage_records = []
            for number in range(args.steps):
                print(f"Round {number + 1}/{args.steps}: requesting {len(models)} model decisions...", flush=True)
                response = client.post(f"/api/arenas/{arena_id}/step", json={"expected_round": number})
                if response.status_code != 200:
                    checkpoints = []
                    seen = set()
                    for checkpoint in client.app.state.service.agents.checkpointer.list(None, limit=100):
                        identity = str(checkpoint.config["configurable"].get("thread_id")) + "/" + checkpoint.config["configurable"].get("checkpoint_ns", "")
                        if identity in seen:
                            continue
                        seen.add(identity)
                        messages = checkpoint.checkpoint.get("channel_values", {}).get("messages", [])
                        if messages:
                            checkpoints.append({"thread": identity, "messages": [
                                {"type": item.type, "tools": [call["name"] for call in item.tool_calls] if isinstance(item, AIMessage) else [],
                                 "tool_result": str(item.content)[:500] if isinstance(item, ToolMessage) else ""} for item in messages]})
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.with_suffix(".failure.json").write_text(json.dumps({"error": response.json(), "checkpoints": checkpoints}, ensure_ascii=False, indent=2).replace(api_key, "[redacted]"), encoding="utf-8")
                    raise RuntimeError(f"Provider check failed: HTTP {response.status_code} {response.text.replace(api_key, '[redacted]')}")
                arena = response.json()
                for decision in (item for item in arena["decisions"] if item["mode"] == "llm"):
                    print(f"Usage: {decision['input_tokens']} input + {decision['output_tokens']} output tokens", flush=True)
                    usage_records.append({"round": number + 1, "model": decision["model_config"]["model"],
                                          "input_tokens": decision["input_tokens"], "output_tokens": decision["output_tokens"]})
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.with_suffix(".usage.json").write_text(json.dumps(usage_records, indent=2), encoding="utf-8")
                    Decision.model_validate(decision["plan"])
                    assert decision["input_tokens"] > 0 and decision["output_tokens"] > 0
                    if args.workflow == "adaptive":
                        assert decision["trace"]["routing"]["objective"]
                        executed = [event for event in client.get(f"/api/arenas/{arena_id}/timeline?round={number + 1}").json()
                                    if event["merchant_id"] == decision["merchant_id"] and event["status"] == "tool_completed"]
                        assert len(executed) <= args.tool_budget, f"Executed {len(executed)} tools beyond budget"
                    # Zero tools is valid when the initial business context is sufficient.
                    # Tool protocol is tested separately by the connection probe.
                    allowed = {"inspect_store", "observe_market", "review_history", "evaluate_plan", "recall_experience"}
                    assert all(item["name"] in allowed for item in decision["tools"])
                    if args.negotiation:
                        assert decision["trace"]["negotiation"]["messages"]
                    if args.workflow == "reviewed":
                        assert len(decision["trace"]["candidates"]) >= 2 and decision["trace"]["reviews"][-1]["approved"]
                    decisions.append(decision)
                    print(f"Round {number + 1}: {decision['model_config']['model']} settled; tokens {decision['input_tokens']} + {decision['output_tokens']}", flush=True)
            assert arena["status"] == ("completed" if args.steps == 3 else "paused") and arena["current_round"] == args.steps
            export = client.get(f"/api/arenas/{arena_id}/export").json()
            assert len(export["snapshots"]) == args.steps + 1
            assert len(export["decisions"]) == args.steps * len(merchants)
            assert export["ledger"]
            for round_number in range(1, args.steps + 1):
                replay = client.get(f"/api/arenas/{arena_id}?round={round_number}").json()
                assert replay["snapshot"]["round"] == round_number
            initial = export["snapshots"][0]
            for merchant in arena["snapshot"]["merchants"]:
                entries = [item for item in export["ledger"] if item["merchant_id"] == merchant["id"]]
                starting_cash = next(item["cash"] for item in initial["merchants"] if item["id"] == merchant["id"])
                assert starting_cash + sum(item["amount"] for item in entries) == merchant["cash"]
            report = {
                "tested_at": datetime.now(timezone.utc).isoformat(), "provider": args.base_url,
                "model": models[0] if len(models) == 1 else "mixed", "models": models, "thinking": args.thinking, "workflow": args.workflow, "rounds": args.steps, "status": arena["status"],
                "duration_seconds": round(time.monotonic() - started, 2),
                "input_tokens": sum(item["input_tokens"] for item in decisions),
                "output_tokens": sum(item["output_tokens"] for item in decisions),
                "decisions": decisions, "export": export, "events": client.get(f"/api/arenas/{arena_id}/timeline?limit=1000").json(),
            }
            encoded = json.dumps(report, ensure_ascii=False, indent=2)
            assert api_key not in encoded
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(encoded, encoding="utf-8")
            print(f"PASS real model, tools, settlement, ledger and replay; report: {args.report}", flush=True)


if __name__ == "__main__":
    main()
