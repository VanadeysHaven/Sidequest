"""A `sidequest.scheduler.notifier.Notifier` for tests: records calls instead of using Discord."""

import asyncio
from collections.abc import Callable, Sequence

from sidequest.scheduler.notifier import Failed, Posted, PostResult
from sidequest.services.dto import DueReminder
from sidequest.services.effects import Effect


class FakeNotifier:
    """Posts succeed by default with increasing message ids (1, 2, …).

    - `calls`: ("execute", effect) / ("post", occurrence_id) in call order, to check that a
      replaced reminder is deleted before the new one is posted.
    - `posted`: every reminder passed to `post`.
    - `respond`: optional hook returning a custom result (e.g. `Failed("forbidden")`) or
      raising, per reminder; return None for the default success.
    - `wait_for_posts(n)`: await until at least n posts happened (for loop tests).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.posted: list[DueReminder] = []
        self.executed: list[Effect] = []
        self.respond: Callable[[DueReminder], PostResult | None] | None = None
        self._next_message_id = 1
        self._post_count_changed = asyncio.Condition()

    async def post(self, reminder: DueReminder) -> PostResult:
        self.calls.append(("post", reminder.occurrence.id))
        self.posted.append(reminder)
        async with self._post_count_changed:
            self._post_count_changed.notify_all()
        if self.respond is not None:
            result = self.respond(reminder)
            if result is not None:
                return result
        if reminder.channel_id is None:
            return Failed(reason="no_channel")
        message_id = self._next_message_id
        self._next_message_id += 1
        return Posted(channel_id=reminder.channel_id, message_id=message_id)

    async def execute(self, effects: Sequence[Effect]) -> None:
        for effect in effects:
            self.calls.append(("execute", effect))
            self.executed.append(effect)

    async def wait_for_posts(self, count: int, seconds: float = 5.0) -> None:
        async with asyncio.timeout(seconds), self._post_count_changed:
            await self._post_count_changed.wait_for(lambda: len(self.posted) >= count)
