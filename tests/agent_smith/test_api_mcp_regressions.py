from __future__ import annotations

import pytest

from src.agent_smith import mcp_servers


@pytest.mark.asyncio
async def test_plans_api_and_mcp_share_persistence(agent_smith_client):
    response = await agent_smith_client.post(
        "/api/plans",
        json={"title": "Port Plan", "body": "Ship the Agent Smith port.", "project": "agent-smith"},
    )

    assert response.status_code == 201
    created = response.json()
    fetched = await mcp_servers.get(plan_id=created["id"])
    searched = await mcp_servers.get(query="Agent Smith port")

    assert fetched["title"] == "Port Plan"
    assert searched[0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_harness_api_and_mcp_share_persistence(agent_smith_client):
    response = await agent_smith_client.post(
        "/api/harness/items/rule",
        json={
            "name": "port_rule",
            "project": "agent-smith",
            "agents": ["codex"],
            "content": {"body": "Use the Agent Smith service layer."},
        },
    )

    assert response.status_code == 201
    created = response.json()
    fetched = await mcp_servers.harness_get(name="port_rule", item_type="rule", project="agent-smith")
    listed = await mcp_servers.harness_list(item_type="rule", project="agent-smith", agent="codex")

    assert fetched["id"] == created["id"]
    assert listed[0]["name"] == "port_rule"


@pytest.mark.asyncio
async def test_eval_config_api_and_mcp_share_persistence(agent_smith_client):
    response = await agent_smith_client.post(
        "/api/eval-configs/suites",
        json={
            "name": "port_suite",
            "eval_type": "rules",
            "subcategory": "port",
            "judge_prompt": "Judge the port.",
            "items": {},
            "config": {},
            "enabled": True,
        },
    )
    assert response.status_code == 201
    suite = response.json()

    scenario_message = await mcp_servers.eval_scenario_save(
        suite_name="port_suite",
        name="smoke",
        prompt="Exercise the route.",
    )
    suite_from_mcp = await mcp_servers.eval_suite_get(suite_id=suite["id"])

    assert "Eval scenario saved" in scenario_message
    assert suite_from_mcp["name"] == "port_suite"
    assert suite_from_mcp["scenarios"][0]["name"] == "smoke"


class FakeMemoryService:
    def __init__(self) -> None:
        self.rows = {
            "11111111-1111-1111-1111-111111111111": {
                "id": "11111111-1111-1111-1111-111111111111",
                "content": "remember the Agent Smith port",
                "repo": "agent-smith",
                "tags": ["port"],
            }
        }

    def search(self, **_kwargs):
        return list(self.rows.values())

    def list_memories(self, **_kwargs):
        return list(self.rows.values())

    def get(self, memory_id: str):
        return self.rows.get(memory_id)

    def update(self, memory_id: str, *, content: str | None, repo: str | None, tags: list[str] | None) -> None:
        row = self.rows[memory_id]
        if content is not None:
            row["content"] = content
        if repo is not None:
            row["repo"] = repo
        if tags is not None:
            row["tags"] = tags

    def delete(self, memory_id: str) -> None:
        self.rows.pop(memory_id, None)


@pytest.mark.asyncio
async def test_memory_api_uses_agent_smith_memory_service(agent_smith_client, monkeypatch):
    from src.agent_smith.routers import memory

    fake_service = FakeMemoryService()
    monkeypatch.setattr(memory, "get_memory_service", lambda: fake_service)

    listed = await agent_smith_client.get("/api/memory/list?repo=agent-smith")
    updated = await agent_smith_client.put(
        "/api/memory/11111111-1111-1111-1111-111111111111",
        json={"content": "updated", "tags": ["done"]},
    )
    deleted = await agent_smith_client.delete("/api/memory/11111111-1111-1111-1111-111111111111")

    assert listed.status_code == 200
    assert listed.json()["items"][0]["content"] == "remember the Agent Smith port"
    assert updated.status_code == 200
    assert updated.json()["content"] == "updated"
    assert deleted.status_code == 200
