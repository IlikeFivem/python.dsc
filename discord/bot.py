from __future__ import annotations

import asyncio
import collections
import inspect
import traceback
from .commands.errors import CheckFailure

from typing import (
    Any,
    Callable,
    Coroutine,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

import sys

from .client import Client
from .shard import AutoShardedClient
from .utils import MISSING, get, async_all
from .commands import (
    SlashCommand,
    SlashCommandGroup,
    MessageCommand,
    UserCommand,
    ApplicationCommand,
    ApplicationContext,
    command,
)
#from .cog import CogMixin

from .errors import Forbidden, DiscordException
from .interactions import Interaction

CoroFunc = Callable[..., Coroutine[Any, Any, Any]]
CFT = TypeVar('CFT', bound=CoroFunc)

class ApplicationCommandMixin:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pending_application_commands = []
        self._application_commands = {}

    @property
    def pending_application_commands(self):
        return self._pending_application_commands
    
    @property
    def commands(self) -> List[Union[ApplicationCommand, Any]]:
        commands = self.application_commands
        if self._supports_prefixed_commands:
            commands += self.prefixed_commands
        return commands
    
    @property
    def application_commands(self) -> List[ApplicationCommand]:
        return list(self._applcation_commands.values())
    
    def add_application_command(self, command: ApplicationCommand) -> None:
        if self.debug_guilds and command.guild_ids is None:
            command.guild_ids = self.debug_guilds
        self._pending_application_commands.append(command)
    

    def remove_application_command(self, command: ApplicationCommand) -> Optional[ApplicationCommand]:
        return self._application_commands.pop(command.id)
    
    @property
    def get_command(self):
        return self.get_application_command

    def get_application_command(self, name: str, guild_ids: Optional[List[int]] = None, type: Type[ApplicationCommand] = SlashCommand,) -> Optional[ApplicationCommand]:
        for command in self._application_commands.values():
            if(command.name == name and isinstance(command, type)):
                if guild_ids is not None and command.guild_ids != guild_ids:
                    return
                return command
    
    async def sync_commands(self) -> None:
        
