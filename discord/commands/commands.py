from __future__ import annotations

import asyncio
import types
import functools
import inspect
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Union

from ..enums import SlashCommandOptionType, ChannelType
from ..member import Member
from ..user import User
from ..message import Message
from .context import ApplicationContext
from ..utils import find, get_or_fetch, async_all
from ..errors import ValidationError, ClientException
from .errors import ApplicationCommandError, CheckFailure, ApplicationCommandInvokeError
from .permissions import Permission, has_role, has_any_role, is_user, is_owner, permission

__all__ = (
    "_BaseCommand",
    "ApplicationCommand",
    "SlashCommand",
    "Option",
    "OptionChoice",
    "option",
    "slash_command",
    "application_command",
    "user_command",
    "message_command",
    "command",
    "SlashCommandGroup",
    "ContextMenuCommand",
    "UserCommand",
    "MessageCommand",
    "command",
    "application_command",
    "slash_command",
    "user_command",
    "message_command",
    "has_role",
    "has_any_role",
    "is_user",
    "is_owner",
    "permission",
)

def wrap_callback(coro):
    @functools.wraps(coro)
    async def wrapped(*args, **kwargs):
        try:
            ret = await coro(*args, **kwargs)
        except ApplicationCommandError:
            raise
        except asyncio.CancelledError:
            return
        except Exception as exc:
            raise ApplicationCommandInvokeError(exc) from exc
        return ret
    return wrapped

