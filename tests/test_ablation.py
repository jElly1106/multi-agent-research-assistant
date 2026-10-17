from __future__ import annotations

from unittest.mock import Mock

from examples.critic_mock_demo import load_fixture, make_node_factory
from research_assistant.ablation import run_ablation


def test_missing_plan_is_generated_once_and_shared_between_arms(monkeypatch):
    fixture = load_fixture()
    planner = Mock(return_value={
        "research_questions": fixture["initial_state"]["research_questions"],
        "research_scope": "fixed scope",
    })
    monkeypatch.setattr("research_assistant.ablation.coordinator_node", planner)
    result = run_ablation({"topic": "fixed topic", "max_critic_rounds": 2}, make_node_factory(fixture))
    planner.assert_called_once()
    assert result["without_critic"]["state"]["research_scope"] == "fixed scope"
    assert result["with_critic"]["state"]["research_scope"] == "fixed scope"


def test_existing_plan_prevents_extra_planner_call(monkeypatch):
    fixture = load_fixture()
    planner = Mock(side_effect=AssertionError("must preserve provided plan"))
    monkeypatch.setattr("research_assistant.ablation.coordinator_node", planner)
    run_ablation(fixture["initial_state"], make_node_factory(fixture))
    planner.assert_not_called()
