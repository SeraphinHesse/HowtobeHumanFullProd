"""Transform (E-10): world position + draw layer. Pure Python.

wx/wy are fractional world tile coords (the only space game logic uses);
layer is one of the fixed draw layers (engine.render.LAYERS) and decides
which pass this object's sprites render in.
"""
from engine.render.item import LAYERS


class Transform:
    def __init__(self, wx=0.0, wy=0.0, layer="entities"):
        if layer not in LAYERS:
            raise ValueError(f"unknown draw layer {layer!r}; expected one of {LAYERS}")
        self.wx = wx
        self.wy = wy
        self.layer = layer

    @property
    def world_pos(self):
        return (self.wx, self.wy)

    def to_dict(self):
        return {"wx": self.wx, "wy": self.wy, "layer": self.layer}

    @classmethod
    def from_dict(cls, data):
        return cls(wx=data["wx"], wy=data["wy"], layer=data["layer"])
