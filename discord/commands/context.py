from typing import TYPE_CHECKING, Optional, Union

import discord.abc

if TYPE_CHECKING:
    import discord
    from discord.state import ConnectionState

from ..guild import Guild
from ..interactions import Interaction, InteractionResponse
from ..member import Member
from ..message import Message
from ..user import User
from ..utils import cached_property

class ApplicationContext(discord.abc.Messageable):
    def __init__(self, bot: "discord.Bot", interaction: Interaction):
        self.bot = bot
        self.interaction = interaction
        self.command = None
        self._state: ConnectionState = self.interaction._state

    async def _get_channel(self) -> discord.abc.Messageable:
        return self.channel

    @cached_property
    def channel(self):
        return self.interaction.channel

    @cached_property
    def channel_id(self) -> Optional[int]:
        return self.interaction.channel_id
    
    @cached_property
    def guild(self) -> Optional[Guild]:
        return self.interaction.guild
    
    @cached_property
    def guild_id(self) -> Optional[int]:
        return self.interaction.guild_id

    @cached_property
    def message(self) -> Optional[Message]:
        return self.interaction.message

    @cached_property
    def user(self) -> Optional[Union[Member, User]]:
        return self.interaction.user

    @property
    def voice_client(self):
        return self.guild.voice_client

    @cached_property
    def response(self) -> InteractionResponse:
        return self.interaction.response
    
    author = user

    @property
    def respond(self):
        return self.followup.send if self.response.is_done() else self.interaction.response.send_message

    @property
    def defer(self):
        return self.interaction.response.defer
    
    @property
    def followup(self):
        return self.interaction.followup

    async def delete(self):
        if not self.response.is_done():
            await self.defer()

        return await self.interaction.delete_original_message()
    
    @property
    def edit(self):
        return self.interaction.edit_original_message