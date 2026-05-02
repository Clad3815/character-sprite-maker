#!/usr/bin/env python3
"""Create a labeled contact sheet from a configurable character atlas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


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
        "width": int(atlas_raw.get("width", 0)),
        "height": int(atlas_raw.get("height", 0)),
    }
    animations_raw = request.get("animations")
    if not isinstance(animations_raw, list):
        raise SystemExit("request missing animations")
    animations = [item for item in animations_raw if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("frames"), int) and isinstance(item.get("row"), int)]
    return atlas, sorted(animations, key=lambda item: int(item["row"]))


def draw_checker(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], size: int = 8) -> None:
    left, top, right, bottom = box
    colors = ["#d7d7d7", "#f2f2f2"]
    for y in range(top, bottom, size):
        for x in range(left, right, size):
            color = colors[((x - left) // size + (y - top) // size) % 2]
            draw.rectangle((x, y, min(x + size - 1, right), min(y + size - 1, bottom)), fill=color)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlas")
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--scale", type=int, default=1)
    args = parser.parse_args()

    request = load_request(Path(args.request).expanduser().resolve())
    atlas_spec, animations = specs(request)
    scale = max(1, args.scale)
    label_width = max(160, atlas_spec["cell_width"])
    label_height = 24
    width = label_width + atlas_spec["columns"] * atlas_spec["cell_width"] * scale
    height = len(animations) * (atlas_spec["cell_height"] * scale + label_height)
    sheet = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    with Image.open(Path(args.atlas).expanduser().resolve()) as opened:
        atlas = opened.convert("RGBA")
    for row_index, animation in enumerate(animations):
        state = str(animation["name"])
        row = int(animation["row"])
        frames = int(animation["frames"])
        y = row_index * (atlas_spec["cell_height"] * scale + label_height)
        draw.rectangle((0, y, width, y + label_height - 1), fill="#ededed")
        draw.text((6, y + 6), f"{row}: {state} ({frames})", fill="#111111", font=font)
        for column in range(atlas_spec["columns"]):
            x = label_width + column * atlas_spec["cell_width"] * scale
            draw_checker(draw, (x, y + label_height, x + atlas_spec["cell_width"] * scale, y + label_height + atlas_spec["cell_height"] * scale))
            left = column * atlas_spec["cell_width"]
            top = row * atlas_spec["cell_height"]
            cell = atlas.crop((left, top, left + atlas_spec["cell_width"], top + atlas_spec["cell_height"]))
            if scale != 1:
                cell = cell.resize((atlas_spec["cell_width"] * scale, atlas_spec["cell_height"] * scale), Image.Resampling.NEAREST)
            sheet.alpha_composite(cell, (x, y + label_height))
            outline = "#111111" if column < frames else "#bbbbbb"
            draw.rectangle((x, y + label_height, x + atlas_spec["cell_width"] * scale - 1, y + label_height + atlas_spec["cell_height"] * scale - 1), outline=outline)
            draw.text((x + 3, y + label_height + 3), str(column), fill="#111111", font=font)

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(output)
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
