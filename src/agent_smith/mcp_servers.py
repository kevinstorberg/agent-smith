from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from db.unit_of_work import unit_of_work
from src.agent_smith.responses import empty_to_none
from src.agent_smith.services.evals import EvalService
from src.agent_smith.services.graphs import get_graph_service
from src.agent_smith.services.harness import HarnessService
from src.agent_smith.services.jobs import JobService
from src.agent_smith.services.memory import DEFAULT_LIMIT, get_memory_service
from src.agent_smith.services.plans import PlanService
from src.agent_smith.validation import validate_item_type

memory_mcp = FastMCP("memory - store and search observations, learnings, and context")
plans_mcp = FastMCP("plans - save and retrieve implementation plans and strategies")
harness_mcp = FastMCP("harness - manage rules, skills, tools, hooks, and agents")
evals_mcp = FastMCP("evals - manage evaluation suites and scenarios")
graphs_mcp = FastMCP("graphs - run hardcoded LangGraph workflows")
jobs_mcp = FastMCP("jobs - manage background jobs, scheduling, and execution history")


@memory_mcp.tool()
def memory_add(content: str, repo: str = "", tags: list[str] | None = None) -> str:
    """Store an observation, learning, or context note."""
    return get_memory_service().add(content=content, repo=empty_to_none(repo), tags=tags or [])


@memory_mcp.tool()
def memory_search(query: str, repo: str = "", limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Semantically search memories using vector similarity."""
    return get_memory_service().search(query=query, repo=empty_to_none(repo), limit=limit)


@memory_mcp.tool()
def memory_list(repo: str = "", limit: int = DEFAULT_LIMIT) -> list[dict]:
    """List recent memories, newest first."""
    return get_memory_service().list_memories(repo=empty_to_none(repo), limit=limit)


@memory_mcp.tool()
def memory_delete(id: str) -> str:
    """Delete a memory by its ID."""
    get_memory_service().delete(id)
    return f"Deleted: {id}"


@memory_mcp.tool()
def memory_update(id: str, content: str = "", repo: str = "", tags: list[str] | None = None) -> str:
    """Update an existing memory's content, repo, or tags."""
    get_memory_service().update(memory_id=id, content=content or None, repo=empty_to_none(repo), tags=tags)
    return f"Updated: {id}"


@plans_mcp.tool()
async def save(title: str, body: str, project: str = "") -> str:
    """Save an implementation plan or strategy to the database."""
    async with unit_of_work() as uow:
        plan = await PlanService(uow).create_plan(title=title, body=body, project=empty_to_none(project))
    return f"Plan saved (id={plan['id']})"


@plans_mcp.tool()
async def get(plan_id: int = 0, query: str = "") -> dict | list[dict] | None:
    """Retrieve a plan by ID or fuzzy search on title."""
    async with unit_of_work() as uow:
        service = PlanService(uow)
        if plan_id > 0:
            return await service.get_plan(plan_id)
        if query:
            return await service.search_plans(query)
    return []


@harness_mcp.tool()
async def harness_list(item_type: str, project: str = "", agent: str = "") -> list[dict]:
    """List harness items."""
    validate_item_type(item_type)
    async with unit_of_work() as uow:
        service = HarnessService()
        rows = await service.convenience_list(
            uow,
            item_type,
            project=empty_to_none(project),
            agent=empty_to_none(agent),
        )
        for row in rows:
            row["configs"] = await service.list_configs(uow, row["id"], item_type)
        return rows


@harness_mcp.tool()
async def harness_get(name: str, item_type: str, project: str = "") -> dict | None:
    """Get a single harness item by name and type."""
    validate_item_type(item_type)
    async with unit_of_work() as uow:
        service = HarnessService()
        item = await service.get_item_by_name(uow, item_type, name, project=empty_to_none(project))
        if item:
            item["configs"] = await service.list_configs(uow, item["id"], item_type)
        return item


@harness_mcp.tool()
async def harness_upsert(
    name: str,
    item_type: str,
    content: dict,
    project: str = "",
    agents: list[str] | None = None,
    device: str = "*",
    repo: str = "*",
) -> str:
    """Create or update a harness item. Bumps version on update."""
    validate_item_type(item_type)
    async with unit_of_work() as uow:
        service = HarnessService()
        item_id = await service.upsert_item(
            uow,
            item_type,
            name=name,
            content=content,
            project=empty_to_none(project),
            agents=agents,
        )
        if device != "*" or repo != "*":
            configs = await service.list_configs(uow, item_id, item_type)
            if configs:
                await service.update_config(uow, configs[0]["id"], device=device, repo=repo)
    return f"Upserted {item_type} '{name}' (id={item_id})"


@harness_mcp.tool()
async def harness_disable(name: str, item_type: str, project: str = "") -> str:
    """Disable a harness item by disabling all its config rows."""
    validate_item_type(item_type)
    async with unit_of_work() as uow:
        service = HarnessService()
        item = await service.get_item_by_name(uow, item_type, name, project=empty_to_none(project))
        if not item:
            return f"Not found: {item_type} '{name}'"
        configs = await service.list_configs(uow, item["id"], item_type)
        for config in configs:
            await service.update_config(uow, config["id"], enabled=False)
    return f"Disabled {item_type} '{name}' ({len(configs)} config(s) disabled)"


@harness_mcp.tool()
async def harness_sync_item(
    item_type: str,
    item_id: int = 0,
    name: str = "",
    project: str = "",
    dry_run: bool = False,
) -> str:
    """Sync a single harness item to disk by ID or name."""
    validate_item_type(item_type)
    from src.agent_smith.services.sync import AgentSmithSyncService

    return await AgentSmithSyncService().sync_item(
        item_type=item_type,
        item_id=item_id or None,
        name=name or None,
        project=empty_to_none(project),
        dry_run=dry_run,
    )


@evals_mcp.tool()
async def eval_suite_list(enabled_only: bool = True) -> list[dict]:
    """List eval suites with their scenario counts."""
    async with unit_of_work() as uow:
        items, _ = await EvalService().list_suites(uow, enabled_only=enabled_only, limit=1000, offset=0)
        for item in items:
            item["scenario_count"] = len(await EvalService().list_scenarios(uow, item["id"], enabled_only=False))
        return items


@evals_mcp.tool()
async def eval_suite_get(name: str = "", suite_id: int = 0) -> dict | None:
    """Get an eval suite by name or ID, including its scenarios."""
    async with unit_of_work() as uow:
        service = EvalService()
        if suite_id > 0:
            return await service.get_suite(uow, suite_id, include_scenarios=True)
        if name:
            items, _ = await service.list_suites(uow, enabled_only=False, limit=1000, offset=0)
            for item in items:
                if item["name"] == name:
                    return await service.get_suite(uow, item["id"], include_scenarios=True)
    return None


@evals_mcp.tool()
async def eval_suite_save(
    name: str,
    eval_type: str,
    subcategory: str,
    judge_prompt: str,
    items: dict | None = None,
    config: dict | None = None,
    enabled: bool = True,
) -> str:
    """Create or update an eval suite."""
    async with unit_of_work() as uow:
        suite_id = await EvalService().upsert_suite(
            uow,
            name=name,
            eval_type=eval_type,
            subcategory=subcategory,
            judge_prompt=judge_prompt,
            items=items or {},
            config=config or {},
            enabled=enabled,
        )
    return f"Eval suite saved (id={suite_id})"


@evals_mcp.tool()
async def eval_scenario_save(suite_name: str, name: str, prompt: str, enabled: bool = True) -> str:
    """Create or update a scenario within an eval suite."""
    async with unit_of_work() as uow:
        service = EvalService()
        suites, _ = await service.list_suites(uow, enabled_only=False, limit=1000, offset=0)
        suite = next((item for item in suites if item["name"] == suite_name), None)
        if suite is None:
            raise ValueError(f"Suite not found: {suite_name}")
        scenario_id = await service.upsert_scenario(uow, suite["id"], name=name, prompt=prompt, enabled=enabled)
    return f"Eval scenario saved (id={scenario_id})"


@graphs_mcp.tool(description=get_graph_service().build_tool_description())
async def run_graph(type: str, inputs: dict) -> str:
    return await get_graph_service().dispatch(type, inputs)


@jobs_mcp.tool()
async def job_create(
    name: str,
    schedule_config: dict,
    input_params: dict | None = None,
    description: str = "",
) -> dict:
    """Create a background job that runs a shell command on a fixed interval."""
    async with unit_of_work() as uow:
        return await JobService().create_job(
            uow,
            name=name,
            schedule_config=schedule_config,
            input_params=input_params or {},
            description=empty_to_none(description),
        )


@jobs_mcp.tool()
async def job_list(limit: int = 50, offset: int = 0) -> dict:
    """List background jobs, newest-updated first."""
    async with unit_of_work() as uow:
        items, total = await JobService().list_jobs(uow, limit=limit, offset=offset)
    return {"items": items, "total": total}


@jobs_mcp.tool()
async def job_get(job_id: int) -> dict | None:
    """Get a single job with its device/repo configs attached."""
    async with unit_of_work() as uow:
        return await JobService().get_job(uow, job_id, detail=True)


@jobs_mcp.tool()
async def job_update(
    job_id: int,
    name: str = "",
    schedule_config: dict | None = None,
    input_params: dict | None = None,
    description: str = "",
) -> dict | None:
    """Update a job's name, schedule_config, input_params, or description."""
    async with unit_of_work() as uow:
        return await JobService().update_job(
            uow,
            job_id,
            name=empty_to_none(name),
            schedule_config=schedule_config,
            input_params=input_params,
            description=empty_to_none(description),
        )


@jobs_mcp.tool()
async def job_delete(job_id: int) -> str:
    """Delete a job and all configs and execution history."""
    async with unit_of_work() as uow:
        await JobService().delete_job(uow, job_id)
    return f"Job {job_id} deleted"


@jobs_mcp.tool()
async def job_run_now(job_id: int) -> dict:
    """Run a job's command immediately, ignoring schedule and scoping."""
    async with unit_of_work() as uow:
        job = await JobService().get_job(uow, job_id, detail=True)
    if not job:
        return {"error": f"job {job_id} not found"}
    return await JobService().run_now(job)


@jobs_mcp.tool()
async def job_list_executions(job_id: int, limit: int = 50, offset: int = 0) -> dict:
    """List a job's execution history, newest first."""
    async with unit_of_work() as uow:
        items, total = await JobService().list_executions(uow, job_id, limit=limit, offset=offset)
    return {"items": items, "total": total}


@jobs_mcp.tool()
async def job_add_config(
    job_id: int,
    device: str = "*",
    repo: str = "*",
    enabled: bool = True,
    exclude: bool = False,
) -> list[dict]:
    """Add a device/repo scoping config to a job."""
    async with unit_of_work() as uow:
        return await JobService().create_config(
            uow,
            job_id,
            device=device,
            repo=repo,
            enabled=enabled,
            exclude=exclude,
        )


@jobs_mcp.tool()
async def job_update_config(
    config_id: int,
    device: str = "",
    repo: str = "",
    enabled: bool | None = None,
    exclude: bool | None = None,
) -> str:
    """Update a job config."""
    async with unit_of_work() as uow:
        await JobService().update_config(
            uow,
            config_id,
            device=empty_to_none(device),
            repo=empty_to_none(repo),
            enabled=enabled,
            exclude=exclude,
        )
    return f"Config {config_id} updated"


@jobs_mcp.tool()
async def job_delete_config(config_id: int) -> str:
    """Delete a job config."""
    async with unit_of_work() as uow:
        await JobService().delete_config(uow, config_id)
    return f"Config {config_id} deleted"


def all_mcp_servers() -> list[FastMCP]:
    return [memory_mcp, plans_mcp, harness_mcp, evals_mcp, graphs_mcp, jobs_mcp]
