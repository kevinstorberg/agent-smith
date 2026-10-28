from __future__ import annotations

from services.meetings.config import SourceConfig
from services.meetings.types import MeetingProvider


def build_meeting_provider(config: SourceConfig) -> MeetingProvider:
    try:
        builder = _PROVIDER_BUILDERS[config.provider]
    except KeyError:
        raise ValueError(f"Unsupported meeting provider '{config.provider}'; expected {', '.join(_PROVIDER_BUILDERS)}") from None
    return builder(config)


def _build_granola(config: SourceConfig) -> MeetingProvider:
    from services.meetings.providers.granola import GranolaProvider

    return GranolaProvider(config)


_PROVIDER_BUILDERS = {"granola": _build_granola}
