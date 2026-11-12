"""Server lists (S8, D41–D53): create, rename, delete, collaborators, transfer, lookup.

Every server has one ownerless fallback list ("Default List", D42). It is created by
`ensure_guild` the first time anything reads the server's lists: the bot runs without the
guilds intent (D11), so it never hears about joining a server.
"""

from collections.abc import Sequence

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from sidequest.core.enums import TodoStatus
from sidequest.core.errors import Forbidden, InvalidOperation, LimitExceeded, NameTaken, NotFound
from sidequest.core.limits import COLLABORATORS_MAX, LIST_NAME_MAX, LISTS_MAX
from sidequest.core.text import bold
from sidequest.db.models import (
    GuildSettings,
    ListCollaborator,
    Todo,
    TodoList,
    UserGuildSettings,
)
from sidequest.services import _common as c
from sidequest.services import permissions
from sidequest.services.actor import Actor
from sidequest.services.dto import ListDeletePreview, ListDeleteResult, ListView
from sidequest.services.effects import Effect, Outcome
from sidequest.services.uow import Uow

DEFAULT_LIST_NAME = "Default List"
NAME_INDEX = "uq_todo_lists_guild_id_name"
LIST_NOT_FOUND = "That list doesn't exist in this server."
MAX_CLASHES_SHOWN = 10


# --- validation --------------------------------------------------------------------------


def clean_list_name(name: str) -> str:
    """D43: trimmed, 1–50 characters."""
    name = name.strip()
    if not name:
        raise InvalidOperation("A list name can't be empty.")
    if len(name) > LIST_NAME_MAX:
        raise LimitExceeded(f"A list name is too long ({len(name)}/{LIST_NAME_MAX} characters).")
    return name


def _name_taken(name: str) -> NameTaken:
    return NameTaken(f"There's already a list called {bold(name)}.")


async def _require_unique_name(
    uow: Uow, guild_id: int, name: str, exclude_id: int | None = None
) -> None:
    stmt = select(TodoList.id).where(
        TodoList.guild_id == guild_id, func.lower(TodoList.name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(TodoList.id != exclude_id)
    if await uow.session.scalar(stmt.limit(1)) is not None:
        raise _name_taken(name)


async def _flush_name(uow: Uow, name: str) -> None:
    """Flush; a concurrent duplicate name (unique index) becomes `NameTaken`."""
    try:
        await uow.session.flush()
    except IntegrityError as exc:
        await uow.session.rollback()
        if NAME_INDEX in str(exc.orig):
            raise _name_taken(name) from None
        raise


# --- lookup ------------------------------------------------------------------------------


async def ensure_guild(uow: Uow, guild_id: int) -> int:
    """The server's fallback list id. Creates the settings row and its "Default List" if
    missing (D42). Race-safe; doesn't commit (the caller does)."""
    fallback = await uow.session.scalar(
        select(GuildSettings.default_list_id).where(GuildSettings.guild_id == guild_id)
    )
    if fallback is not None:
        return fallback
    await uow.session.execute(
        insert(GuildSettings).values(guild_id=guild_id).on_conflict_do_nothing()
    )
    settings = await uow.session.scalar(
        select(GuildSettings)
        .where(GuildSettings.guild_id == guild_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert settings is not None
    if settings.default_list_id is None:
        lst = TodoList(guild_id=guild_id, name=DEFAULT_LIST_NAME, owner_id=None, collaborators=[])
        uow.session.add(lst)
        await uow.session.flush()
        settings.default_list_id = lst.id
        await uow.session.flush()
    return settings.default_list_id


async def own_default_list_id(uow: Uow, actor: Actor) -> int | None:
    """The actor's own default-list setting here (D45), without the fallback. None if
    unset or if that list was deleted (the row cascades)."""
    guild_id = c.require_guild(actor)
    return await uow.session.scalar(
        select(UserGuildSettings.default_list_id).where(
            UserGuildSettings.user_id == actor.user_id, UserGuildSettings.guild_id == guild_id
        )
    )


async def load_list(uow: Uow, guild_id: int, list_id: int, *, lock: bool = False) -> TodoList:
    """A list of `guild_id` with its collaborators; `NotFound` for another server's list."""
    stmt = (
        select(TodoList)
        .where(TodoList.id == list_id, TodoList.guild_id == guild_id)
        .options(selectinload(TodoList.collaborators))
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update(of=TodoList)
    lst = await uow.session.scalar(stmt)
    if lst is None:
        raise NotFound(LIST_NOT_FOUND)
    return lst


async def resolve(uow: Uow, actor: Actor, list_id: int | None, *, lock: bool = False) -> TodoList:
    """The given list, else the actor's default, else the server's fallback (D45)."""
    guild_id = c.require_guild(actor)
    fallback = await ensure_guild(uow, guild_id)
    if list_id is None:
        list_id = await own_default_list_id(uow, actor) or fallback
    return await load_list(uow, guild_id, list_id, lock=lock)


# --- views -------------------------------------------------------------------------------


async def _open_counts(uow: Uow, list_ids: Sequence[int]) -> dict[int, int]:
    if not list_ids:
        return {}
    rows = await uow.session.execute(
        select(Todo.list_id, func.count())
        .where(Todo.list_id.in_(list(list_ids)), Todo.status == TodoStatus.OPEN)
        .group_by(Todo.list_id)
    )
    return {list_id: count for list_id, count in rows}


def _view(
    actor: Actor, lst: TodoList, *, fallback_id: int, my_default_id: int, open_count: int
) -> ListView:
    return ListView(
        id=lst.id,
        guild_id=lst.guild_id,
        name=lst.name,
        owner_id=lst.owner_id,
        collaborator_ids=tuple(sorted(lst.collaborator_ids)),
        is_fallback=lst.id == fallback_id,
        is_my_default=lst.id == my_default_id,
        open_count=open_count,
        can_manage=permissions.can_manage_list(actor, lst),
        can_rename=permissions.can_rename_list(actor, lst),
        can_add=permissions.can_add(actor, lst),
    )


async def _views(uow: Uow, actor: Actor, lists: Sequence[TodoList]) -> list[ListView]:
    guild_id = c.require_guild(actor)
    fallback = await ensure_guild(uow, guild_id)
    my_default = await own_default_list_id(uow, actor) or fallback
    counts = await _open_counts(uow, [lst.id for lst in lists])
    return [
        _view(
            actor,
            lst,
            fallback_id=fallback,
            my_default_id=my_default,
            open_count=counts.get(lst.id, 0),
        )
        for lst in lists
    ]


async def view_of(uow: Uow, actor: Actor, lst: TodoList) -> ListView:
    await uow.session.flush()
    return (await _views(uow, actor, [lst]))[0]


async def get(uow: Uow, actor: Actor, list_id: int | None) -> ListView:
    """One list; None = the actor's effective default (D45)."""
    lst = await resolve(uow, actor, list_id)
    view = await view_of(uow, actor, lst)
    await uow.session.commit()
    return view


async def list_lists(uow: Uow, actor: Actor) -> list[ListView]:
    """All lists of the actor's server: the fallback first, then by name."""
    views = await _all_views(uow, actor)
    await uow.session.commit()
    return views


async def autocomplete(
    uow: Uow, actor: Actor, query: str, limit: int = 25
) -> list[tuple[int, str]]:
    """(id, name) of the server's lists whose name contains `query`; prefix matches first."""
    if actor.guild_id is None:
        return []
    guild_id = actor.guild_id
    await ensure_guild(uow, guild_id)
    q = query.strip()
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    stmt = select(TodoList.id, TodoList.name).where(TodoList.guild_id == guild_id)
    if q:
        stmt = stmt.where(TodoList.name.ilike(f"%{escaped}%", escape="\\"))
    stmt = stmt.order_by(
        case((TodoList.name.ilike(f"{escaped}%", escape="\\"), 0), else_=1),
        func.lower(TodoList.name),
        TodoList.id,
    ).limit(limit)
    rows = [(list_id, name) for list_id, name in await uow.session.execute(stmt)]
    await uow.session.commit()
    return rows


# --- change ------------------------------------------------------------------------------


def _require_manage(actor: Actor, lst: TodoList, fallback_message: str) -> None:
    if lst.owner_id is None:
        raise InvalidOperation(fallback_message.format(name=bold(lst.name)))
    if not permissions.can_manage_list(actor, lst):
        raise Forbidden(
            f"Only the owner of {bold(lst.name)} or someone with Manage Server can do that."
        )


async def create(uow: Uow, actor: Actor, name: str) -> ListView:
    """Anyone in the server; the caller becomes the owner (D46)."""
    guild_id = c.require_guild(actor)
    await ensure_guild(uow, guild_id)
    name = clean_list_name(name)
    # Serialize list creation per server (count limit + name check).
    await uow.session.execute(
        select(GuildSettings.guild_id).where(GuildSettings.guild_id == guild_id).with_for_update()
    )
    count = await uow.session.scalar(
        select(func.count()).select_from(TodoList).where(TodoList.guild_id == guild_id)
    )
    if (count or 0) >= LISTS_MAX:
        raise LimitExceeded(f"A server can have at most {LISTS_MAX} lists.")
    await _require_unique_name(uow, guild_id, name)
    lst = TodoList(guild_id=guild_id, name=name, owner_id=actor.user_id, collaborators=[])
    uow.session.add(lst)
    await _flush_name(uow, name)
    view = await view_of(uow, actor, lst)
    await uow.session.commit()
    return view


async def rename(uow: Uow, actor: Actor, list_id: int, name: str) -> ListView:
    """Owner or Manage Server; only Manage Server for the fallback list (D46, D51)."""
    lst = await resolve(uow, actor, list_id, lock=True)
    if not permissions.can_rename_list(actor, lst):
        if lst.owner_id is None:
            raise Forbidden(f"Only someone with Manage Server can rename {bold(lst.name)}.")
        raise Forbidden(
            f"Only the owner of {bold(lst.name)} or someone with Manage Server can rename it."
        )
    name = clean_list_name(name)
    await _require_unique_name(uow, lst.guild_id, name, exclude_id=lst.id)
    lst.name = name
    await _flush_name(uow, name)
    view = await view_of(uow, actor, lst)
    await uow.session.commit()
    return view


FALLBACK_NO_DELETE = (
    "{name} is this server's fallback list, so it can't be deleted. You can rename it."
)
FALLBACK_NO_COLLABORATORS = "{name} is open to everyone, so it has no collaborators."
FALLBACK_NO_TRANSFER = "{name} is open to everyone, so it has no owner to change."


async def _open_todos(uow: Uow, list_id: int) -> list[Todo]:
    return list(
        await uow.session.scalars(
            select(Todo)
            .where(Todo.list_id == list_id, Todo.status == TodoStatus.OPEN)
            .order_by(Todo.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


async def _move_targets(uow: Uow, actor: Actor, lst: TodoList) -> list[ListView]:
    return [v for v in await _all_views(uow, actor) if v.id != lst.id and v.can_add]


async def _all_views(uow: Uow, actor: Actor) -> list[ListView]:
    guild_id = c.require_guild(actor)
    fallback = await ensure_guild(uow, guild_id)
    lists = list(
        await uow.session.scalars(
            select(TodoList)
            .where(TodoList.guild_id == guild_id)
            .options(selectinload(TodoList.collaborators))
            .order_by(
                case((TodoList.id == fallback, 0), else_=1),
                func.lower(TodoList.name),
                TodoList.id,
            )
        )
    )
    return await _views(uow, actor, lists)


async def delete_preview(uow: Uow, actor: Actor, list_id: int) -> ListDeletePreview:
    """What deleting asks about (D47): open to-dos and where they could go."""
    lst = await resolve(uow, actor, list_id)
    _require_manage(actor, lst, FALLBACK_NO_DELETE)
    view = await view_of(uow, actor, lst)
    targets = await _move_targets(uow, actor, lst) if view.open_count else []
    await uow.session.commit()
    return ListDeletePreview(list=view, open_count=view.open_count, targets=targets)


async def delete(
    uow: Uow, actor: Actor, list_id: int, *, move_to: int | None
) -> Outcome[ListDeleteResult]:
    """Delete a list (D47). Its open to-dos are deleted (cancelled, reminders removed) or,
    with `move_to`, moved there; a title clash there refuses the whole move. Finished
    history goes with the list (FK cascade); users' defaults for it fall back (D45)."""
    lst = await resolve(uow, actor, list_id, lock=True)
    _require_manage(actor, lst, FALLBACK_NO_DELETE)
    todos = await _open_todos(uow, lst.id)
    effects: list[Effect] = []
    changed = False
    moved_to: TodoList | None = None

    if move_to is not None:
        target = await load_list(uow, lst.guild_id, move_to)
        if target.id == lst.id:
            raise InvalidOperation("Pick another list to move the to-dos to.")
        c.require_add(actor, target)
        await _require_no_clashes(uow, target, todos)
        for todo in todos:
            todo.list_id = target.id
        moved_to = target
    else:
        for todo in todos:
            todo_effects, had_pending = await c.cancel_open(uow, todo, include_sent=True)
            todo.status = TodoStatus.CANCELLED
            effects += todo_effects
            changed = changed or had_pending

    await uow.session.flush()
    name = lst.name
    await uow.session.delete(lst)
    await uow.session.flush()
    await uow.session.commit()
    return Outcome(
        value=ListDeleteResult(
            name=name,
            deleted=0 if moved_to else len(todos),
            moved=len(todos) if moved_to else 0,
            moved_to=moved_to.name if moved_to else None,
        ),
        effects=effects,
        changed_schedule=changed,
    )


async def _require_no_clashes(uow: Uow, target: TodoList, todos: Sequence[Todo]) -> None:
    if not todos:
        return
    existing = set(
        await uow.session.scalars(
            select(func.lower(Todo.title)).where(
                Todo.list_id == target.id, Todo.status == TodoStatus.OPEN
            )
        )
    )
    clashes = [t.title for t in todos if t.title.lower() in existing]
    if not clashes:
        return
    shown = ", ".join(bold(t) for t in clashes[:MAX_CLASHES_SHOWN])
    more = len(clashes) - MAX_CLASHES_SHOWN
    if more > 0:
        shown += f" and {more} more"
    raise NameTaken(
        f"These titles already exist on {bold(target.name)}: {shown}. Rename or finish them first."
    )


async def set_collaborators(
    uow: Uow, actor: Actor, list_id: int, user_ids: Sequence[int]
) -> ListView:
    """Replace the collaborators (D50). Owner or Manage Server. The owner's own id is
    dropped (the owner is implicit); bots are filtered by the adapter."""
    lst = await resolve(uow, actor, list_id, lock=True)
    _require_manage(actor, lst, FALLBACK_NO_COLLABORATORS)
    wanted = [u for u in dict.fromkeys(user_ids) if u != lst.owner_id]
    if len(wanted) > COLLABORATORS_MAX:
        raise LimitExceeded(f"A list can have at most {COLLABORATORS_MAX} collaborators.")
    _replace_collaborators(lst, wanted)
    view = await view_of(uow, actor, lst)
    await uow.session.commit()
    return view


def _replace_collaborators(lst: TodoList, wanted: Sequence[int]) -> None:
    for collaborator in list(lst.collaborators):
        if collaborator.user_id not in wanted:
            lst.collaborators.remove(collaborator)
    current = {col.user_id for col in lst.collaborators}
    lst.collaborators.extend(ListCollaborator(user_id=u) for u in wanted if u not in current)


async def transfer(uow: Uow, actor: Actor, list_id: int, new_owner_id: int) -> ListView:
    """D52: owner or Manage Server. The new owner stops being a collaborator; the old
    owner becomes one. Bots are refused by the adapter."""
    lst = await resolve(uow, actor, list_id, lock=True)
    _require_manage(actor, lst, FALLBACK_NO_TRANSFER)
    old_owner = lst.owner_id
    if new_owner_id == old_owner:
        raise InvalidOperation("That user already owns this list.")
    wanted = [u for u in sorted(lst.collaborator_ids) if u != new_owner_id]
    if old_owner is not None and old_owner not in wanted:
        wanted.append(old_owner)
    if len(wanted) > COLLABORATORS_MAX:
        raise LimitExceeded(
            f"{bold(lst.name)} already has {COLLABORATORS_MAX} collaborators, so the current "
            "owner can't stay on as one. Remove a collaborator first."
        )
    _replace_collaborators(lst, wanted)
    lst.owner_id = new_owner_id
    view = await view_of(uow, actor, lst)
    await uow.session.commit()
    return view
