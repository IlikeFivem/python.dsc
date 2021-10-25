from ..errors import DiscordException

class ApplicationCommandError(DiscordException):
    pass

class CheckFailure(ApplicationCommandError):
    pass

class ApplicationCommandInvokeError(ApplicationCommandError):
    def __init__(self, e: Exception) -> None:
        self.original: Exception = e
        super().__init__(f'Application Command rasied an exception: {e.__class__.__name__}: {e}')