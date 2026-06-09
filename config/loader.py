from functools import lru_cache

import yaml

from config.models import DefaultConfig, GraphConfig
from lib.cairn.paths import get_module_dir

_CONFIG_DIR = get_module_dir(__file__)


class GraphConfigNotFound(ValueError):
    pass


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


@lru_cache(maxsize=1)
def load_default_config() -> DefaultConfig:
    path = _CONFIG_DIR / "default.yaml"
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return DefaultConfig(**data)


@lru_cache(maxsize=16)
def load_graph_config(graph_name: str, *, require_file: bool = False) -> GraphConfig:
    default = load_default_config()
    path = _CONFIG_DIR / "graphs" / f"{graph_name}.yaml"

    if not path.exists():
        if require_file:
            raise GraphConfigNotFound(f"Graph config not found: {path}")
        merged = default.model_dump()
        merged["name"] = graph_name
        return GraphConfig(**merged)

    with open(path) as f:
        graph_data = yaml.safe_load(f) or {}

    merged = default.model_dump()
    _deep_merge(merged, graph_data)
    merged["name"] = graph_name
    return GraphConfig(**merged)
