"""Plain-text helpers for user-facing messages built outside the bot layer."""

import re

_MARKDOWN = re.compile(r"([\\*_~`|>#\[\]()-])")


def bold(text: str) -> str:
    """`**text**` with Discord markdown in `text` escaped, for names users typed (list
    names, to-do titles) inside service error messages. Mentions are escaped by the bot."""
    escaped = _MARKDOWN.sub(lambda m: "\\" + m.group(1), text)
    return f"**{escaped}**"
