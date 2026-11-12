"""`/lists collaborators`: choosing who may work on a list (D50), like `views/assign.py`."""

import discord

from sidequest.bot import adapter, render
from sidequest.bot.views.base import BaseView
from sidequest.core.limits import COLLABORATORS_MAX
from sidequest.services import lists
from sidequest.services.dto import ListView


class CollaboratorsView(BaseView):
    def __init__(self, owner_id: int, lst: ListView) -> None:
        super().__init__(owner_id)
        self.list_id = lst.id
        self.list_owner_id = lst.owner_id
        self.select = discord.ui.UserSelect(
            placeholder="Collaborators",
            min_values=0,
            max_values=COLLABORATORS_MAX,
            default_values=[discord.Object(id=u) for u in lst.collaborator_ids],
        )
        self.select.callback = self._chosen
        self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction) -> None:
        picked = list(self.select.values)
        ids = [u.id for u in picked if not u.bot and u.id != self.list_owner_id]
        dropped: list[str] = []
        if any(u.bot for u in picked):
            dropped.append("bots can't be collaborators")
        if any(u.id == self.list_owner_id for u in picked):
            dropped.append("the owner is always in")
        await interaction.response.defer()
        async with adapter.uows(interaction)() as uow:
            lst = await lists.set_collaborators(
                uow, adapter.actor_from(interaction), self.list_id, ids
            )
        content = render.collaborators_text(lst)
        await interaction.edit_original_response(
            content=content, view=None, allowed_mentions=adapter.NO_MENTIONS
        )
        self.stop()
