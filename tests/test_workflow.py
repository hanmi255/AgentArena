import copy

from arena.domain.simulation import simulate_plan
from tests.test_model import ModelHandler, configure


def test_reviewed_rule_workflow_runs_scenarios_and_checks_budget(client, arena_config):
    for merchant in arena_config["merchants"]:
        merchant["workflow"] = "reviewed"
    arena = client.post("/api/arenas", json=arena_config).json()
    for number in range(5):
        result = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": number})
        assert result.status_code == 200, result.text
        for decision in result.json()["decisions"]:
            trace = decision["trace"]
            assert decision["tools"] == []
            assert trace["routing"]["tools"] == []
            assert decision["input_tokens"] == decision["output_tokens"] == 0
            assert len(trace["candidates"]) == 2
            assert trace["reviews"][-1]["approved"]
            assert all(len(candidate["scenarios"]) == 3 for candidate in trace["candidates"])
        events = client.get(f"/api/arenas/{arena['id']}/timeline?round={number + 1}").json()
        assert not any(event["status"] in {"tool_started", "tool_completed", "model_started", "model_completed"} for event in events)


def test_planner_and_reviewer_can_revise_before_settlement(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0].update(mode="llm", workflow="reviewed")
    arena = client.post("/api/arenas", json=arena_config).json()
    ModelHandler.review_rejections = 1
    result = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert result.status_code == 200, result.text
    decision = result.json()["decisions"][0]
    assert decision["trace"]["revisions"] == 1
    assert [review["approved"] for review in decision["trace"]["reviews"]] == [False, True]
    assert len(decision["trace"]["candidates"]) == 2
    assert len([stage for stage in decision["stages"] if stage["node"] == "decide"]) == 2
    assert result.json()["current_round"] == 1


def test_inner_agent_recovers_after_provider_failure_without_repeating_completed_tool(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0]["mode"] = "llm"
    arena = client.post("/api/arenas", json=arena_config).json()
    ModelHandler.fail_after_inspection = True
    first = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert first.status_code == 400
    assert client.get(f"/api/arenas/{arena['id']}").json()["current_round"] == 0
    calls_before = len(ModelHandler.requests)
    result = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert result.status_code == 200, result.text
    # The resumed call already contains inspect_store's result; the tool is not regenerated.
    resumed = ModelHandler.requests[calls_before]
    assert any(message["role"] == "tool" and message["tool_call_id"] == "call-inspect_store" for message in resumed["messages"])
    assert len(result.json()["decisions"][0]["tools"]) == 3


def test_projection_uses_only_visible_observation_and_never_mutates_it(client, arena_config):
    arena = client.post("/api/arenas", json=arena_config).json()
    result = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0}).json()["decisions"][0]
    original = copy.deepcopy(result["observation"])
    projected = simulate_plan(original, result["plan"])
    assert original == result["observation"]
    assert projected == simulate_plan(original, result["plan"])
    assert "seed" not in original


def test_original_three_node_failed_checkpoint_can_resume(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0]["mode"] = "llm"
    arena = client.post("/api/arenas", json=arena_config).json()
    merchant = arena["snapshot"]["merchants"][0]
    service = client.app.state.service
    observation = service.observation(service.db.arena(arena["id"]), arena["snapshot"], merchant, arena["snapshot"]["market"])
    config = {"configurable": {"thread_id": f"arena-{arena['id']}/round-1/merchant-{merchant['id']}"}}
    # Original checkpoints did not include model assignments or inner graph IDs.
    service.agents.graph.update_state(config, {"observation": observation, "strategy": service.db.strategy("balanced"), "mode": "llm",
                                               "tools": [], "stages": [{"node": "observe", "label": "观察市场", "status": "completed"}], "started_at": 1.0}, as_node="observe")
    result = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert result.status_code == 200, result.text
    assert result.json()["current_round"] == 1


def test_parallel_duplicate_tool_calls_do_not_execute_past_budget(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0]["mode"] = "llm"
    arena = client.post("/api/arenas", json=arena_config).json()
    ModelHandler.repeat_reads = True
    response = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert response.status_code == 200, response.text
    reads = [item for item in response.json()["decisions"][0]["tools"] if item["name"] == "inspect_store"]
    assert len(reads) == 2
    assert "额度已用完" in reads[1]["result"]
    assert reads[0]["executed"] is True and reads[1]["executed"] is False


def test_repeated_review_rejection_stops_after_two_revisions_without_settlement(client, arena_config, model_server):
    configure(client, model_server)
    arena_config["merchants"][0].update(mode="llm", workflow="reviewed")
    arena = client.post("/api/arenas", json=arena_config).json()
    ModelHandler.review_rejections = 3
    response = client.post(f"/api/arenas/{arena['id']}/step", json={"expected_round": 0})
    assert response.status_code == 400
    assert "连续审核未通过" in response.json()["detail"]
    assert client.get(f"/api/arenas/{arena['id']}/ledger").json() == []
    assert client.get(f"/api/arenas/{arena['id']}").json()["current_round"] == 0
    reviews = [item for item in ModelHandler.requests if len(item.get("tools", [])) == 1 and item["tools"][0]["function"]["name"] == "PlanReview"]
    assert len(reviews) == 3
