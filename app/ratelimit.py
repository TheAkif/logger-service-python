import time
from collections import deque
from typing import Optional

_windows: dict[str, deque[float]] = {}


def check_rate_limit(tenant_id: str, limit_per_min: Optional[int]) -> bool:
    if limit_per_min is None:
        return True

    now = time.monotonic()
    window = _windows.setdefault(tenant_id, deque())

    while window and now - window[0] > 60.0:
        window.popleft()

    if len(window) >= limit_per_min:
        return False

    window.append(now)
    return True


def current_count(tenant_id: str) -> int:
    now = time.monotonic()
    window = _windows.get(tenant_id, deque())
    while window and now - window[0] > 60.0:
        window.popleft()
    return len(window)
