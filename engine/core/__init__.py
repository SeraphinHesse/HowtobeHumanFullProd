"""engine.core — GameObject/Component/Transform/Scene (E-10..E-15).

Pure Python, no pygame (it may import engine.render.item and engine.physics,
both pure). Shipped components: SpriteAnimator, Health, Movement, RangeSensor.
"""
from .component import Component, component_from_dict
from .gameobject import GameObject
from .health import Health, death_epoch
from .movement import Movement
from .range_sensor import RangeSensor
from .scene import Scene
from .sprite_animator import SpriteAnimator
from .transform import Transform

__all__ = [
    "Component",
    "GameObject",
    "Health",
    "Movement",
    "RangeSensor",
    "Scene",
    "SpriteAnimator",
    "Transform",
    "component_from_dict",
    "death_epoch",
]
