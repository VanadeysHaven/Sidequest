"""Discord timestamps (`<t:unix:style>`): the only way points in time reach users.

Minimal for S1; S3 completes this module.
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
