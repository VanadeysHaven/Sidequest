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
