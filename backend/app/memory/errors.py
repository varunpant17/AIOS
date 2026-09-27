class MemoryError(Exception):
    """Base class for normalized AIOS memory boundary errors."""


class InvalidMemoryError(MemoryError):
    pass


class MemoryNotFoundError(MemoryError):
    pass


class DuplicateMemoryError(MemoryError):
    pass


class InvalidMemoryQueryError(MemoryError):
    pass


class MemoryStoreError(MemoryError):
    pass
