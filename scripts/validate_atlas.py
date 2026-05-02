#!/usr/bin/env python3
"""Validate a configurable character spritesheet atlas."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image


def alpha_nonzero_count(image: Image.Image) -> int:
    alpha = image.getchannel("A")
    return sum(alpha.histogram()[1:])


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
    atlas["width"] = int(atlas_raw.get("width", atlas["columns"] * atlas["cell_width"]))
    atlas["height"] = int(atlas_raw.get("height", atlas["rows"] * atlas["cell_height"]))
    animations_raw = request.get("animations")
    if not isinstance(animations_raw, list):
        raise SystemExit("request missing animations")
    animations = [item for item in animations_raw if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("frames"), int) and isinstance(item.get("row"), int)]
    return atlas, sorted(animations, key=lambda item: int(item["row"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlas")
    parser.add_argument("--request", required=True, help="Path to character_request.json")
    parser.add_argument("--json-out")
    parser.add_argument("--min-used-pixels", type=int, default=50)
    parser.add_argument("--near-opaque-threshold", type=float, default=0.95)
    parser.add_argument("--allow-opaque", action="store_true")
    parser.add_argument("--allow-near-opaque-used-cells", action="store_true")
    args = parser.parse_args()

    request = load_request(Path(args.request).expanduser().resolve())
    atlas_spec, animations = specs(request)
    by_row = {int(animation["row"]): animation for animation in animations}
    atlas_path = Path(args.atlas).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    near_opaque_used_cells: dict[str, list[int]] = defaultdict(list)
    cells: list[dict[str, Any]] = []
    try:
        with Image.open(atlas_path) as opened:
            source_mode = opened.mode
            source_format = opened.format
            image = opened.convert("RGBA")
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "errors": [f"could not open atlas: {exc}"], "warnings": []}
        print(json.dumps(result, indent=2))
        raise SystemExit(1)

    if image.size != (atlas_spec["width"], atlas_spec["height"]):
        errors.append(f"expected {atlas_spec['width']}x{atlas_spec['height']}, got {image.width}x{image.height}")
    if source_format not in {"PNG", "WEBP"}:
        errors.append(f"expected PNG or WebP, got {source_format}")
    if "A" not in source_mode and not args.allow_opaque:
        errors.append("atlas does not have an alpha channel")

    cell_width = atlas_spec["cell_width"]
    cell_height = atlas_spec["cell_height"]
    for row_index in range(atlas_spec["rows"]):
        animation = by_row.get(row_index)
        state = str(animation.get("name")) if animation else f"row-{row_index}"
        frame_count = int(animation.get("frames")) if animation else 0
        for column_index in range(atlas_spec["columns"]):
            left = column_index * cell_width
            top = row_index * cell_height
            cell = image.crop((left, top, left + cell_width, top + cell_height))
            nontransparent = alpha_nonzero_count(cell)
            used = column_index < frame_count
            cell_info = {"state": state, "row": row_index, "column": column_index, "used": used, "nontransparent_pixels": nontransparent}
            cells.append(cell_info)
            if used and nontransparent < args.min_used_pixels:
                errors.append(f"{state} row {row_index} column {column_index} is empty or too sparse ({nontransparent} pixels)")
            if used and nontransparent > cell_width * cell_height * args.near_opaque_threshold:
                near_opaque_used_cells[f"{state} row {row_index}"].append(column_index)
            if not used and nontransparent != 0:
                errors.append(f"{state} row {row_index} unused column {column_index} is not transparent ({nontransparent} pixels)")

    for row_label, columns in near_opaque_used_cells.items():
        message = f"{row_label} has {len(columns)} nearly opaque used cells; this usually means the sprite has a non-transparent background"
        if args.allow_near_opaque_used_cells:
            warnings.append(message)
        else:
            errors.append(message)
    alpha_count = alpha_nonzero_count(image)
    if alpha_count == atlas_spec["width"] * atlas_spec["height"]:
        message = "atlas is fully opaque; game sprites usually need a transparent background"
        if args.allow_opaque:
            warnings.append(message)
        else:
            errors.append(message)

    result = {"ok": not errors, "file": str(atlas_path), "format": source_format, "mode": source_mode, "width": image.width, "height": image.height, "errors": errors, "warnings": warnings, "cells": cells}
    if args.json_out:
        Path(args.json_out).expanduser().resolve().write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cells"}, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
