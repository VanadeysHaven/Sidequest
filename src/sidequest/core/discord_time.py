"""Discord timestamps (`<t:unix:style>`): the only way points in time reach users (C5).

Discord renders them in each viewer's own timezone and 12h/24h preference (D1).
"""

import math
from datetime import datetime
from typing import Literal

# t: 16:20 · T: 16:20:30 · d: 20/04/2021 · D: 20 April 2021 · f: date + time
# F: weekday + date + time · R: relative ("in 2 hours")
Style = Literal["t", "T", "d", "D", "f", "F", "R"]


def ts(dt: datetime, style: Style = "f") -> str:
    if dt.tzinfo is None:
        raise ValueError("naive datetime; use timezone-aware UTC")
    return f"<t:{math.floor(dt.timestamp())}:{style}>"


def ts_due(dt: datetime) -> str:
    """The standard way to show a due time: full date + time, then relative."""
    return f"{ts(dt, 'F')} ({ts(dt, 'R')})"
