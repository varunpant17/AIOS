"""Small immutable JSON containers for frozen domain models."""

from copy import deepcopy
from collections.abc import Mapping
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict


class FrozenJsonDict(dict):
    def __init__(self, *args, **kwargs):
        self._immutable()

    def _immutable(self, *args, **kwargs):
        raise TypeError("JSON metadata is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = (
        _immutable
    )

    def __deepcopy__(self, memo):
        return freeze_json(
            {
                deepcopy(key, memo): deepcopy(value, memo)
                for key, value in dict.items(self)
            }
        )


class FrozenJsonList(list):
    def __init__(self, *args, **kwargs):
        self._immutable()

    def _immutable(self, *args, **kwargs):
        raise TypeError("JSON metadata is immutable")

    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = (
        reverse
    ) = sort = __iadd__ = __imul__ = _immutable

    def __deepcopy__(self, memo):
        return freeze_json([deepcopy(value, memo) for value in list.__iter__(self)])


def freeze_json(value: Any) -> Any:
    """Recursively detach and freeze JSON dictionaries/lists without changing shape."""
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        frozen = dict.__new__(FrozenJsonDict)
        dict.update(frozen, {key: freeze_json(item) for key, item in value.items()})
        return frozen
    if isinstance(value, list):
        frozen = list.__new__(FrozenJsonList)
        list.extend(frozen, [freeze_json(item) for item in value])
        return frozen
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


class ImmutableDomainModel(BaseModel):
    """Frozen Pydantic domain model whose copy updates are always revalidated."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False):
        data = self.model_dump(mode="python")
        if deep:
            data = deepcopy(data)
        if update:
            data.update(update)
        return type(self).model_validate(data)
