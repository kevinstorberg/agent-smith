from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scripts.shared.paths import ensure_importable  # noqa: E402
ensure_importable(__file__)
