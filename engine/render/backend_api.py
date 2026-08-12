"""The backend contract (G1): what `Renderer.flush()` hands a backend, and
what a backend must honour to draw it. Pure Python — imports pygame nowhere,
not even lazily at module level, so `import engine.render` (which exports
`Backend`/`default_backend` from here) stays pygame-free.

**The call shape.** A backend is a callable taking exactly one positional
pair, `(target, draw_calls)`. `target` is opaque to this module (the pygame
backend uses a `pygame.Surface`; a future backend may use something else).
`draw_calls` is a flat, order-significant, HETEROGENEOUS list built by
`Renderer.flush()`, in exactly this order:
1. sprite `DrawCall`s, depth-sorted;
2. overlay entries — `OverlayLines` / `OverlayPolys`, already converted to
   screen space;
3. the HUD pass — `HudSprite` is resolved by the renderer into a `DrawCall`
   carrying `slice=frame.slice` and `crop_rect=hud.crop`; `HudRect` /
   `HudText` / `HudLines` pass through UNTOUCHED for the backend to
   `isinstance`-dispatch. **`HudSprite` itself never reaches a backend** —
   the renderer always resolves it first.

**What a backend must honour** (see `backend.py`, the reference
implementation, for exact behaviour):
- `DrawCall.size` — scale to it; a size equal to the source size is the
  identity.
- `DrawCall.dest` — top-left. Both `dest` and `size` are quantized with
  `item.round_half_up` — **not** the target API's own rounding — which is
  the authoritative pixel quantizer for this whole package (see
  `engine/render/CLAUDE.md`, "Pixel quantizer"); a backend that rounds any
  other way will desync from the ground cache and other consumers that share
  the same quantizer.
- `DrawCall.flip` — horizontal only.
- `DrawCall.tint` — multiply blend on a COPY of the source (never mutate the
  cached/shared source surface).
- `DrawCall.slice` — nine-slice margins, **HUD only**. World sprites never
  set it. An all-zero slice or a 1:1 draw is the plain-scale identity.
- `DrawCall.crop_rect` — source sub-rect `(x, y, w, h)` in frame pixels,
  **HUD only**, resolved BEFORE scale/nine-slice; clamp into the surface's
  own bounds rather than raising (E-37 — rendering never raises on a bad
  asset reference).
- `OverlayLines` — a polyline: `points`, `color`, `width`, `closed`.
- `OverlayPolys` — a filled polygon: `points`, `color` (RGB or RGBA; alpha
  < 255 must alpha-blend onto the target).
- `HudRect` / `HudLines` / `HudText` — the three HUD primitives that reach a
  backend directly (screen-space already; no coords conversion). `HudText`
  draws via a font cache (`engine.render.fonts`).
- **Order is exact.** The list encodes draw order end to end; a backend that
  reorders or batches must reproduce visible output identical to drawing the
  list front-to-back.
- Return value is ignored — `Renderer.flush()` returns its own item count.
"""
from typing import Protocol


class Backend(Protocol):
    """Structural contract for a backend callable — a `typing.Protocol`, not
    an ABC, and nothing here does `isinstance`/`issubclass` against it.

    The shipped backend is a bare module-level function (`backend.draw`),
    and every test injects a plain callable object (`RecordingBackend.
    __call__` in `tools/tests/test_render.py`) — neither participant
    subclasses anything. An ABC would demand inheritance no existing
    participant has and `Renderer.__init__` validates nothing today
    (`self._backend = backend`, verbatim); adding a runtime check here would
    be a behavioural change this phase is forbidden to make. This class is
    documentation plus a type hook for a future backend/host-selection
    phase, not a runtime gate — it is deliberately NOT `@runtime_checkable`.
    """

    def __call__(self, target, draw_calls) -> None: ...


def default_backend():
    """The Surface backend (`engine.render.backend.draw`) — the fallback
    every host gets when it constructs a `Renderer` without a `backend=`
    argument. Imported INSIDE the function so `import engine.render` stays
    pygame-free: this is the lazy import moved out of `Renderer.flush()`,
    not a new one. Callers name this function; nothing resolves it eagerly
    or at import time."""
    from . import backend

    return backend.draw
