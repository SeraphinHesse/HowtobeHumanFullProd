"""Renderer (E-21/E-22): submit → resolve via assets → depth sort → coords
→ hand a flat DrawCall list to the backend.

Pure orchestration — no pygame imports here; the default pygame backend is
resolved lazily inside flush(), and tests inject a recording backend.

Anchor convention: a frame is blitted centred horizontally on its world
position. A tile-height frame (64x32) has its BOTTOM edge on the bottom of the
tile's diamond (world_to_screen y + tile_h·zoom) — covering the diamond exactly.
A frame TALLER than the tile (64x96 buildings/enemies/deco) is anchored one more
tile-height lower (bottom at y + 2·tile_h·zoom): the prototype's building-sheet
convention (src/buildings/building.py — "so the figure sits ON the tile, not
above it"), since the art is authored centred in the 96px frame. Per-entry
manifest offset_x/offset_y nudge from there.
"""
from .hud import HudLines, HudRect, HudSprite, HudText
from .item import LAYERS, DrawCall, OverlayLines, OverlayPolys

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

    def submit_overlay_polys(self, points, color):
        """Filled-polygon overlay (10J): WORLD points, RGB or RGBA color —
        alpha < 255 blends onto the target. Converted via coords at flush,
        drawn in the overlay pass alongside submit_overlay_lines, in
        submission order."""
        if len(points) < 3:
            raise ValueError("overlay polygon needs at least 3 points")
        self._overlay.append(OverlayPolys(tuple(points), color))

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
            # Frames taller than the tile anchor one extra tile-height lower so
            # the (centred) figure sits ON the tile, not above it — the
            # prototype's 64x96 building-sheet convention (bottom at 2·tile_h).
            anchor = tile_h * (2 if frame.frame_h > tile_h else 1)
            draw_calls.append(
                DrawCall(
                    surface=frame.surface,
                    dest=(
                        px - w / 2 + frame.offset_x * zoom,
                        py + anchor * zoom - h + frame.offset_y * zoom,
                    ),
                    size=(w, h),
                    tint=item.tint,
                    flip=item.flip,
                )
            )
        for entry in self._overlay:
            screen_points = tuple(coords.world_to_screen(*p) for p in entry.points)
            if isinstance(entry, OverlayPolys):
                draw_calls.append(OverlayPolys(points=screen_points, color=entry.color))
            else:
                draw_calls.append(OverlayLines(
                    points=screen_points,
                    color=entry.color,
                    width=entry.width,
                    closed=entry.closed,
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
