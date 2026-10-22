"""Agent Card validation: every agent must serve a real, schema-valid card
whose skills match what its executor actually supports."""
import pytest
from fastapi.testclient import TestClient

from agents.agent_1.main.main import app as agent1_app
from agents.agent_1.skills.tools import get_tools as agent1_tools
from agents.agent_2.main.main import app as agent2_app
from agents.agent_2.skills.tools import get_tools as agent2_tools
from agents.agent_3.main.main import app as agent3_app
from agents.agent_3.skills.tools import get_tools as agent3_tools
from agents.agent_4.main.main import app as agent4_app
from agents.agent_4.skills.tools import get_tools as agent4_tools
from shared.a2a_protocol.schemas import AgentCard

CASES = [
    (agent1_app, agent1_tools, "email-intake-agent"),
    (agent2_app, agent2_tools, "validator-agent"),
    (agent3_app, agent3_tools, "extraction-agent"),
    (agent4_app, agent4_tools, "erp-push-agent"),
]


@pytest.mark.parametrize("app, get_tools, expected_id", CASES)
def test_agent_card_is_schema_valid_and_matches_tools(app, get_tools, expected_id):
    client = TestClient(app)
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200

    card = AgentCard(**response.json())
    assert card.id == expected_id
    assert card.url  # populated from settings, not hardcoded placeholder-only

    advertised_skill_ids = {skill.id for skill in card.skills}
    tool_names = {tool.name for tool in get_tools()}
    assert advertised_skill_ids == tool_names, "Agent Card skills must exactly match the tools the crew can call"


@pytest.mark.parametrize("app, get_tools, expected_id", CASES)
def test_health_endpoint_reports_agent_identity(app, get_tools, expected_id):
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["agentId"] == expected_id
