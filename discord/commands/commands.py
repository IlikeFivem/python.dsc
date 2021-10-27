from __future__ import annotations

import asyncio
from asyncio.exceptions import CancelledError
import types
import functools
import inspect
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Union
from typing_extensions import Required

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

def hooked_wrapped_callback(command, ctx, coro):
    @functools.wraps(coro)
    async def wrapped(arg):
        try:
            ret = await coro(arg)
        except ApplicationCommandError:
            raise
        except asyncio.CancelledError:
            return
        except Exception as exc:
            raise ApplicationCommandInvokeError(exc) from exc
        finally:
            await command.call_after_hooks(ctx)
        return ret
    return wrapped  

class _BaseCommand:
    __slots__ = ()

class ApplicationCommand(_BaseCommand):
    cog = None

    def __repr__(self):
        return f"<discord.commands.{self.__class__.__name__} name={self.name}>"

    def __eq__(self, other):
        return isinstance(other, self.__class__)
    
    async def __call__(self, ctx, *args, **kwargs):
        return await self.callback(ctx, *args, **kwargs)

    async def prepare(self, ctx: ApplicationContext) -> None:
        ctx.command = self

        if not await self.can_run(ctx):
            raise CheckFailure(f'The check functions for the command {self.name} failed')
        
        await self.call_before_hooks(ctx)
    
    async def invoke(self, ctx: ApplicationContext) -> None:
        await self.prepare(ctx)

        injected = hooked_wrapped_callback(self, ctx, self._invoke)
        await injected(ctx)

    async def can_run(self, ctx: ApplicationContext) -> bool:

        if not await ctx.bot.can_run(ctx):
            raise CheckFailure(f'The global check functions for command {self.name} failed.')

        predicates = self.checks
        if not predicates:
            return True
        
        return await async_all(predicate(ctx) for predicate in predicates)

    async def dispatch_error(self, ctx: ApplicationContext, error: Exception) -> None:
        ctx.command_failed = True
        cog = self.cog
        try:
            coro = self.in_error
        except AttributeError:
            pass
        else:
            injected = wrap_callback(coro)
            if cog is not None:
                await injected(cog, ctx, error)
            else:
                await injected(ctx, error)
        
        try:
            if cog is not None:
                local = cog.__class__._get_overridden_method(cog.cog_command_error)
                if local is not None:
                    wrapped = wrap_callback(local)
                    await wrapped(ctx, error)
        finally:
            ctx.bot.dispatch('application_command_error', ctx, error)
        
    def _get_signature_parameters(self):
        return OrderedDict(inspect.signature(self.callback).parameters)

    def error(self, coro):
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError('The error handler must be a coroutine.')
        
        self.on_error = coro
        return coro
    
    def has_error_handler(self) -> bool:
        return hasattr(self, 'on_error')
    
    def before_invoke(self, coro):
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError('The pre-invoke hook must be a coroutine.')

        self._before_invoke = coro
        return coro

    def after_invoke(self, coro):
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The post-invoke hook must be a coroutine.")

        self._after_invoke = coro
        return coro

    async def call_before_hooks(self, ctx: ApplicationContext) -> None:
        cog = self.cog
        if self._before_invoke is not None:
            instance = getattr(self._before_invoke, '__self__', cog)
            if instance:
                await self._before_invoke(instance, ctx)
            else:
                await self._before_invoke(ctx)
        
        if cog is not None:
            hook = cog.__class__._get_overridden_method(cog.cog_before_invoke)
            if hook is not None:
                await hook(ctx)
            
        hook = ctx.bot._before_invoke
        if hook is not None:
            await hook(ctx)
    
    async def call_after_hooks(self, ctx: ApplicationContext) -> None:
        cog = self.cog
        if self._after_invoke is not None:
            instance = getattr(self._after_invoke, '__self__', cog)
            if instance:
                await self._after_invoke(instance, ctx)
            else:
                await self._after_invoke(ctx)
        
        if cog is not None:
            hook = cog.__class__._get_overridden_method(ctx.cog_after_invoke)
            if hook is not None:
                await hook(ctx)
            
        hook = ctx.bot._after_invoke
        if hook is not None:
            await hook(ctx)

class SlashCommand(ApplicationCommand):
    type = 1
    
    def __new__(cls, *args, **kwargs) -> SlashCommand:
        self = super().__new__(cls)

        self.__original_kwargs__ = kwargs.copy()
        return self
    
    def __init__(self, func: Callable, *args, **kwargs) -> None:
        if not asyncio.iscoroutinefunction(func):
            raise TypeError("Callback must be a coroutine")
        self.callback = func

        self.guild_ids: Optional[List[int]] = kwargs.get("guild_ids", None)

        name = kwargs.get("name") or func.__name__
        validate_chat_input_name(name)
        self.name: str = name

        description = kwargs.get("description") or (
            inspect.cleandoc(func.__doc__).splitlines()[0]
            if func.__doc__ is not None
            else "No description provided"
        )
        validate_chat_input_description(description)
        self.description: str = description
        self.is_subcommand: bool = False
        self.cog = None

        params = self._get_signature_parameters()
        self.options = self._parse_options(params)

        try:
            checks = func.__commands_checks__
            checks.reverse()
        except AttributeError:
            checks = kwargs.get('checks', [])
        
        self.checks = checks

        self._before_invoke = None
        self._after_invoke = None

        # Permissions
        self.default_permission = kwargs.get("default_permission", True)
        self.permissions: List[Permission] = getattr(func, "__app_cmd_perms__", []) + kwargs.get("permissions", [])
        if self.permissions and self.default_permission:
            self.default_permission = False


    def _parse_options(self, params) -> List[Option]:
        final_options = []

        if list(params.items())[0][0] == "self":
            temp = list(params.items())
            temp.pop(0)
            params = dict(temp)
        params = iter(params.items())

        try:
            next(params)
        except StopIteration:
            raise ClientException(f'Callback for {self.name} command is missing "ctx" parameter.')

        final_options = []

        for p_name, p_obj in params:

            option = p_obj.annotation
            if option == inspect.Parameter.empty:
                option = str

            if self._is_typing_union(option):
                if self._is_typing_optional(option):
                    option = Option(option.__args__[0], "No description provided", required=False)
                else:
                    option = Option(option.__args__, "No description provided")
                
            if not isinstance(option, Option):
                option = Option(option, "No description provided")
                if p_obj.default != inspect.Parameter.empty:
                    option.required = False
            
            option.default = option.default or p_obj.default

            if option.default == inspect.Parameter.empty:
                option.default = None
            
            if option.name is None:
                option.name = p_name

            final_options.append(option)
        return final_options

    def _is_typing_union(self, annotation):
        return(
            getattr(annotation, '__origin__', None) is Union
            or type(annotation) is getattr(types, "UninonType", Union)
        )
    
    def _is_typing_optional(self, annotation):
        return self._is_typing_union(annotation) and type(None) in annotation.__args__

    def to_dict(self) -> Dict:
        as_dict = {
            "name": self.name,
            "description": self.description,
            "options": [o.to_dict() for o in self.options],
            "default_permission": self.default_permission,
        }
        if self.is_subcommand:
            as_dict["type"] = SlashCommandOptionType.sub_command.value

        return as_dict

    def __eq__(self, other) -> bool:
        return(
            isinstance(other, SlashCommand)
            and other.name == self.name
            and other.description == self.description
        )

    async def _invoke(self, ctx: ApplicationContext) -> None:
        kwargs = {}
        for arg in ctx.interaction.data.get("options", []):
            op = find(lambda x: x.name == arg["name"], self.options)
            arg = arg["value"]

            if(
                SlashCommandOptionType.user.value
                <= op.input_type.value
                <= SlashCommandOptionType.role.value
            ):
                name = "member" if op.input_type.name == "user" else op.input_type.name
                arg = await get_or_fetch(ctx.guild, name, int(arg), default=int(arg))
            
            elif op.input_type == SlashCommandOptionType.mentionable:
                arg_id = int(arg)
                arg = await get_or_fetch(ctx.guild, "member", arg_id)
                if arg is None:
                    arg = ctx.guild.get_role(arg_id) or arg_id
            
            elif op.input_type == SlashCommandOptionType.string and op._converter is not None:
                arg = await op._converter.convert(ctx, arg)

            kwargs[op.name] = arg 
        
        for o in self.options:
            if o.name not in kwargs:
                kwargs[o.name] = o.default

        if self.cog is not None:
            await self.callback(self.cog, ctx, **kwargs)
        else:
            await self.callback(ctx, **kwargs)

    def qualified_name(self):
        return self.name

    def copy(self):
        ret = self.__class__(self.callback, **self.__original_kwargs__)
        return self._ensure_assignment_on_copy(ret)

    def _ensure_assignment_on_copy(self, other):
        other._before_invoke = self._before_invoke
        other._after_invoke = self._after_invoke
        if self.checks != other.checks:
            other.checks = self.checks.copy()

        try:
            other.on_error = self.on_error
        except AttributeError:
            pass
        return other

    def _update_copy(self, kwargs: Dict[str, Any]):
        if kwargs:
            kw = kwargs.copy()
            kw.update(self.__original_kwargs__)
            copy = self.__class__(self.callback, **kw)
            return self._ensure_assignment_on_copy(copy)
        else:
            return self.copy()

channel_type_map = {
    'TextChannel': ChannelType.text,
    'VoiceChannel': ChannelType.voice,
    'StageChannel': ChannelType.stage_voice,
    'CategoryChannel': ChannelType.category
}

class Option:
    def __init__(
        self, input_type: Any, /, description: str = None, **kwargs
    ) -> None:
        self.name: Optional[str] = kwargs.pop("name", None)
        self.description = description or "No description provided"
        self._converter = None
        self.channel_types: List[SlashCommandOptionType] = kwargs.pop("channel_types", [])
        if not isinstance(input_type, SlashCommandOptionType):
            if hasattr(input_type, "convert"):
                self._converter = input_type
                input_type = SlashCommandOptionType.string
            else:
                _type = SlashCommandOptionType.from_datatype(input_type)
                if _type == SlashCommandOptionType.channel:
                    if not isinstance(input_type, tuple):
                        input_type = (input_type,)
                    for i in input_type:
                        if i.__name__ == 'GuildChannel':
                            continue

                        channel_type = channel_type_map[i.__name__]
                        self.channel_types.append(channel_type)
                input_type = _type
        self.input_type = input_type
        self.required: bool = kwargs.pop("required", True)
        self.choices: List[OptionalChoice] = [
            o if isinstance(o, OptionalChoice) else OptionalChoice(o)
            for o in kwargs.pop("choices", list())
        ]
        self.default = kwargs.pop("default", None)
        if self.input_type == SlashCommandOptionType.integer:
            minmax_types = (int,)
        elif self.input_type == SlashCommandOptionType.number:
            minmax_types = (int, float)
        else:
            minmax_types = (type(None),)
        minmax_typehint = Optional[Union[minmax_types]]

        self.min_value: minmax_typehint = kwargs.pop("min_value", None)
        self.max_value: minmax_typehint = kwargs.pop("max_value", None)

        if not (isinstance(self.min_value, minmax_types) or self.min_value is None):
            raise TypeError(f"Expected {minmax_typehint} for min_value, got \"{type(self.min_value).__name__}\"")
        if not (isinstance(self.max_value, minmax_types) or self.min_value is None):
            raise TypeError(f"Expected {minmax_typehint} for max_value, got \"{type(self.max_value).__name__}\"")
    def to_dict(self) -> Dict:
        as_dict = {
            "name": self.name,
            "description": self.description,
            "type": self.input_type.value,
            "required": self.required,
            "choices": [c.to_dict() for c in self.choices],
        }
        if self.channel_types:
            as_dict["channel_types"] = [t.value for t in self.channel_types]
        if self.min_value is not None:
            as_dict["min_value"] = self.min_value
        if self.max_value is not None:
            as_dict["max_value"] = self.max_value

        return as_dict
    
    def __repr__(self):
        return f"<discord.commands.{self._class__.__name__} name={self.name}>"

class OptionalChoice:
    def __init__(self, name: str, value: Optional[Union[str, int, float]] = None):
        self.name = name
        self.value = value or name

    def to_dict(self) -> Dict[str, Union[str, int, float]]:
        return {"name": self.name, "value": self.value}

