"""Plain-text helpers for user-facing messages built outside the bot layer."""

import re
from datetime import date

_MARKDOWN = re.compile(r"([\\*_~`|>#\[\]()-])")


def bold(text: str) -> str:
    """`**text**` with Discord markdown in `text` escaped, for names users typed (list
    names, to-do titles) inside service error messages. Mentions are escaped by the bot."""
    escaped = _MARKDOWN.sub(lambda m: "\\" + m.group(1), text)
    return f"**{escaped}**"


def plain_date(d: date) -> str:
    """A calendar date that isn't a point in time (start, end): `DD-MM-YYYY`."""
    return d.strftime("%d-%m-%Y")
