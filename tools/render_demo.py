"""Visual check for Phase 1: render the grey-X iso grid offscreen and save
a PNG. No window is opened (SDL dummy drivers).

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
from engine.render import Renderer, RenderItem

VIEW_W, VIEW_H = 1280, 720


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
    for pos in [(4, 4), (10, 7), (7, 12), (15, 15), (12, 3)]:
        renderer.submit(RenderItem("demo_entity", pos, layer="entities"))
    for pos in [(6, 6), (14, 10)]:
        renderer.submit(RenderItem("demo_deco", pos, layer="deco"))
    renderer.submit(
        RenderItem("demo_highlight", (10, 10), layer="overlay", tint=(120, 255, 120, 255))
    )

    target = pygame.Surface((VIEW_W, VIEW_H))
    target.fill((24, 20, 32))
    count = renderer.flush(target)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(target, str(out_path))
    print(f"rendered {count} items -> {out_path}")


if __name__ == "__main__":
    main()
