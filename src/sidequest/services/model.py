"""Base for the services' data models (D34)."""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Immutable, no type coercion: a wrong type is a bug and fails loudly.

    Keyword arguments only (pydantic models take no positional arguments).
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
