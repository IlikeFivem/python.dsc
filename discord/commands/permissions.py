from typing import Union, Dict, Callable

__all__ = ("Permission", "has_role", "has_any_role", "is_user", "is_owner", "permission")

class Permission:
    def __init__(self, id: Union[int, str], type: int, permission: bool = True, guild_id: int = None):
        self.id = id
        self.type = type
        self.permission = permission
        self.guild_id = guild_id

    def to_dict(self) -> Dict[str, Union[int, bool]]:
        return {"id": self.id, "type": self.type, "permission": self.permission}
    
def permission(role_id: int = None, user_id: int = None, permission: bool = True, guild_id: int = None):
    def decorator(func: Callable):
        if not role_id is None:
            app_cmd_perm = Permission(role_id, 1, permission, guild_id)
        elif not user_id is None:
            app_cmd_perm = Permission(user_id, 2, permission, guild_id)
        else:
            raise ValueError("role_id or user_id must be specified!")

        if not hasattr(func, '__app_cm_perms__'):
            func.__app_cmd_perms__ = []

        func.__app_cmd_perms__.append(app_cmd_perm)

        return func

    return decorator

def has_role(item: Union[int, str], guild_id: int = None):
    def decorator(func: Callable):
        if not hasattr(func, '__app_cmd_perms__'):
            func.__app_cmd_perms__ = []

            app_cmd_perm = Permission(item, 1, True, guild_id)

            func.__app_cmd_perms__.append(app_cmd_perm)

        return func
    return decorator

def has_any_role(*items: Union[int, str], guild_id: int = None):
    def decorator(func: Callable):
        if not hasattr(func, '__app_cmd_perms__'):
            func.__app_cmd_perms__ = []

        for item in items:
            app_cmd_perm = Permission(item, 1, True, guild_id)

            func.__app_cmd_perms__.append(app_cmd_perm)
        return func
    return decorator

def is_user(user: int, guild_id: int = None):
    def decorator(func: Callable):
        if not hasattr(func, '__app_cmd_perms__'):
            func.__app_cmd_perms__ = []

            app_cmd_perm = Permission(user, 2, True, guild_id)

            func.__app_cmd_perms__.append(app_cmd_perm)

        return func
    return decorator

def is_owner(guild_id: int = None):
    def decorator(func: Callable):
        if not hasattr(func, '__app_cmd_perms__'):
            func.__app_cmd_perms__ = []

        app_cmd_perm = Permission("owner", 2, True, guild_id)

        func.__app_cmd_perms__.append(app_cmd_perm)

        return func
    return decorator
