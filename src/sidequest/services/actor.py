"""Who is asking: the identity every service call is checked against."""

from typing import Literal

from sidequest.services.model import StrictModel

type Origin = Literal["discord", "web", "system"]


class Actor(StrictModel):
    user_id: int
    guild_id: int | None
    """The guild the request came from (None in DMs and on the web)."""
    can_manage_guild: bool
    """The user has Manage Server in `guild_id`."""
    origin: Origin

    @classmethod
    def system(cls) -> "Actor":
        """The scheduler. Passes every permission check."""
        return cls(user_id=0, guild_id=None, can_manage_guild=False, origin="system")

    @property
    def is_system(self) -> bool:
        return self.origin == "system"
