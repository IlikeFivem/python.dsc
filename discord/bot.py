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
