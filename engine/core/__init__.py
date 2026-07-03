"""engine.core — GameObject/Component/Transform/Scene (E-10..E-15).

Pure Python, no pygame (it may import engine.render.item, which is pure
data). Shipped components: SpriteAnimator + Health; Movement and
RangeSensor arrive with engine/physics (E-12 phasing).
"""
from .component import Component, component_from_dict
from .gameobject import GameObject
from .health import Health
from .scene import Scene
from .sprite_animator import SpriteAnimator
from .transform import Transform

__all__ = [
    "Component",
    "GameObject",
    "Health",
    "Scene",
    "SpriteAnimator",
    "Transform",
    "component_from_dict",
]
