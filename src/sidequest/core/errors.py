"""Domain errors. `message` is safe to show to the user (the bot still escapes it)."""


class SidequestError(Exception):
    """Base class for every error the user is meant to see."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidTime(SidequestError):
    """A time of day could not be parsed, or a date was given without a time."""


class InvalidDate(SidequestError):
    """A date could not be parsed or does not exist."""


class InvalidTimezone(SidequestError):
    """Not a known IANA timezone name."""


class InPast(SidequestError):
    """A one-time to-do was scheduled for a moment that has already passed."""


class InvalidRule(SidequestError):
    """A repeat rule (or one of its parts) is invalid."""


class NotFound(SidequestError):
    """The thing does not exist, or the user may not see it (so IDs don't leak)."""


class Forbidden(SidequestError):
    """The user may see the thing but not change it."""


class ReminderChannelNotSet(SidequestError):
    """A timed server to-do needs a reminder channel, and the server has none yet."""


class LimitExceeded(SidequestError):
    """A size limit (BRIEF §4.11) was exceeded."""


class InvalidOperation(SidequestError):
    """The request makes no sense for this to-do (e.g. a date for a repeating to-do)."""
