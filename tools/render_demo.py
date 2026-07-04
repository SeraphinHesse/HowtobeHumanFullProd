"""Visual check for the render pipeline: render the iso grid offscreen and
save a PNG. No window is opened (SDL dummy drivers).

Phase 9B additions (the phase Quick Test): a screen-space HUD text pass and a
waypoint-following dummy, proving Movement + HUD end-to-end in one frame.
Those two features come from the parallel 9B half (engine.core.Movement,
engine.render.HudText, Renderer.submit_hud); this demo is written against
that documented API. When the half is not merged yet the extras are skipped
with a printed notice and the grid still renders, so the file always runs.

Usage (from the repo root):
    py tools/render_demo.py [output.png]

Default output: build/render_demo.png (build/ is gitignored).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pygame

from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import GameObject, Scene, SpriteAnimator, Transform
from engine.render import Renderer, RenderItem

# Cross-half (parallel 9B) API — Movement component + HUD text primitive.
# Guarded so the grid still renders before that half is merged.
try:
    from engine.core import Movement
    from engine.render import HudText

    _NINEB_HALF = True
except ImportError:
    Movement = None
    HudText = None
    _NINEB_HALF = False

VIEW_W, VIEW_H = 1280, 720


def _add_walker(scene):
    """A dummy with a Movement component walking a short waypoint path. Its
    transform is advanced by Scene.update over the frames stepped below."""
    walker = GameObject(
        name="walker",
        tags=("dummy",),
        transform=Transform(wx=2.0, wy=2.0),
        components=[
            SpriteAnimator(slot_key="demo_entity"),
            Movement(waypoints=[[2.0, 2.0], [14.0, 2.0], [14.0, 14.0]], speed=6.0),
        ],
    )
    scene.spawn(walker)
    return walker


def _submit_hud(renderer):
    """A title + a fake love counter, proving HudText renders (screen space)."""
    renderer.submit_hud(HudText("How To Be Human — render demo", pos=(24, 20),
                                font_key="xl", color=(235, 230, 220)))
    renderer.submit_hud(HudText("love 128", pos=(VIEW_W - 24, 20),
                                font_key="hud_phase", color=(255, 210, 120),
                                align="right"))


def main():
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "build" / "render_demo.png"
    pygame.init()

    cs = load_coordinate_system(REPO / "data")
    # Centre the whole map in the viewport (clamp centres axes smaller than
    # the viewport; the 20x20 map is 1280x640 at zoom 1).
    cs.clamp(VIEW_W, VIEW_H)

    assets = AssetStore(frame_sizes={"demo_entity": (64, 96), "demo_deco": (64, 96)})
    renderer = Renderer(cs, assets)

    g = cs.geometry
    for row in range(g.map_rows):
        for col in range(g.map_cols):
            renderer.submit(RenderItem("demo_tile", (col, row), layer="ground"))
    for pos in [(10, 7), (7, 12), (15, 15), (12, 3)]:
        renderer.submit(RenderItem("demo_entity", pos, layer="entities"))
    for pos in [(6, 6), (14, 10)]:
        renderer.submit(RenderItem("demo_deco", pos, layer="deco"))
    renderer.submit(
        RenderItem("demo_highlight", (10, 10), layer="overlay", tint=(120, 255, 120, 255))
    )

    if _NINEB_HALF:
        scene = Scene()
        walker = _add_walker(scene)
        for _ in range(90):  # ~1.5 s at 60 fps — walker moves off its origin
            scene.update(1.0 / 60.0)
        for item in scene.render_items():
            renderer.submit(item)
        print(f"walker at ({walker.transform.wx:.2f}, {walker.transform.wy:.2f})")
        _submit_hud(renderer)
    else:
        print("render_demo: Movement/HudText not present (parallel 9B half not "
              "merged) - skipping walker + HUD, rendering grid only")

    target = pygame.Surface((VIEW_W, VIEW_H))
    target.fill((24, 20, 32))
    count = renderer.flush(target)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(target, str(out_path))
    print(f"rendered {count} items -> {out_path}")


if __name__ == "__main__":
    main()
