from __future__ import annotations


def resolve_sync_targets(item: dict, agent: str, device_name: str) -> list[str]:
    configs = item.get("configs", [])
    relevant = [
        c for c in configs
        if c["enabled"]
        and agent in c["agents"]
        and _device_matches(c["device"], device_name)
    ]

    additive = [c for c in relevant if not c["exclude"]]
    subtractive = [c for c in relevant if c["exclude"]]

    if not additive:
        return []

    targets = {c["repo"] for c in additive}

    for c in subtractive:
        targets.discard(c["repo"])

    return sorted(targets)


def _device_matches(config_device: str, device_name: str) -> bool:
    if config_device == "*":
        return True
    if not device_name:
        return False
    return config_device == device_name
