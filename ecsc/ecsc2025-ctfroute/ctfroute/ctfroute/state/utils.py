__all__ = [
    "AreEqual",
    "FilterView",
    "InternalMixin",
    "InternalState",
    "InternalStateUpdate",
    "are_equal",
]

from typing import Any, Generic, MutableSequence, Protocol, TypeVar

from pydantic import Field

ChildT = TypeVar("ChildT")
IndexT = TypeVar("IndexT")
DefaultT = TypeVar("DefaultT", None, Any)


class FilterView(Generic[ChildT, IndexT]):
    def __init__(self, parent: Any, attr: str, filter_attr: str):
        self.filter_attr = filter_attr
        self.attr = attr
        self.parent = parent

    @property
    def container(self) -> MutableSequence:
        path = self.attr.split(".")
        current = self.parent
        for step in path:
            current = getattr(current, step)
            if current is None:
                return []

        return current

    def __getitem__(self, index: IndexT) -> ChildT:
        for item in self.container:
            if getattr(item, self.filter_attr) == index:
                return item
        raise IndexError(
            f"No {self.attr.removesuffix('s')} with {self.filter_attr} == {index}"
        )

    def __setitem__(self, index: IndexT, value: ChildT) -> None:
        for i in range(len(self.container)):
            if index == getattr(self.container[i], self.filter_attr):
                self.container[i] = value
                return
        self.container.append(value)

    def __delitem__(self, index: IndexT) -> None:
        for i in range(len(self.container)):
            if index == getattr(self.container[i], self.filter_attr):
                del self.container[i]
                return
        raise IndexError(
            f"No {self.attr.removesuffix('s')} with {self.filter_attr} == {index}"
        )

    def __contains__(self, index: IndexT) -> bool:
        return any(getattr(item, self.filter_attr) == index for item in self.container)

    def get(self, index: IndexT, default: DefaultT = None) -> ChildT | DefaultT:
        try:
            return self[index]
        except IndexError:
            return default


InternalState = dict[str, str | None]
InternalStateUpdate = InternalState


class InternalMixin:
    """
    Add internal_state field.

    All entities in the state get an internal_state field for communication between
    controllers within one instance of ctf-route.
    """

    internal_state: InternalState = Field(default_factory=dict)


Model = TypeVar("Model", bound=InternalMixin, contravariant=True)


class AreEqual(Protocol[Model]):
    def __call__(self, a: Model, b: Model, **kwargs) -> bool: ...


def are_equal(
    a: Model,
    b: Model,
    *,
    fields: tuple[str, ...] | None = None,
    meta: tuple[str, ...] | None = None,
) -> bool:
    """
    Compare two internal entities.

    Use this function with functools.partial to build equalities between entities. Since
    different parts of the code typically only care about different subsets of entities'
    fields, it doesn't make much sense to bend over backwards and come up with canonical
    equalities for entities implement as methods. Instead, controllers etc. can just
    define their own ideas of equal teams / routers, etc.
    """
    if fields is None:
        fields = tuple()

    if meta is None:
        meta = tuple()

    # Not comparing any fields doesn't make sense, caller most likely forgot to make a
    #  partial or is doing something too dynamic.
    assert meta or fields

    for field in fields:
        # Note: Pydantic generally does a decent job at comparing instances of
        # BaseModel, so this should also work for nested models, e.g. drivers
        if getattr(a, field, None) != getattr(b, field, None):
            return False

    for field in meta:
        if a.internal_state.get(field) != a.internal_state.get(field):
            return False

    return True
