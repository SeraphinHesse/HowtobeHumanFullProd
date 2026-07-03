"""GameObject (E-10): stable id, name, Transform, ordered components,
lifecycle hooks. Pure Python.

Rule (E-11), mechanically enforced: components are what the editor sees;
subclasses are behavior convenience. After construction, setting a NEW
public attribute raises — authoritative state must live in a declared
component field. Underscore-prefixed attributes stay writable for
transient caches (never serialized, explicitly non-authoritative).

Serialization (E-15) round-trips through a JSON dict. from_dict returns a
base GameObject — components carry all state, so subclass identity is not
persisted.
"""
import uuid

from .component import component_from_dict
from .transform import Transform

_ENGINE_ATTRS = frozenset({"id", "name", "tags", "transform", "components"})


class GameObject:
    def __init__(self, id=None, name="", tags=(), transform=None, components=()):
        self.id = id if id is not None else uuid.uuid4().hex
        self.name = name
        self.tags = tuple(tags)
        self.transform = transform if transform is not None else Transform()
        self.components = []
        self._sealed = True  # setattr guard active from here on
        for component in components:
            self.add_component(component)

    def __setattr__(self, name, value):
        if (
            getattr(self, "_sealed", False)
            and not name.startswith("_")
            and name not in _ENGINE_ATTRS
        ):
            raise AttributeError(
                f"{type(self).__name__}.{name}: gameplay state must live in a "
                "declared component field, not a GameObject attribute (E-11); "
                "underscore-prefixed transient caches are allowed"
            )
        super().__setattr__(name, value)

    # -- components -------------------------------------------------------

    def add_component(self, component):
        self.components.append(component)
        return component

    def get_component(self, cls):
        """First component of the given type, or None."""
        for component in self.components:
            if isinstance(component, cls):
                return component
        return None

    # -- lifecycle (E-10) — called by Scene --------------------------------

    def on_spawn(self):
        """Hook: object became live in the scene (frame boundary, E-13)."""

    def update(self, dt):
        """Fixed order: components in list order, then the subclass hook."""
        for component in self.components:
            component.update(dt)
        self.on_update(dt)

    def on_update(self, dt):
        """Subclass behavior hook; state changes go through components."""

    def on_despawn(self):
        """Hook: object removed from the scene (frame boundary, E-13)."""

    # -- serialization (E-15) ----------------------------------------------

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "tags": list(self.tags),
            "transform": self.transform.to_dict(),
            "components": [c.to_dict() for c in self.components],
        }

    @classmethod
    def from_dict(cls, data):
        return GameObject(
            id=data["id"],
            name=data["name"],
            tags=tuple(data["tags"]),
            transform=Transform.from_dict(data["transform"]),
            components=[component_from_dict(c) for c in data["components"]],
        )
