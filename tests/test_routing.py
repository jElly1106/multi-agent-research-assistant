from research_assistant.graph import route_after_critic


def test_pass_routes_to_writer():
    state = {
        "critic_result": {"decision": "PASS"},
        "critic_round": 1,
        "max_critic_rounds": 2,
    }
    assert route_after_critic(state) == "writer"


def test_fail_routes_back_to_search():
    state = {
        "critic_result": {"decision": "FAIL"},
        "critic_round": 1,
        "max_critic_rounds": 2,
    }
    assert route_after_critic(state) == "search"


def test_fail_after_max_rounds_routes_to_writer():
    state = {
        "critic_result": {"decision": "FAIL"},
        "critic_round": 2,
        "max_critic_rounds": 2,
    }
    assert route_after_critic(state) == "writer"
