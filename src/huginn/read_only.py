"""Read-only containers for state shared by every job in a run."""

from typing import NoReturn

import yaml


def freeze(value: object) -> object:
    """Recursively convert dicts and lists to their read-only counterparts."""
    if isinstance(value, dict):
        return ReadOnlyDict({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return ReadOnlyList(freeze(item) for item in value)
    return value


def thaw(value: object) -> object:
    """Recursively convert read-only containers back to plain dicts and lists."""
    if isinstance(value, dict):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, list):
        return [thaw(item) for item in value]
    return value


def _read_only(*_args: object, **_kwargs: object) -> NoReturn:
    """Reject a mutation of a shared container."""
    raise TypeError(
        "This value is read-only and shared by every job; "
        "use copy.deepcopy() to get a mutable copy"
    )


class ReadOnlyDict(dict[str, object]):
    """A dict that rejects mutation, used for state shared by every job.

    Reads, equality, `isinstance(..., dict)` and JSON serialization behave as
    for a plain dict. `copy.copy` and `copy.deepcopy` return mutable copies.
    """

    __setitem__ = __delitem__ = __ior__ = _read_only
    clear = pop = popitem = setdefault = update = _read_only

    def __copy__(self) -> dict[str, object]:
        """Return a shallow, mutable copy."""
        return dict(self)

    def __deepcopy__(self, memo: dict[int, object]) -> object:
        """Return a deep, mutable copy."""
        return thaw(self)

    def __reduce__(self) -> tuple[type[dict[str, object]], tuple[object]]:
        """Pickle as a plain dict."""
        return (dict, (thaw(self),))


class ReadOnlyList(list[object]):
    """A list that rejects mutation, used for state shared by every job.

    Reads, equality, `isinstance(..., list)` and JSON serialization behave as
    for a plain list. `copy.copy` and `copy.deepcopy` return mutable copies.
    """

    __setitem__ = __delitem__ = __iadd__ = __imul__ = _read_only
    append = extend = insert = pop = remove = clear = sort = reverse = _read_only

    def __copy__(self) -> list[object]:
        """Return a shallow, mutable copy."""
        return list(self)

    def __deepcopy__(self, memo: dict[int, object]) -> object:
        """Return a deep, mutable copy."""
        return thaw(self)

    def __reduce__(self) -> tuple[type[list[object]], tuple[object]]:
        """Pickle as a plain list."""
        return (list, (thaw(self),))


# Let `yaml.safe_dump` serialize read-only containers like plain dicts and lists.
yaml.SafeDumper.add_representer(ReadOnlyDict, yaml.SafeDumper.represent_dict)
yaml.SafeDumper.add_representer(ReadOnlyList, yaml.SafeDumper.represent_list)
