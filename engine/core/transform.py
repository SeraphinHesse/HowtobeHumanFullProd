"""Transform (E-10): world position + draw order. Pure Python.

wx/wy are fractional world tile coords (the only space game logic uses);
layer is one of the fixed draw layers (engine.render.LAYERS) and decides
which pass this object's sprites render in; rank breaks a same-tile tie
WITHIN that layer.
"""
from engine.render.item import LAYERS


class Transform:
    def __init__(self, wx=0.0, wy=0.0, layer="entities", rank=0):
        if layer not in LAYERS:
            raise ValueError(f"unknown draw layer {layer!r}; expected one of {LAYERS}")
        self.wx = wx
        self.wy = wy
        self.layer = layer
        # VA-3: the depth-key rank (CoordinateSystem.depth_key — a tie-break
        # below FRONT_RANK, absolute at or above it). It lives
        # here beside `layer` because it is the same kind of thing — draw-order
        # metadata about this object's position, with the same lifetime and the
        # same one consumer — and because SpriteAnimator already reads `layer`
        # off the transform, so a one-shot cosmetic sprite needs no new
        # component field to say "draw me behind the building I came from".
        # Notably NOT a SpriteAnimator field: that component is on every
        # building and enemy in the game, and this concerns exactly one
        # cosmetic object type (the same argument that kept `loop_count` off
        # it in ESV-5).
        self.rank = rank

    @property
    def world_pos(self):
        return (self.wx, self.wy)

    def to_dict(self):
        # `rank` is OMITTED at its default, the manifest `row_start`/`slice`
        # convention: every object saved before VA-3, and every object that
        # never opts in, serializes byte-identically to before.
        out = {"wx": self.wx, "wy": self.wy, "layer": self.layer}
        if self.rank:
            out["rank"] = self.rank
        return out

    @classmethod
    def from_dict(cls, data):
        return cls(wx=data["wx"], wy=data["wy"], layer=data["layer"],
                   rank=data.get("rank", 0))
