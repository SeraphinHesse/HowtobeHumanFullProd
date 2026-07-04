"""Renderer (E-21/E-22): submit → resolve via assets → depth sort → coords
→ hand a flat DrawCall list to the backend.

Pure orchestration — no pygame imports here; the default pygame backend is
resolved lazily inside flush(), and tests inject a recording backend.

Anchor convention: a frame is blitted centred horizontally on its world
position with its BOTTOM edge on the bottom of that tile's diamond
(world_to_screen y + tile_h·zoom). A 64x32 tile frame therefore covers its
diamond exactly; taller frames (e.g. 64x96 buildings) rise above it.
"""
from .hud import HudLines, HudRect, HudSprite, HudText
from .item import LAYERS, DrawCall, OverlayLines

_HUD_TYPES = (HudRect, HudText, HudSprite, HudLines)


class Renderer:
    def __init__(self, coords, assets, backend=None):
        self._coords = coords
        self._assets = assets
        self._backend = backend
        self._queue = []
        self._overlay = []
        self._hud = []

    def submit(self, item):
        if item.layer not in LAYERS:
            raise ValueError(f"unknown draw layer {item.layer!r}; expected one of {LAYERS}")
        self._queue.append(item)

    def submit_overlay_lines(self, points, color, width=1, closed=False):
        """E-24 overlay pass: a polyline in WORLD coordinates (e.g. the
        editor's grid lines). Converted via coords at flush and appended
        AFTER every sprite DrawCall — overlays always draw on top."""
        if len(points) < 2:
            raise ValueError("overlay polyline needs at least 2 points")
        self._overlay.append(OverlayLines(tuple(points), color, width, closed))

    def submit_hud(self, item):
        """HUD pass (E-12): a screen-space primitive (HudRect / HudText /
        HudSprite / HudLines). Folded into the flat draw list after every
        sprite and overlay at flush — HUD always draws last, in pixels."""
        if not isinstance(item, _HUD_TYPES):
            raise TypeError(
                f"submit_hud expects one of {[t.__name__ for t in _HUD_TYPES]}, "
                f"got {type(item).__name__}"
            )
        self._hud.append(item)

    def flush(self, target):
        """Draw all submitted items to `target`, clear the queue, and return
        the number of items drawn. Target-agnostic (E-22): game window or
        editor offscreen surface alike."""
        coords = self._coords
        ordered = sorted(
            self._queue,
            key=lambda item: coords.depth_key(
                item.world_pos[0], item.world_pos[1], LAYERS.index(item.layer)
            ),
        )
        zoom = coords.camera.zoom
        tile_h = coords.geometry.tile_h
        draw_calls = []
        for item in ordered:
            frame = self._assets.frame(item.slot_key, item.animation, item.anim_time_ms)
            px, py = coords.world_to_screen(*item.world_pos)
            w = frame.frame_w * zoom
            h = frame.frame_h * zoom
            draw_calls.append(
                DrawCall(
                    surface=frame.surface,
                    dest=(
                        px - w / 2 + frame.offset_x * zoom,
                        py + tile_h * zoom - h + frame.offset_y * zoom,
                    ),
                    size=(w, h),
                    tint=item.tint,
                    flip=item.flip,
                )
            )
        for lines in self._overlay:
            draw_calls.append(OverlayLines(
                points=tuple(coords.world_to_screen(*p) for p in lines.points),
                color=lines.color,
                width=lines.width,
                closed=lines.closed,
            ))
        # HUD pass (E-12): screen space already — no coords conversion, no
        # depth sort. Sprites resolve to DrawCalls; the rest pass through for
        # the backend to isinstance-dispatch (like OverlayLines).
        for hud in self._hud:
            if isinstance(hud, HudSprite):
                frame = self._assets.frame(hud.slot_key)
                draw_calls.append(DrawCall(
                    surface=frame.surface,
                    dest=hud.dest,
                    size=hud.size,
                    tint=hud.tint,
                    flip=hud.flip,
                ))
            else:
                draw_calls.append(hud)
        if self._backend is None:
            from . import backend as _pygame_backend

            self._backend = _pygame_backend.draw
        self._backend(target, draw_calls)
        count = len(self._queue) + len(self._overlay) + len(self._hud)
        self._queue.clear()
        self._overlay.clear()
        self._hud.clear()
        return count
