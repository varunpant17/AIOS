class ReflectionError(Exception):
    """Base class for normalized reflection boundary failures."""


class InvalidReflectionError(ReflectionError):
    pass


class ReflectorError(ReflectionError):
    pass
