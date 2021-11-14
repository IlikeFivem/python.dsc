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

    