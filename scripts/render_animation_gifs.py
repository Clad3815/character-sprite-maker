#!/usr/bin/env python3
"""Render per-animation GIF previews from a character atlas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image


def load_request(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"request file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def specs(request: dict[str, Any]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    atlas_raw = request.get("atlas")
    if not isinstance(atlas_raw, dict):
        raise SystemExit("request missing atlas")
    atlas = {
        "columns": int(atlas_raw.get("columns", 0)),
        "rows": int(atlas_raw.get("rows", 0)),
        "cell_width": int(atlas_raw.get("cell_width", 0)),
        "cell_height": int(atlas_raw.get("cell_height", 0)),
    }
    animations_raw = request.get("animations")
    if not isinstance(animations_raw, list):
        raise SystemExit("request missing animations")
    animations = [item for item in animations_raw if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("frames"), int) and isinstance(item.get("row"), int)]
    return atlas, sorted(animations, key=lambda item: int(item["row"]))


def checker_background(size: tuple[int, int], block: int = 8) -> Image.Image:
    width, height = size
    bg = Image.new("RGBA", size, (255, 255, 255, 255))
    pix = bg.load()
    for y in range(height):
        for x in range(width):
            v = 222 if ((x // block + y // block) % 2) else 242
            pix[x, y] = (v, v, v, 255)
    return bg


def composite_preview(frame: Image.Image, scale: int) -> Image.Image:
    if scale != 1:
        frame = frame.resize((frame.width * scale, frame.height * scale), Image.Resampling.NEAREST)
    bg = checker_background(frame.size)
    bg.alpha_composite(frame.convert("RGBA"))
    return bg.convert("P", palette=Image.Palette.ADAPTIVE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlas")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--fps", type=int, default=0, help="Override FPS for all animations. Default uses per-animation/request fps.")
    args = parser.parse_args()

    request = load_request(Path(args.request).expanduser().resolve())
    atlas_spec, animations = specs(request)
    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with Image.open(Path(args.atlas).expanduser().resolve()) as opened:
        atlas = opened.convert("RGBA")
    for animation in animations:
        state = str(animation["name"])
        row = int(animation["row"])
        frame_count = int(animation["frames"])
        fps = args.fps or int(animation.get("fps") or 12)
        duration_ms = max(20, round(1000 / fps))
        frames = []
        for column in range(frame_count):
            left = column * atlas_spec["cell_width"]
            top = row * atlas_spec["cell_height"]
            cell = atlas.crop((left, top, left + atlas_spec["cell_width"], top + atlas_spec["cell_height"]))
            frames.append(composite_preview(cell, max(1, args.scale)))
        if not frames:
            continue
        output = out_dir / f"{state}.gif"
        frames[0].save(output, save_all=True, append_images=frames[1:], duration=duration_ms, loop=0, optimize=False, disposal=2)
        written.append(str(output))
    print(json.dumps({"ok": True, "output_dir": str(out_dir), "gifs": written}, indent=2))


if __name__ == "__main__":
    main()
