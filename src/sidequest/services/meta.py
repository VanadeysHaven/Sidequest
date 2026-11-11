"""Small key/value store for the app itself (`app_meta`), e.g. the synced command hash."""

from sqlalchemy.dialects.postgresql import insert

from sidequest.db.models import AppMeta
from sidequest.services.uow import Uow

COMMAND_HASH = "command_hash"


async def get(uow: Uow, key: str) -> str | None:
    row = await uow.session.get(AppMeta, key)
    return None if row is None else row.value


async def put(uow: Uow, key: str, value: str) -> None:
    stmt = insert(AppMeta).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=[AppMeta.key], set_={"value": value})
    await uow.session.execute(stmt)
    await uow.session.commit()
