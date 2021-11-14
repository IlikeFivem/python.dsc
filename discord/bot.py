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
from .utils import MISSING, get, find, async_all
from .commands import (
    SlashCommand,
    SlashCommandGroup,
    MessageCommand,
    UserCommand,
    ApplicationCommand,
    ApplicationContext,
    command,
)
from .cog import CogMixin

from .errors import Forbidden, DiscordException
from .interactions import Interaction
from .enums import InteractionType

CoroFunc = Callable[..., Coroutine[Any, Any, Any]]
CFT = TypeVar('CFT', bound=CoroFunc)

__all__ = (
    'ApplicationCommandMixin',
    'Bot',
    'AutoShardedBot',
)

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
        raise NotImplementedError
    
    async def register_commands(self) -> None:
        commands = []

        # Global Command Permissions
        global_permissions: List = []

        registered_commands = await self.http.get_global_commands(self.user.id)
        for command in [
            cmd for cmd in self.pending_application_commands if cmd.guild_ids is None
        ]:
            as_dict = command.to_dict()
            if len(registered_commands) > 0:
                matches = [
                    x
                    for x in registered_commands
                    if x["name"] == command.name and x["type"] == command.type
                ]
                # TODO: rewrite this, it seems inefficient
                if matches:
                    as_dict["id"] = matches[0]["id"]
            commands.append(as_dict)

        cmds = await self.http.bulk_upsert_global_commands(self.user.id, commands)

        for i in cmds:
            cmd = get(
                self.pending_application_commands,
                name=i["name"],
                guild_ids=None,
                type=i["type"],
            )
            cmd.id = i["id"]
            self._application_commands[cmd.id] = cmd

            # Permissions (Roles will be converted to IDs just before Upsert for Global Commands)
            global_permissions.append({"id": i["id"], "permissions": cmd.permissions})

        update_guild_commands = {}
        async for guild in self.fetch_guilds(limit=None):
            update_guild_commands[guild.id] = []
        for command in [
            cmd
            for cmd in self.pending_application_commands
            if cmd.guild_ids is not None
        ]:
            as_dict = command.to_dict()
            for guild_id in command.guild_ids:
                to_update = update_guild_commands[guild_id]
                update_guild_commands[guild_id] = to_update + [as_dict]

        for guild_id, guild_data in update_guild_commands.items():
            try:
                cmds = await self.http.bulk_upsert_guild_commands(
                    self.user.id, guild_id, update_guild_commands[guild_id]
                )

                # Permissions for this Guild
                guild_permissions: List = []
            except Forbidden:
                if not guild_data:
                    continue
                print(f"Failed to add command to guild {guild_id}", file=sys.stderr)
                raise
            else:
                for i in cmds:
                    cmd = find(lambda cmd: cmd.name == i["name"] and cmd.type == i["type"] and int(i["guild_id"]) in cmd.guild_ids, self.pending_application_commands)
                    cmd.id = i["id"]
                    self._application_commands[cmd.id] = cmd

                    # Permissions
                    permissions = [
                        perm.to_dict()
                        for perm in cmd.permissions
                        if perm.guild_id is None
                        or (
                            perm.guild_id == guild_id and perm.guild_id in cmd.guild_ids
                        )
                    ]
                    guild_permissions.append(
                        {"id": i["id"], "permissions": permissions}
                    )

                for global_command in global_permissions:
                    permissions = [
                        perm.to_dict()
                        for perm in global_command["permissions"]
                        if perm.guild_id is None
                        or (
                            perm.guild_id == guild_id and perm.guild_id in cmd.guild_ids
                        )
                    ]
                    guild_permissions.append(
                        {"id": global_command["id"], "permissions": permissions}
                    )

                # Collect & Upsert Permissions for Each Guild
                # Command Permissions for this Guild
                guild_cmd_perms: List = []

                # Loop through Commands Permissions available for this Guild
                for item in guild_permissions:
                    new_cmd_perm = {"id": item["id"], "permissions": []}

                    # Replace Role / Owner Names with IDs
                    for permission in item["permissions"]:
                        if isinstance(permission["id"], str):
                            # Replace Role Names
                            if permission["type"] == 1:
                                role = get(
                                    self.get_guild(guild_id).roles,
                                    name=permission["id"],
                                )

                                # If not missing
                                if role is not None:
                                    new_cmd_perm["permissions"].append(
                                        {
                                            "id": role.id,
                                            "type": 1,
                                            "permission": permission["permission"],
                                        }
                                    )
                                else:
                                    print(
                                        "No Role ID found in Guild ({guild_id}) for Role ({role})".format(
                                            guild_id=guild_id, role=permission["id"]
                                        )
                                    )
                            # Add owner IDs
                            elif (
                                permission["type"] == 2 and permission["id"] == "owner"
                            ):
                                app = await self.application_info()  # type: ignore
                                if app.team:
                                    for m in app.team.members:
                                        new_cmd_perm["permissions"].append(
                                            {
                                                "id": m.id,
                                                "type": 2,
                                                "permission": permission["permission"],
                                            }
                                        )
                                else:
                                    new_cmd_perm["permissions"].append(
                                        {
                                            "id": app.owner.id,
                                            "type": 2,
                                            "permission": permission["permission"],
                                        }
                                    )
                        # Add the rest
                        else:
                            new_cmd_perm["permissions"].append(permission)

                    # Make sure we don't have over 10 overwrites
                    if len(new_cmd_perm["permissions"]) > 10:
                        print(
                            "Command '{name}' has more than 10 permission overrides in guild ({guild_id}).\nwill only use the first 10 permission overrides.".format(
                                name=self._application_commands[new_cmd_perm["id"]].name,
                                guild_id=guild_id,
                            )
                        )
                        new_cmd_perm["permissions"] = new_cmd_perm["permissions"][:10]

                    # Append to guild_cmd_perms
                    guild_cmd_perms.append(new_cmd_perm)

                # Upsert
                try:
                    await self.http.bulk_upsert_command_permissions(
                        self.user.id, guild_id, guild_cmd_perms
                    )
                except Forbidden:
                    print(
                        f"Failed to add command permissions to guild {guild_id}",
                        file=sys.stderr,
                    )
                    raise
    async def process_application_commands(self, interaction: Interaction) -> None:
        if interaction.type not in (InteractionType.application_command, InteractionType.auto_complete):
            return
        try:
            command = self._application_commands[interaction.data["id"]]
        except KeyError:
            self.dispatch("unknown_command", interaction)
        else:
            if interaction.type is InteractionType.auto_complete:
                return await command.invoke_autocomplete_callback(interaction)

            ctx = await self.get_application_context(interaction)
            ctx.command = command
            self.dispatch("application_command", ctx)
            try:
                if await self.can_run(ctx, call_once=True):
                    await ctx.command.invoke(ctx)
                else:
                    raise CheckFailure("The global check once functions failed.")
            except DiscordException as exc:
                await ctx.command.dispatch_error(ctx, exc)
            else:
                self.dispatch("application_command_completion", ctx)
    
    def slash_command(self, **kwargs):
        return self.application_command(cls=SlashCommand, **kwargs)
    

    def user_command(self, **kwargs):
        return self.application_command(cls=UserCommand, **kwargs)
    

    def message_command(self, **kwargs):
        return self.application_command(cls=MessageCommand, **kwargs)
    
    def application_command(self, **kwargs):
        def decorator(func) -> ApplicationCommand:
            kwargs.setdefault("parent", self)
            result = command(**kwargs)(func)
            self.add_application_command(result)
            return result
        return decorator
    
    def command(self, **kwargs):
        return self.application_command(**kwargs)
    
    def command_group(self, name: str, description: str, guild_ids = None) -> SlashCommandGroup:
        group = SlashCommandGroup(name, description, guild_ids)
        self.add_application_command(group)
        return group

    async def get_application_context(self, interaction: Interaction, cls=None) -> ApplicationContext:
        if cls is None:
            cls = ApplicationContext
        return cls(self, interaction)


class BotBase(ApplicationCommandMixin, CogMixin):
    _supports_prefixed_commands = False
    def __init__(self, description=None, *args, **options):
        # super(Client, self).__init__(*args, **kwargs)
        # I replaced ^ with v and it worked
        super().__init__(*args, **options)
        self.extra_events = {}  # TYPE: Dict[str, List[CoroFunc]]
        self.__cogs = {}  # TYPE: Dict[str, Cog]
        self.__extensions = {}  # TYPE: Dict[str, types.ModuleType]
        self._checks = []  # TYPE: List[Check]
        self._check_once = []
        self._before_invoke = None
        self._after_invoke = None
        self.description = inspect.cleandoc(description) if description else ""
        self.owner_id = options.get("owner_id")
        self.owner_ids = options.get("owner_ids", set())

        self.debug_guild = options.pop(
            "debug_guild", None
        )  # TODO: remove or reimplement
        self.debug_guilds = options.pop("debug_guilds", None)

        if self.owner_id and self.owner_ids:
            raise TypeError("Both owner_id and owner_ids are set.")

        if self.owner_ids and not isinstance(
            self.owner_ids, collections.abc.Collection
        ):
            raise TypeError(
                f"owner_ids must be a collection not {self.owner_ids.__class__!r}"
            )

        if self.debug_guild:
            if self.debug_guilds is None:
                self.debug_guilds = [self.debug_guild]
            else:
                raise TypeError("Both debug_guild and debug_guilds are set.")

        self._checks = []
        self._check_once = []
        self._before_invoke = None
        self._after_invoke = None
    async def on_connect(self):
        await self.register_commands()
    
    async def on_interaction(self, interaction):
        await self.process_application_commands(interaction)
    
    async def on_application_command_error(self, context: ApplicationContext, exception: DiscordException) -> None:
        if self.extra_events.get('on_application_command_error', None):
            return

        command = context.command
        if command and command.has_error_handler():
            return

        cog = context.cog
        if cog and cog.has_error_handler():
            return

        print(f"Ignoring exception in command {context.command}:", file=sys.stderr)
        traceback.print_exception(type(exception), exception, exception.__traceback__, file=sys.stderr)


    def check(self, func):
        self.add_check(func)
        return func

    def add_check(self, func, *, call_once: bool = False) -> None:
        if call_once:
            self._check_once.append(func)
        else:
            self._checks.append(func)
        
    def remove_check(self, func, *, call_once: bool = False) -> None:
        l = self._check_once if call_once else self._checks
        try:
            l.remove(func)
        except ValueError:
            pass
    

    def check_once(self, func):
        self.add_check(func, call_once=True)
        return func
    
    async def can_run(self, ctx: ApplicationCommand, *, call_once: bool = False) -> bool:
        data = self._check_once if call_once else self._checks

        if len(data) == 0:
            return True
        
        return await async_all(f(ctx) for f in data)

    def add_listener(self, func: CoroFunc, name: str = MISSING) -> None:
        name = func.__name__ if name is MISSING else name

        if not asyncio.iscoroutinefunction(func):
            raise TypeError('Listeners must be coroutines')

        if name in self.extra_events:
            self.extra_events[name].append(func)
        else:
            self.extra_events[name] = [func]
        
    def remove_listeners(self, func: CoroFunc, name: str = MISSING) -> None:
        name = func.__name__ if name is MISSING else name

        if name in self.extra_events:
            try:
                self.extra_events[name].remove(func)
            except ValueError:
                pass
    
    def listen(self, name: str = MISSING) -> Callable[[CFT], CFT]:
        def decorator(func: CFT) -> CFT:
            self.add_listener(func, name)
            return func
        return decorator
    
    def dispatch(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        super().dispatch(event_name, *args, **kwargs)
        ev = 'on_' + event_name
        for event in self.extra_events.get(ev, []):
            self._scheduled_event(event, ev, *args, **kwargs)
    
    def before_invoke(self, coro):
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The pre-invoke hook must be a coroutine.")

        self._before_invoke = coro
        return coro
    
    def after_invoke(self, coro):
        if not asyncio.iscoroutinefunction(coro):
            raise TypeError("The post-invoke hook must be a coroutine.")
        
        self._after_invoke = coro
        return coro

class Bot(BotBase, Client):
    pass

class AutoShardedBot(BotBase, AutoShardedClient):
    pass