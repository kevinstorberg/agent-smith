from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base


class IntTimestampMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HarnessItemMixin(IntTimestampMixin):
    name: Mapped[str] = mapped_column(Text, nullable=False)
    project: Mapped[str | None] = mapped_column(Text)
    agents: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    subagents: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    sort_key: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class HarnessRule(HarnessItemMixin, Base):
    __tablename__ = "harness_rules"

    clone_as_skill: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class HarnessSkill(HarnessItemMixin, Base):
    __tablename__ = "harness_skills"


class HarnessTool(HarnessItemMixin, Base):
    __tablename__ = "harness_tools"


class HarnessHook(HarnessItemMixin, Base):
    __tablename__ = "harness_hooks"


class HarnessAgent(HarnessItemMixin, Base):
    __tablename__ = "harness_agents"


class HarnessConfig(IntTimestampMixin, Base):
    __tablename__ = "harness_configs"

    item_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    device: Mapped[str] = mapped_column(Text, nullable=False, server_default="*")
    repo: Mapped[str] = mapped_column(Text, nullable=False, server_default="*")
    agents: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{claude,codex,gemini}")
    subagents: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    exclude: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Plan(IntTimestampMixin, Base):
    __tablename__ = "plans"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    project: Mapped[str | None] = mapped_column(Text)


class EvalSuite(IntTimestampMixin, Base):
    __tablename__ = "eval_suites"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    eval_type: Mapped[str] = mapped_column(Text, nullable=False)
    subcategory: Mapped[str] = mapped_column(Text, nullable=False)
    judge_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    scenarios: Mapped[list["EvalScenario"]] = relationship(back_populates="suite", cascade="all, delete-orphan")


class EvalScenario(IntTimestampMixin, Base):
    __tablename__ = "eval_scenarios"

    suite_id: Mapped[int] = mapped_column(ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_key: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    suite: Mapped[EvalSuite] = relationship(back_populates="scenarios")


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    eval_type: Mapped[str] = mapped_column(Text, nullable=False)
    subcategory: Mapped[str | None] = mapped_column(Text)
    scenario: Mapped[str] = mapped_column(Text, nullable=False)
    test_model: Mapped[str] = mapped_column(Text, nullable=False)
    judge_model: Mapped[str] = mapped_column(Text, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text)
    eval_suite_id: Mapped[int | None] = mapped_column(ForeignKey("eval_suites.id", ondelete="SET NULL"))
    eval_scenario_id: Mapped[int | None] = mapped_column(ForeignKey("eval_scenarios.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BackgroundJob(IntTimestampMixin, Base):
    __tablename__ = "background_jobs"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    schedule_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    configs: Mapped[list["JobConfig"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    executions: Mapped[list["JobExecution"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobConfig(IntTimestampMixin, Base):
    __tablename__ = "job_configs"

    job_id: Mapped[int] = mapped_column(ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False)
    device: Mapped[str] = mapped_column(Text, nullable=False, server_default="*")
    repo: Mapped[str] = mapped_column(Text, nullable=False, server_default="*")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    exclude: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    job: Mapped[BackgroundJob] = relationship(back_populates="configs")


class JobExecution(Base):
    __tablename__ = "job_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    device: Mapped[str] = mapped_column(Text, nullable=False, server_default="*")
    job: Mapped[BackgroundJob] = relationship(back_populates="executions")
