"""Scheduler heartbeat: the reminder loop writes it, `sidequest healthcheck` reads it.

The file holds one ISO-8601 UTC timestamp, rewritten after every successful scheduler
iteration (at least once a minute). A missing or old file means the loop is stuck, crashed,
or can't reach the database. Docker's HEALTHCHECK runs `sidequest healthcheck` (shown in
`docker compose ps`), and `Watchdog` exits the process so Docker restarts it.

Kept free of discord/sqlalchemy imports so the healthcheck starts quickly on the Pi.
"""

import logging
import os
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "sidequest-heartbeat"
MAX_AGE = timedelta(minutes=3)
START_GRACE = timedelta(minutes=5)


def write_heartbeat(path: Path, now: datetime) -> None:
    """Atomic (temp file + rename), so a reader never sees a half-written file.

    Raises OSError if the file can't be written.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(now.isoformat(), encoding="utf-8")
    os.replace(tmp, path)


def check_heartbeat(path: Path, now: datetime, max_age: timedelta = MAX_AGE) -> str | None:
    """None if the heartbeat is fresh, else a one-line reason why it isn't."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return f"no heartbeat yet ({path})"
    except OSError as exc:
        return f"cannot read heartbeat {path}: {exc}"
    try:
        beat = datetime.fromisoformat(text)
    except ValueError:
        return f"heartbeat {path} is not a timestamp: {text[:40]!r}"
    if beat.tzinfo is None:
        return f"heartbeat {path} has no timezone: {text[:40]!r}"
    age = int((now - beat).total_seconds())
    limit = int(max_age.total_seconds())
    if age > limit:
        return f"heartbeat is {age} s old (limit {limit} s)"
    return None


class Watchdog:
    """Ends the process when the heartbeat stops changing, so Docker restarts the bot (D38).

    Docker only *marks* a container unhealthy; `restart: unless-stopped` restarts it only
    when its process exits. This runs in a thread, so it still fires when the event loop
    itself is blocked.

    It doesn't compare the timestamp in the file with the wall clock: a Pi has no hardware
    clock and jumps forward when NTP syncs after boot, which would look like a stale beat.
    Instead it notes, on a monotonic clock, when the file's content last changed. Until the
    first heartbeat appears it allows `start_grace` (login, command sync, first iteration);
    after that the content must change at least every `max_age`.
    """

    def __init__(
        self,
        path: Path,
        *,
        on_stale: Callable[[str], None] | None = None,
        interval: float = 30.0,
        max_age: timedelta = MAX_AGE,
        start_grace: timedelta = START_GRACE,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._path = path
        self._on_stale = on_stale or _exit_process
        self._interval = interval
        self._max_age = max_age.total_seconds()
        self._start_grace = start_grace.total_seconds()
        self._monotonic = monotonic
        self._last_content: str | None = None
        self._changed_at = monotonic()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def problem(self) -> str | None:
        """Why the bot should be restarted now, or None."""
        now = self._monotonic()
        content = self._read()
        if content is not None and content != self._last_content:
            self._last_content = content
            self._changed_at = now
        quiet = now - self._changed_at
        if self._last_content is None:
            if quiet > self._start_grace:
                return f"no heartbeat within {int(self._start_grace)} s of starting"
            return None
        if quiet > self._max_age:
            return f"heartbeat unchanged for {int(quiet)} s (limit {int(self._max_age)} s)"
        return None

    def start(self) -> None:
        self._changed_at = self._monotonic()
        self._thread = threading.Thread(target=self._run, name="sidequest-watchdog", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Call before a deliberate shutdown, which stops the heartbeat too."""
        self._stop.set()

    def _read(self) -> str | None:
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            problem = self.problem()
            if problem is not None and not self._stop.is_set():
                self._on_stale(problem)
                return


def _exit_process(problem: str) -> None:
    # No cleanup: the event loop may be the thing that's stuck. Docker's restart policy
    # (restart: unless-stopped) starts a fresh container process. The timer exits even if
    # logging blocks (e.g. the main thread holds the handler lock in a stalled stdout write).
    threading.Timer(5.0, os._exit, args=(1,)).start()
    log.critical("Reminder loop is stuck (%s); exiting so Docker restarts the bot", problem)
    os._exit(1)
