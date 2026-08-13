"""Renderer (E-21/E-22): submit → resolve via assets → depth sort → coords
→ hand a flat DrawCall list to the backend.

Pure orchestration — no pygame imports here; the backend contract lives in
`backend_api.py` (`Backend` Protocol + `default_backend()`), resolved
lazily inside flush(), and tests inject a recording backend.

Anchor convention: a frame is blitted CENTRED on the tile — horizontally on
its world position, vertically on the tile diamond's centre (world_to_screen y
+ tile_h/2·zoom). Continuous in frame_h, and byte-identical to the old
two-branch rule (bottom at tile_h·zoom for a 64x32 tile, at 2·tile_h·zoom for a
taller frame), which was this same rule spelled out for frame_h == tile_h and
frame_h == 3·tile_h — the prototype's building-sheet convention
(src/buildings/building.py — "so the figure sits ON the tile, not above it"),
since the art is authored centred in the 96px frame.

Sizing: an item with fit_tiles > 0 is downscaled — never upscaled — so it spans
at most fit_tiles tiles horizontally; `scale` multiplies on top of that (it is
the knob for art that IS smaller than its footprint). Per-entry manifest
offset_x/offset_y nudge from the anchor, riding the same scale (they are
authored in frame pixels).
"""
import time

from . import backend_api
from .hud import HudLines, HudRect, HudSprite, HudText
from .item import LAYERS, DrawCall, OverlayLines, OverlayPolys, WorldFill

_HUD_TYPES = (HudRect, HudText, HudSprite, HudLines)


def fit_factor(frame_w, tile_w, fit_tiles):
    """Downscale-only footprint fit: the factor that makes a `frame_w`-wide
    frame span at most `fit_tiles` tiles, never magnifying it. `fit_tiles` 0
    means "no fit" -> 1.0.

    THE one expression for it. A HUD element that must sit over a drawn sprite
    (an overhead bar) has to size that sprite exactly as flush() will, so it
    calls this rather than restating the formula.
    """
    if fit_tiles > 0.0 and frame_w > 0:
        return min(1.0, (fit_tiles * tile_w) / frame_w)
    return 1.0


def block_center_offset(fit_tiles):
    """Tiles from a footprint block's ANCHOR (its min corner) to the block's
    CENTRE, on each axis (ER-5). A `fit_tiles`-wide unit is drawn on its block
    centre, not on the anchor tile it is addressed by.

    Zero for `fit_tiles` 0 (no fit) and 1 (a one-tile unit), so every sprite that
    is not a multi-tile footprint is untouched. Added to BOTH world axes it
    cancels in the iso x term and lowers y by (fit_tiles-1) * tile_h/2 — a 2-tile
    unit used to draw exactly half a tile-height above its block.

    THE one expression, for the same reason as `fit_factor`: a HUD element that
    must sit over a drawn sprite has to shift with it, and a second copy of the
    rule would drift the moment the rule changes.
    """
    return (fit_tiles - 1) / 2 if fit_tiles > 0.0 else 0.0


def sprite_anchor_screen(cs, wx, wy, frame_w, fit_tiles, scale, offset_xy,
                         anchor_xy):
    """The SCREEN point an `anchor_xy` frame-px anchor resolves to on the
    sprite `flush` draws for world position `(wx, wy)` — the exact placement
    math above (`block_center_offset` + `fit_factor` + the tile-diamond-
    centre convention), evaluated for one anchor point instead of blitting a
    whole frame. `anchor_xy` of `(0, 0)` is the sprite's drawn CENTRE.

    Composes `block_center_offset`/`fit_factor` — never restates them, so
    this and `flush` cannot drift apart (fix-anchor-origin-parity: the ONE
    shared origin every anchor consumer, game and editor alike, must resolve
    through). `frame_h` never enters this — the centre sits on the tile
    diamond's centre regardless of frame height (see this module's Anchor
    convention docstring). Pure: no pygame, no game vocabulary."""
    zoom = cs.camera.zoom
    tile_w = cs.geometry.tile_w
    half_h = cs.geometry.tile_h / 2
    c = block_center_offset(fit_tiles)
    px, py = cs.world_to_screen(wx + c, wy + c)
    s = fit_factor(frame_w, tile_w, fit_tiles) * scale
    ox, oy = offset_xy
    ax, ay = anchor_xy
    return (px + (ox + ax) * zoom * s,
            py + half_h * zoom + (oy + ay) * zoom * s)


class Renderer:
    def __init__(self, coords, assets, backend=None):
        self._coords = coords
        self._assets = assets
        self._backend = backend
        self._hud_backend = None   # G4: always the Surface backend (D7)
        self._queue = []
        self._overlay = []
        self._hud = []
        # G4 instrumentation: milliseconds spent inside the backend call(s) of
        # the most recent flush, split world vs HUD. The host's frame-timing
        # line reads it; nothing else depends on it.
        self.last_flush_ms = {"world": 0.0, "hud": 0.0}

    @property
    def assets(self):
        """The store slots resolve through — exposed so a caller can ask a
        frame's size (to place something over the sprite it will draw)."""
        return self._assets

    def submit(self, item):
        if item.layer not in LAYERS:
            raise ValueError(f"unknown draw layer {item.layer!r}; expected one of {LAYERS}")
        self._queue.append(item)

    def submit_world_fill(self, points, world_pos, layer="entities",
                          color=None, border=None, border_width=2):
        """fix/depth-sorted-world-fills: a WorldFill, appended to the SAME
        queue as RenderItem so it sorts by real tile depth against buildings
        (see WorldFill's docstring) — unlike submit_overlay_lines/polys
        below, which stay a separate always-drawn-last pass and are
        UNCHANGED by this. ``points`` are WORLD units, converted at flush."""
        if len(points) < 3:
            raise ValueError("world fill needs at least 3 points")
        if layer not in LAYERS:
            raise ValueError(f"unknown draw layer {layer!r}; expected one of {LAYERS}")
        if color is None and border is None:
            raise ValueError("world fill needs a color, a border, or both")
        self._queue.append(WorldFill(tuple(points), world_pos, layer, color,
                                     border, border_width))

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

    def flush(self, target, hud_target=None):
        """Draw all submitted items to `target`, clear the queue, and return
        the number of items drawn. Target-agnostic (E-22): game window or
        editor offscreen surface alike.

        `hud_target` (G4, D7): world sprites + overlays go to `target`
        through `self._backend` (the GPU host's SDL backend), the HUD pass to
        `hud_target` through the SURFACE backend — always, whatever
        `self._backend` is. `None` (the editor / tools / the Surface host)
        keeps the historical single flat list and single call, byte-identical.

        The split is STRUCTURAL — by production site, never a post-hoc
        isinstance filter over a merged list. `slice`/`crop_rect` are set in
        exactly one place (the HUD loop below) and `backend_gpu.draw` raises
        on either, so producing the HUD calls into their own list is what
        GUARANTEES such a call cannot reach the world backend; a filter here
        reopens that crash."""
        coords = self._coords
        ordered = sorted(
            self._queue,
            key=lambda item: coords.depth_key(
                item.world_pos[0], item.world_pos[1], LAYERS.index(item.layer)
            ),
        )
        zoom = coords.camera.zoom
        tile_w = coords.geometry.tile_w
        half_h = coords.geometry.tile_h / 2
        draw_calls = []
        for item in ordered:
            if isinstance(item, WorldFill):
                # fix/depth-sorted-world-fills: reuses the OverlayPolys/
                # OverlayLines DrawCall shapes (the backend already
                # isinstance-dispatches them) but builds them HERE, in
                # depth-sorted position, instead of in the always-last
                # overlay block below — that is the entire mechanism that
                # lets a WorldFill draw behind or in front of a specific
                # building.
                screen_points = tuple(coords.world_to_screen(*p) for p in item.points)
                if item.color is not None:
                    draw_calls.append(OverlayPolys(points=screen_points, color=item.color))
                if item.border is not None:
                    draw_calls.append(OverlayLines(
                        points=screen_points, color=item.border,
                        width=item.border_width, closed=True))
                continue
            frame = self._assets.frame(item.slot_key, item.animation,
                                       item.anim_time_ms, column=item.column)
            # Multi-tile units are ADDRESSED by their anchor tile but DRAWN on
            # their block centre. Note this shifts the blit only — depth_key
            # (above) still sorts on the raw world_pos, or draw order would move
            # with it.
            c = block_center_offset(item.fit_tiles)
            px, py = coords.world_to_screen(
                item.world_pos[0] + c, item.world_pos[1] + c)
            s = fit_factor(frame.frame_w, tile_w, item.fit_tiles) * item.scale
            w = frame.frame_w * zoom * s
            h = frame.frame_h * zoom * s
            draw_calls.append(
                DrawCall(
                    surface=frame.surface,
                    dest=(
                        px - w / 2 + frame.offset_x * zoom * s,
                        py + half_h * zoom - h / 2 + frame.offset_y * zoom * s,
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
        hud_calls = draw_calls if hud_target is None else []
        for hud in self._hud:
            if isinstance(hud, HudSprite):
                frame = self._assets.frame(
                    hud.slot_key, hud.animation, hud.anim_time_ms,
                    extra_hidden=hud.hidden_frames or None)
                hud_calls.append(DrawCall(
                    surface=frame.surface,
                    dest=hud.dest,
                    size=hud.size,
                    tint=hud.tint,
                    flip=hud.flip,
                    slice=frame.slice,
                    crop_rect=hud.crop,
                ))
            else:
                hud_calls.append(hud)
        if self._backend is None:
            self._backend = backend_api.default_backend()
        _t0 = time.perf_counter()
        self._backend(target, draw_calls)
        world_ms = (time.perf_counter() - _t0) * 1000.0
        hud_ms = 0.0
        if hud_target is not None and hud_calls:
            if self._hud_backend is None:
                self._hud_backend = backend_api.default_backend()
            _t1 = time.perf_counter()
            self._hud_backend(hud_target, hud_calls)
            hud_ms = (time.perf_counter() - _t1) * 1000.0
        self.last_flush_ms = {"world": world_ms, "hud": hud_ms}
        count = len(self._queue) + len(self._overlay) + len(self._hud)
        self._queue.clear()
        self._overlay.clear()
        self._hud.clear()
        return count
