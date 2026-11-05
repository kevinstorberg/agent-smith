from __future__ import annotations

from fastapi import APIRouter

from services.api.routers.rules import RulesRouter
from services.api.routers.skills import SkillsRouter
from services.api.routers.tools import ToolsRouter
from services.api.routers.hooks import HooksRouter
from services.api.routers.agents import AgentsRouter
from services.api.routers.sync import router as sync_router
from services.api.routers.harness_editor import router as editor_router

harness_router = APIRouter()

for _ctrl_cls in [RulesRouter, SkillsRouter, ToolsRouter, HooksRouter, AgentsRouter]:
    harness_router.include_router(_ctrl_cls().router)

harness_router.include_router(sync_router)
harness_router.include_router(editor_router)
