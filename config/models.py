from pydantic import BaseModel, Field, model_validator


class LLMConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 4096


class DatabaseConfig(BaseModel):
    backend: str = "postgresql"
    pool_size: int = 5


class MemoryConfig(BaseModel):
    backend: str = "in_memory"
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    pgvector_table: str = "cairn_memory"


class CacheConfig(BaseModel):
    backend: str = "memory"
    default_ttl: int = 300


class StorageConfig(BaseModel):
    backend: str = "local"
    local_path: str = "./storage"


class JobsConfig(BaseModel):
    enabled: bool = True
    auto_discover: bool = True
    scheduler_store: str = "memory"
    status_store: str = "memory"
    lock_backend: str = "memory"
    require_distributed_lock: bool = False


class AdminDebugConfig(BaseModel):
    enabled: bool = False
    expose_config_values: bool = False
    require_admin: bool = True


class FrontendConfig(BaseModel):
    enabled: bool = False
    static_dir: str = "frontend/dist"
    mount_path: str = "/ui"
    spa_fallback: bool = True


class SecurityHeadersConfig(BaseModel):
    enabled: bool = True
    content_type_options: str = "nosniff"
    frame_options: str = "DENY"
    referrer_policy: str = "no-referrer"
    permissions_policy: str = "geolocation=(), microphone=(), camera=()"
    content_security_policy: str = ""
    hsts_max_age_seconds: int = Field(default=31536000, gt=0)


class SecurityConfig(BaseModel):
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    trusted_hosts: list[str] = Field(default_factory=lambda: ["*"])
    rate_limit_enabled: bool = True
    rate_limit_requests: int = Field(default=120, gt=0)
    rate_limit_window_seconds: int = Field(default=60, gt=0)
    max_request_body_bytes: int = Field(default=10485760, gt=0)
    headers: SecurityHeadersConfig = Field(default_factory=SecurityHeadersConfig)


class GraphRuntimeConfig(BaseModel):
    kind: str = "react"
    prompt: str | None = None
    recursion_limit: int = 25


class CheckpointConfig(BaseModel):
    backend: str = "none"


class DefaultConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    admin_debug: AdminDebugConfig = Field(default_factory=AdminDebugConfig)
    frontend: FrontendConfig = Field(default_factory=FrontendConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)


class GraphConfig(DefaultConfig):
    name: str = "default"
    tools: list[str] = Field(default_factory=list)
    validation: dict = Field(default_factory=dict)
    checkpointing: bool = False
    runtime: GraphRuntimeConfig = Field(default_factory=GraphRuntimeConfig)
    checkpoint: CheckpointConfig = Field(default_factory=CheckpointConfig)

    @model_validator(mode="after")
    def apply_legacy_checkpointing_flag(self) -> "GraphConfig":
        if self.checkpointing and self.checkpoint.backend == "none":
            self.checkpoint.backend = "memory"
        return self
