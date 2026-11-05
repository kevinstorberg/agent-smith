from datetime import datetime, timedelta

from services.costs.contracts import require_utc


def month_window(now: datetime) -> tuple[str, str]:
    today = require_utc(now).date()
    return today.replace(day=1).isoformat(), (today + timedelta(days=1)).isoformat()
