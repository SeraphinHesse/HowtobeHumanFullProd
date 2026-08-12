# Phase G1 — Backend seam + headless-renderer feasibility probe

Source plan: `planning/GpuAndMasterSheetsPLAN.md` §6 "Phase G1" (lines 264–287),
decisions **D6** (dual backend, lines 139–146) and **D8** (fallback is the
Surface backend, lines 150–155), environment facts §4 (lines 168–179).

Phase G1 is **two things and nothing else**: (a) make the backend choice
explicit, (b) answer the one unverified environment question. **Zero behavioural
change — this phase must not move a pixel.** `backend_gpu.py` is G2's job and
must NOT appear in this diff.

---

## 1. Behavioral spec (how backend resolution works TODAY)

Every claim below is **verified** by reading the file at the cited line.

**The injection contract.**
`Renderer.__init__(self, coords, assets, backend=None)` stores the argument
verbatim: `engine/render/renderer.py:86-92` (`self._backend = backend`, line 89).
Nothing validates it, nothing wraps it. The injected object is a **callable**,
not a module and not a class instance — the call site is
`self._backend(target, draw_calls)` at `engine/render/renderer.py:206`.

**The lazy default.** The default is resolved *inside* `flush()`, on first draw,
at `engine/render/renderer.py:202-205`:

```python
if self._backend is None:
    from . import backend as _pygame_backend

    self._backend = _pygame_backend.draw
```

Three properties of that block are load-bearing and must survive this phase:
- The import is **function-local**, so `import engine.render` never imports
  pygame. That purity is asserted by the module docstrings at
  `engine/render/renderer.py:4-5` and `engine/render/__init__.py:3-4`, and by the
  package rule in `engine/CLAUDE.md` ("pygame imports are allowed ONLY in
  `render/`'s backend, `render/fonts.py`, `render/ground_cache.py`, …").
- Resolution happens at **first flush**, not at construction. Callers construct
  `Renderer` in pygame-free contexts and in Qt contexts alike —
  `engine/render/ground_cache.py:53`, `game/main.py:335`,
  `editor/panels/viewport.py:349` and `:476`, `editor/panels/vfx_preview.py:151`
  and `:378` all construct with **no** `backend=` argument.
- The resolved callable is **memoised onto `self._backend`**, so the import runs
  once per Renderer instance.

**What a backend must accept.** One positional pair, `(target, draw_calls)`.
`draw_calls` is a flat, order-significant, **heterogeneous** list built in
`flush()` (`engine/render/renderer.py:147-201`) in exactly this order:
1. sprite `DrawCall`s, depth-sorted (`renderer.py:138-171`);
2. overlay entries — `OverlayPolys` / `OverlayLines`, already converted to
   screen space (`renderer.py:172-182`);
3. the HUD pass — `HudSprite` is resolved by the renderer into a `DrawCall`
   carrying `slice=frame.slice` and `crop_rect=hud.crop` (`renderer.py:186-199`);
   `HudRect` / `HudText` / `HudLines` **pass through untouched** for the backend
   to `isinstance`-dispatch (`renderer.py:200-201`).

**What a backend must honour** (all verified in `engine/render/backend.py`, the
one shipped implementation):
- `DrawCall.size` — scale to it; a size equal to the source size is the identity
  (`backend.py:40-49`, `:216-219`). Sizes are quantized with
  `max(1, round_half_up(v))` (`backend.py:203`).
- `DrawCall.dest` — top-left, quantized with `round_half_up`
  (`backend.py:225`); the quantizer is `engine/render/item.py:14-22` and is
  authoritative (`engine/render/CLAUDE.md`, "Pixel quantizer").
- `DrawCall.flip` — horizontal only (`backend.py:220-221`,
  `pygame.transform.flip(surface, True, False)`).
- `DrawCall.tint` — multiply blend on a **copy** (`backend.py:222-224`,
  `BLEND_RGBA_MULT`).
- `DrawCall.slice` — nine-slice margins, **HUD only**; an all-zero slice or a
  1:1 draw falls back to the plain scale path (`backend.py:215-219`, compositor
  at `:52-97`).
- `DrawCall.crop_rect` — source sub-rect, **HUD only**, resolved *before*
  scale/nine-slice, clamped rather than raising (`backend.py:100-125`,
  `:210-213`).
- `OverlayLines` → `pygame.draw.lines` with `closed`/`width`
  (`backend.py:188-191`).
- `OverlayPolys` → filled polygon; RGBA with alpha < 255 goes through a bounding
  box `SRCALPHA` scratch surface (`backend.py:158-171`).
- `HudRect` (`backend.py:145-155`), `HudLines` (`backend.py:196-199`),
  `HudText` (`backend.py:132-142`, via the `engine.render.fonts` cache).
  `HudSprite` **never reaches a backend** (`backend.py:6-8`).
- **Order is exact**: sprite blits batch into one `target.blits(...)`, and any
  non-sprite call flushes the batch first (`backend.py:174-187`, `:226-227`).
- Return value is ignored — `flush()` returns its own count
  (`renderer.py:207-211`).

**How tests inject today.** `tools/tests/test_render.py:67-70` defines a
`RecordingBackend` whose `calls` list is asserted against; it is passed as
`Renderer(..., backend=backend)` throughout (e.g. `test_render.py:83-84`,
`:98-99`, `:288-289`). Two tests deliberately exercise the **real** default
resolution by constructing with no `backend=`: `test_render.py:325-342`
(`test_real_backend_draws_lines`, `Renderer(cs, AssetStore())` at `:333`) and
`test_render.py:348-366` (`TestHeadlessRender`, `:356`).
`tools/tests/test_ground_cache.py:69` also constructs `Renderer(cs, self.assets)`
with the default. **Inferred:** those three sites are the current, implicit
regression pin on default resolution — the plan asks for an explicit one.

**The unverified fact this phase must settle** (plan §4, lines 176–179):
whether an SDL2 `Renderer` can be created at all under `SDL_VIDEODRIVER=dummy`.
`editor/panels/viewport.py` sets that driver at module level and the whole test
suite plus `tools/smoke.py` run under it (plan D6, lines 143–146). The answer
decides whether G2's parity test can run in CI or must be marked live-only; it
does **not** affect D6, which stands either way.

---

## 2. Architecture plan

### 2.1 New file — `engine/render/backend_api.py` (pure)

**It is pure Python and imports pygame nowhere, not even lazily at module
level.** This is the deciding constraint: `engine/render/__init__.py` will
export from it (§2.3), and `import engine.render` must stay pygame-free
(`renderer.py:4-5`, `__init__.py:3-4`, `engine/CLAUDE.md` allow-list). Because
the module is pure, **`engine/CLAUDE.md`'s pygame allow-list does not change in
this phase** — G2 amends it when `backend_gpu.py` lands.

Contents, in this order:

1. **A module docstring that IS the contract.** Everything in §1's "what a
   backend must accept / must honour" lists, written as prose a G2 implementer
   can code against without re-deriving it from `backend.py`. Cite `backend.py`
   as the reference implementation. State explicitly that `slice` and
   `crop_rect` are HUD-only and that `HudSprite` never arrives (G2 asserts this
   rather than implementing it twice — plan lines 313–314), and that
   `item.round_half_up` — not the target API's own rounding — governs dests and
   sizes (plan lines 315–316).

2. **`Backend`, a `typing.Protocol`** — structural, not an ABC, and not
   inherited from. Rationale, state it in the docstring: the shipped backend is
   a plain **module-level function** (`backend.draw`, `backend.py:174`) and every
   test injects a **callable object** (`RecordingBackend.__call__`,
   `test_render.py:67-70`). An ABC would demand subclassing that no existing
   participant does and would break the injection contract this phase is
   forbidden to change. Shape:

   ```python
   class Backend(Protocol):
       def __call__(self, target, draw_calls) -> None: ...
   ```

   It is documentation + a type hook for G2/G4, **not** a runtime check.
   Do **not** decorate it `@runtime_checkable` and do **not** `isinstance`-test
   incoming backends anywhere: `Renderer.__init__` validates nothing today
   (`renderer.py:89`) and adding validation would be behavioural change.

3. **`default_backend()`** — the named, single home of the resolution the
   `flush()` block does inline today:

   ```python
   def default_backend():
       """The Surface backend (D8's fallback, the editor/test/smoke path).
       Imported INSIDE the function so `import engine.render` stays
       pygame-free — this is the lazy import moved out of Renderer.flush(),
       not a new one."""
       from . import backend
       return backend.draw
   ```

   **"Explicit" here means named and documented, not eager.** Resolving at
   import time or in `Renderer.__init__` would pull pygame into every pure
   caller and is out of scope.

**Not in this file:** any GPU/SDL2 name, any `select_backend("gpu")` switch, any
env-var reading. G4 owns host-side selection (plan lines 371–376); a switch added
now would be dead, untested code.

### 2.2 Modified — `engine/render/renderer.py`

Replace `renderer.py:202-205` with the delegating form, keeping the `is None`
memoise-once shape byte-for-byte otherwise:

```python
if self._backend is None:
    self._backend = backend_api.default_backend()
```

with `from . import backend_api` at the top of the module (pure import — safe
alongside the existing `from .hud import …` / `from .item import …` at
`renderer.py:22-23`). Update the module docstring at `renderer.py:4-5` to name
`backend_api` as the contract, keeping the "resolved lazily inside flush()"
sentence true.

**Nothing else in `renderer.py` changes.** `__init__`'s signature, the
`self._backend = backend` assignment (`:89`), and the call at `:206` are
untouched, so injection keeps working unchanged.

### 2.3 Modified — `engine/render/__init__.py`

Export `Backend` and `default_backend` (add the import beside `.item` /
`.renderer` at `__init__.py:10-13` and both names to `__all__`, keeping it
alphabetical). This is additive and pure. Do **not** export `backend.draw`
itself — that would make `engine.render` import pygame and break the rule at
`__init__.py:3-4`.

### 2.4 Modified — `engine/render/CLAUDE.md`

Amend the "Render flow" bullet that currently reads "the pygame backend
(`render/backend.py`) is lazily imported on first `flush()` and injectable for
tests": say the contract now lives in `engine/render/backend_api.py`
(`Backend` Protocol + `default_backend()`), that the module is pure so the
pygame allow-list is unchanged, and that resolution is still lazy-at-first-flush
and still injectable. Two or three sentences — do not restate the contract, the
new module holds it.

### 2.5 The feasibility probe (throwaway, NOT committed)

Write the script into the scratchpad directory, not the repo. Under
`SDL_VIDEODRIVER=dummy` (set before importing pygame, mirroring
`test_render.py:11`):

1. `pygame.init()`; `pygame._sdl2.video.Window("probe", size=(64, 64))`;
2. `pygame._sdl2.video.Renderer(window)`;
3. one `Texture.from_surface(renderer, surf)` upload of a small `SRCALPHA`
   surface;
4. `renderer.clear()` + `texture.draw(dstrect=…)` + `renderer.to_surface()`
   readback, and check the read-back pixel is the colour drawn.

Each step wrapped so the **first** failing step and its exception type/message
are reported rather than a bare traceback. Record: pygame-ce version, SDL
version, which step succeeded, the exception text if any, and whether the
readback pixel matched.

**Then edit exactly one place in the plan doc**: `planning/GpuAndMasterSheetsPLAN.md`
§4, the "**Unverified and load-bearing:**" bullet (lines 176–179). Replace it
with the measured result — keep the sentence stating that the answer only affects
whether the GPU path can be *tested* headlessly and that **D6 stands either way**.
Tag it as measured, naming the machine's pygame-ce/SDL versions. Do not touch
any other line of the plan doc (the Status column is the orchestrator's).

---

## 3. File scope

**New**
- `engine/render/backend_api.py` — §2.1. Pure; no pygame at module level.

**Modified**
- `engine/render/renderer.py` — one new pure import at the top (beside `:22-23`);
  the `flush()` block at `:202-205` delegates to `backend_api.default_backend()`;
  docstring line `:4-5` updated. Nothing else.
- `engine/render/__init__.py` — additive export of `Backend` + `default_backend`
  (`:10-13` imports, `:15-32` `__all__`).
- `engine/render/CLAUDE.md` — the "Render flow" bullet, per §2.4.
- `tools/tests/test_render.py` — one new `unittest.TestCase` appended (the tests
  in §4). Existing tests are **not** edited; if any of them needs a change to
  pass, that is a behavioural regression, not a test to update — stop and report.
- `planning/GpuAndMasterSheetsPLAN.md` — **only** the §4 "Unverified and
  load-bearing" bullet (lines 176–179), replaced with the probe result.

**Untouched — the boundary, stated hard.** This is a single-phase run, so there
is no shared-file contract to reconcile with a sibling phase; instead the fence
is absolute. Nothing outside `engine/render/**`, `engine/render/CLAUDE.md`, the
two named test files, and the one plan-doc line may be edited. Specifically **do
not** touch: `engine/render/backend.py` (its behaviour is the pin), any
`backend_gpu.py` (G2), `engine/render/ground_cache.py` (G3), `game/main.py`
(G4), `engine/CLAUDE.md` (G2 amends the allow-list; `backend_api.py` is pure so
there is nothing to add now), `editor/**`, `conftest.py` (no new test *module* is
created, so the `TIERS` table needs no entry — if you find yourself adding a new
test file, you have left this phase's scope).

The probe script goes in the scratchpad directory and is **never** added to the
repo, not even gitignored.

---

## 4. Exit gate + Quick Test

### Required new test (plan line 284)

In `tools/tests/test_render.py`, one class — e.g. `TestBackendResolution` —
asserting the default resolution is **unchanged** when nothing is injected:

- `engine.render.default_backend() is engine.render.backend.draw` (import the
  backend module inside the test, as `test_render.py:391` and `:416` already do).
- A `Renderer(make_cs(), FakeAssets())` built with **no** `backend=` has
  `_backend is None` before `flush()` and `is engine.render.backend.draw` after
  one flush onto a real dummy-driver `pygame.Surface` — the memoise-once shape.
- An **injected** backend is never replaced: after `flush()`, `_backend` is still
  the injected object, and it received the call.
- `import engine.render` does not pull in pygame — assert in a
  `subprocess`/fresh-interpreter check (`test_render.py:7` already imports
  `subprocess`, and the file has precedent for spawning one) that
  `"pygame" not in sys.modules` after `import engine.render`. Skip this one if
  an existing purity test already covers it — check before writing a duplicate.

Bare-minimum coverage. Do not expand into a backend-contract test matrix; the
contract is documentation in this phase, and G2's parity test is where it gets
exercised.

### Exit gate (plan line 286-287)

1. `py tools/smoke.py` — green.
2. `py -m pytest tools/tests/test_render.py tools/tests/test_ground_cache.py -q`
   — green, with the existing tests **unchanged**.
3. The probe result recorded in `planning/GpuAndMasterSheetsPLAN.md` §4, tagged
   measured, with pygame-ce/SDL versions and the first failing step (if any).

### Test budget — verbatim, inherited by the coder

> The coder's gate is `py tools/smoke.py` + `py -m pytest
> tools/tests/test_render.py tools/tests/test_ground_cache.py -q` — nothing
> wider. NOT the full suite, NOT a tier sweep, NOT `--affected` (the
> `test_guard.py` hook denies all three for subagents).

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.

### Quick Test (concrete, proves nothing moved)

**Pixel-identity check, headless, before/after.**
1. Before touching anything: `py tools/render_demo.py` — it renders the grey-X
   tile grid offscreen to `build/render_demo.png` (gitignored; documented in
   `engine/render/CLAUDE.md` "Verify", implemented at `tools/render_demo.py:83`
   where it constructs `Renderer(cs, assets)` with the **default** backend, i.e.
   exactly the resolution path this phase edits). Copy the PNG aside.
2. Make the change; run it again.
3. The two PNGs must be **byte-identical**. Report the comparison and how you
   made it. A difference of any size fails this phase.

**Live look** (state that it was live, per `engine/CLAUDE.md` "Verify"):
`py game/main.py`, open the first map, pan and zoom one step in and out, place
one building. Sprites, ground tiles and the HUD must look exactly as before —
same positions, same HUD text, no flicker, no console warning about a backend.
Then `py editor/main.py`, open a map, confirm the viewport still draws its grid
overlay (the `submit_overlay_lines` path) and that tile art appears; the editor
constructs `Renderer` with the default backend at
`editor/panels/viewport.py:349`/`:476`, so it is the second independent
exercise of the resolution.
