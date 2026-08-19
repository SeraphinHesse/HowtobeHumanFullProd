"""RenderItem (E-20) and DrawCall — pure data, no pygame.

Game objects submit RenderItems (visual intent, world space); the renderer
resolves them into DrawCalls (screen space, concrete surface) for the
backend. LAYERS is the fixed named draw order (E-26); HUD is drawn by the
host after flush, not through the item pipeline.
"""
import math
from dataclasses import dataclass

#: The layer is the PRIMARY sort key (``CoordinateSystem.depth_key``), so a
#: higher layer beats iso depth ALWAYS — it is "draw over, unconditionally",
#: never "draw over when in front". Reach for a layer only when that is
#: genuinely what you mean.
#:
#: ``deco`` is a cautionary tale and is emitted by NOTHING today: trees and
#: props used to ride it, which made every tree draw over every enemy no matter
#: whose feet were nearer, and (because ``Renderer._depth_pos`` resolves the
#: ``depth_pivot`` feet anchor only on ``entities``) silently discarded the very
#: anchors authored to sort them. They now ride ``entities`` — see
#: ``engine.tilemap.DECO_LAYER``. It stays in the tuple because removing it
#: would renumber ``overlay``, and because "unconditionally above the world" is
#: still a legitimate thing to want; just be sure you want it.
LAYERS = ("ground", "terrain", "entities", "deco", "overlay")


def round_half_up(v):
    """THE pixel quantizer for screen coordinates (backend dests/points, the
    ground cache's scroll/blit offsets). Builtin round() is banker's
    (half-to-even): two dests both ending in .5 can round OPPOSITE ways, and a
    pan crossing a .5 tie can double-step 2px — per item, inconsistently.
    floor(x + 0.5) breaks every tie the same way, so equal sub-pixel phases
    always land on the same pixel. One expression for the same reason as
    fit_factor: a second copy would drift the moment the rule changes."""
    return math.floor(v + 0.5)


@dataclass(frozen=True)
class RenderItem:
    slot_key: str
    world_pos: tuple
    layer: str = "entities"
    animation: str = "idle"
    anim_time_ms: int = 0
    tint: tuple = None
    flip: bool = False
    fit_tiles: float = 0.0   # 0 = no fit: draw at the raw frame size
    scale: float = 1.0       # extra multiplier applied after the fit
    # The LIVE master column this item is driven at (a season index, a
    # building's colour), or None for "no driver — use the entry's own stored
    # `column`". **None, not 0**: D3 promises a non-manual entry falls back to
    # its stored column when the caller supplies none, and 0 is a legitimate
    # live value (D7 clamps TO it), so 0 cannot double as "unset" without
    # making the first season/first colour unaddressable.
    column: int | None = None
    # VA-3: depth-key tie-break within this item's layer — +1 draws in front
    # of a same-tile entity, -1 behind it. 0 (every shipping caller) keeps the
    # historical ordering exactly. See CoordinateSystem.depth_key.
    rank: int = 0


@dataclass(frozen=True)
class DrawCall:
    surface: object  # opaque to everything except the backend
    dest: tuple  # screen-space topleft (floats; backend rounds)
    size: tuple  # final blit size in px (backend scales if != surface size)
    tint: tuple = None
    flip: bool = False
    slice: tuple = None  # nine-slice margins (frame px) — HUD sprites only
    crop_rect: tuple = None  # (x, y, w, h) source sub-rect (frame px) — HUD only


@dataclass(frozen=True)
class OverlayLines:
    """E-24 overlay primitive: a polyline. Submitted in WORLD points via
    Renderer.submit_overlay_lines; the renderer emits a screen-space copy
    after all sprite DrawCalls (overlays draw last)."""

    points: tuple  # ((x, y), ...) — world at submit, screen in the backend
    color: tuple
    width: int = 1
    closed: bool = False


@dataclass(frozen=True)
class OverlayPolys:
    """Filled polygon overlay (10J). Same world→screen contract as
    OverlayLines; color may be RGBA — an alpha < 255 alpha-blends onto the
    target (tile fills, splatters, glows)."""

    points: tuple  # ((x, y), ...) — world at submit, screen in the backend
    color: tuple  # RGB or RGBA


@dataclass(frozen=True)
class WorldFill:
    """fix/depth-sorted-world-fills: a flat-color world-space polygon fill
    (optional border), submitted via ``Renderer.submit_world_fill`` and
    sorted into the SAME depth-ordered queue as ``RenderItem`` — unlike
    ``OverlayLines``/``OverlayPolys`` (always drawn dead last, after every
    sprite, regardless of when submitted), a ``WorldFill``'s draw position is
    decided by its own ``world_pos``/``layer`` exactly like a building's, via
    the SAME ``depth_key`` formula. That is what lets a tile highlight or a
    wall segment draw BEHIND a specific building standing on/near it — a
    fixed always-on-top or always-behind layer can only ever approximate
    that; this participates in real per-tile depth instead.

    ``points`` are WORLD-space (converted via coords at flush, same contract
    as ``OverlayPolys``/``OverlayLines``). ``world_pos`` is the depth-sort
    anchor — pass the SAME ``(col, row)`` a building's own ``Transform``
    would use for the tile this fill belongs to, so ties against a same-tile
    building resolve by SUBMISSION ORDER (Python's stable sort): submit the
    fill before the building's ``RenderItem`` to draw it behind, after to
    draw it in front. ``color`` is the fill (``None`` = outline only);
    ``border`` is an optional outline colour drawn on top of the fill."""

    points: tuple             # world-space polygon points, closed implicitly
    world_pos: tuple          # (wx, wy) depth-sort anchor — the RenderItem convention
    layer: str = "entities"
    color: tuple = None       # RGB/RGBA fill; None = outline only
    border: tuple = None      # RGB/RGBA outline colour; None = no outline
    border_width: int = 2
    rank: int = 0             # VA-3 depth-key tie-break; see RenderItem.rank


@dataclass(frozen=True)
class WorldRect:
    """VA-3: a FIXED-PIXEL-SIZE rect at a world DEPTH anchor.

    The gap this fills: ``WorldFill`` is depth-sorted but its polygon is
    world-space, so it grows and shrinks with zoom — right for a tile
    diamond, wrong for a particle, which is a few screen pixels at every
    zoom level. ``HudRect`` has the fixed size but lives in the HUD pass,
    which is drawn dead last with no depth at all. A spark that wants to
    pass BEHIND the building that emitted it needs both halves, so this
    carries the depth anchor and the pixel geometry separately:

    * ``world_pos`` is the depth-sort anchor ONLY — same convention as
      ``WorldFill``/``RenderItem`` (the raw ``(col, row)`` a ``Transform``
      uses), and it is also the point ``offset`` is measured from.
    * ``offset`` and ``size`` are SCREEN pixels at the live zoom; the caller
      scales them (a particle's own offsets are authored at base zoom).

    ``world_pos`` is the depth-sort anchor and NOTHING ELSE — same convention
    as ``WorldFill``/``RenderItem`` (the raw ``(col, row)`` a ``Transform``
    uses). ``rect`` is FULLY-RESOLVED screen pixels, converted by the caller,
    which is deliberate rather than lazy: the caller already holds the
    ``CoordinateSystem`` (it needs it for the equivalent HUD submit), and
    resolving here instead would round at a different point than the HUD pass
    does. That difference is not hypothetical — it was measured at 1px on a
    slash line while writing ``test_depth_rank.py``, because
    ``VfxSystem.submit_hud`` truncates ``int(anchor + offset)`` while an
    offset resolved at flush truncates the offset alone. Carrying the final
    rect makes "the same effect drawn in the other pass does not move"
    true by construction instead of by matching two rounding sites by hand.

    It resolves to an ``OverlayPolys`` of four screen corners rather than a
    ``HudRect``: both backends draw polys, while ``backend_gpu`` raises on
    every HUD primitive by design (D7), so emitting a ``HudRect`` into the
    depth-sorted world list would crash the GPU host.
    """

    world_pos: tuple          # (wx, wy) depth-sort anchor ONLY
    rect: tuple               # (x, y, w, h) fully-resolved SCREEN px
    color: tuple              # RGB/RGBA
    layer: str = "entities"
    rank: int = 0


@dataclass(frozen=True)
class WorldLines:
    """VA-3: ``WorldRect``'s polyline sibling — screen-pixel geometry sorted
    at a world depth anchor. A melee slash is a handful of lines around its
    attacker, so ``VfxSystem``'s world submit needs this as well as the rect
    to mirror what its HUD submit already draws.

    ``points`` are FULLY-RESOLVED screen pixels, for the same reason
    ``WorldRect.rect`` is. Resolves to an ``OverlayLines``.
    """

    world_pos: tuple          # (wx, wy) depth-sort anchor ONLY
    points: tuple             # ((x, y), ...) fully-resolved SCREEN px
    color: tuple
    width: int = 1
    closed: bool = False
    layer: str = "entities"
    rank: int = 0
