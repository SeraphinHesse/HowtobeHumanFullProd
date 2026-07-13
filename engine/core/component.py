"""Component base (E-11): declared, typed, JSON-serializable fields.

Subclasses declare fields as class-level annotations with defaults:

    class Health(Component):
        max_hp: int = 10
        hp: int = 10

ALL gameplay state lives in these declared fields — that is what makes
serialization (E-15) and the editor inspector work generically. Field types
must be JSON-safe (bool/int/float/str/list/dict). Subclasses may add
behavior methods, an optional update(dt), and an optional
render_items(transform) hook yielding RenderItems.

Every Component subclass auto-registers by class name for deserialization
(component_from_dict). Pure Python — no pygame.
"""

import inspect

_JSON_FIELD_TYPES = (bool, int, float, str, list, dict)

_REGISTRY = {}


def _own_annotations(cls):
    """This class's OWN declared field annotations (never inherited).

    Python 3.14 (PEP 649/749) evaluates annotations lazily: a class's
    annotations no longer live eagerly in ``cls.__dict__["__annotations__"]``
    (they sit behind ``__annotate__``), so the old ``__dict__.get`` read
    returned ``{}`` on 3.14 and no fields registered — every component with
    declared fields then raised "has no field". ``inspect.get_annotations``
    reads the correct source on every supported version and, for a class,
    returns only that class's own annotations (does NOT fall through the MRO
    the way plain ``cls.__annotations__`` does)."""
    return inspect.get_annotations(cls)


class Component:
    _fields = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        fields = dict(cls._fields)  # inherit parent declarations
        for name, ftype in _own_annotations(cls).items():
            if ftype not in _JSON_FIELD_TYPES:
                raise TypeError(
                    f"{cls.__name__}.{name}: field type {ftype!r} is not "
                    f"JSON-serializable; allowed: {_JSON_FIELD_TYPES}"
                )
            if not hasattr(cls, name):
                raise TypeError(f"{cls.__name__}.{name}: declared field needs a default")
            fields[name] = ftype
        cls._fields = fields
        _REGISTRY[cls.__name__] = cls

    def __init__(self, **overrides):
        for name in self._fields:
            default = getattr(type(self), name)
            if isinstance(default, (list, dict)):
                default = type(default)(default)  # per-instance copy, never shared
            setattr(self, name, default)
        for name, value in overrides.items():
            if name not in self._fields:
                raise TypeError(f"{type(self).__name__} has no field {name!r}")
            self._check_type(name, value)
            setattr(self, name, value)

    def _check_type(self, name, value):
        ftype = self._fields[name]
        ok = isinstance(value, ftype) or (ftype is float and isinstance(value, int))
        if not ok or (ftype is not bool and isinstance(value, bool)):
            raise TypeError(
                f"{type(self).__name__}.{name} expects {ftype.__name__}, "
                f"got {type(value).__name__}"
            )

    # -- lifecycle hooks (called by GameObject) ---------------------------

    def on_added(self, owner):
        """Owner seam: called by GameObject.add_component right after this
        component is appended. Default no-op. A component that needs its
        owner's transform caches it here as ``self._owner = owner`` — an
        underscore-prefixed transient (non-authoritative), which is fine:
        the E-11 setattr guard is on GameObject, not Component."""

    def update(self, dt):
        """Optional per-frame behavior; dt in seconds."""

    # Subclasses with a visual presence define:
    #   render_items(transform) -> iterable[RenderItem]
    # Scene.render_items() collects from any component providing it.

    # -- serialization (E-15) ---------------------------------------------

    def to_dict(self):
        return {
            "type": type(self).__name__,
            "fields": {name: getattr(self, name) for name in self._fields},
        }


def component_from_dict(data):
    """Inverse of Component.to_dict. KeyError on unregistered type."""
    cls = _REGISTRY[data["type"]]
    return cls(**data["fields"])
