#!/usr/bin/env python3
"""Inspect extracted character animation frames before atlas composition."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from PIL import Image

IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def alpha_nonzero_count(image: Image.Image) -> int:
    alpha = image if image.mode == "L" else image.getchannel("A")
    return sum(alpha.histogram()[1:])


def edge_alpha_count(image: Image.Image, margin: int) -> int:
    alpha = image.getchannel("A")
    width, height = alpha.size
    total = 0
    for box in ((0, 0, width, margin), (0, height - margin, width, height), (0, 0, margin, height), (width - margin, 0, width, height)):
        total += alpha_nonzero_count(alpha.crop(box))
    return total


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def chroma_adjacent_count(image: Image.Image, chroma_key: tuple[int, int, int] | None, threshold: float) -> int:
    if chroma_key is None:
        return 0
    rgba = image.convert("RGBA")
    data = rgba.tobytes()
    count = 0
    for index in range(0, len(data), 4):
        red, green, blue, alpha = data[index:index + 4]
        if alpha > 16 and color_distance((red, green, blue), chroma_key) <= threshold:
            count += 1
    return count


def frame_files(state_dir: Path) -> list[Path]:
    if not state_dir.is_dir():
        return []
    return sorted(path for path in state_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)


def load_manifest(frames_root: Path) -> dict[str, Any]:
    manifest_path = frames_root / "frames-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"frames manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_chroma_key(manifest: dict[str, Any]) -> tuple[int, int, int] | None:
    chroma_key = manifest.get("chroma_key")
    if not isinstance(chroma_key, dict):
        return None
    rgb = chroma_key.get("rgb")
    if not isinstance(rgb, list) or len(rgb) != 3 or not all(isinstance(value, int) for value in rgb):
        return None
    return (rgb[0], rgb[1], rgb[2])


def manifest_rows(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = manifest.get("rows", [])
    if not isinstance(rows, list):
        return {}
    return {str(row["state"]): row for row in rows if isinstance(row, dict) and isinstance(row.get("state"), str)}


def manifest_animations(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    animations = manifest.get("animations", [])
    if not isinstance(animations, list):
        raise SystemExit("frames manifest has no animations list")
    valid = []
    for item in animations:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("frames"), int) and isinstance(item.get("row"), int):
            valid.append(item)
    return sorted(valid, key=lambda item: int(item["row"]))


def inspect_state(frames_root: Path, spec: dict[str, Any], rows_by_state: dict[str, dict[str, Any]], chroma_key: tuple[int, int, int] | None, cell_width: int, cell_height: int, args: argparse.Namespace) -> dict[str, Any]:
    state = str(spec["name"])
    expected_count = int(spec["frames"])
    state_dir = frames_root / state
    files = frame_files(state_dir)
    row_errors: list[str] = []
    row_warnings: list[str] = []
    frames: list[dict[str, Any]] = []
    areas: list[int] = []
    manifest_row = rows_by_state.get(state, {})
    method = manifest_row.get("method")

    if len(files) != expected_count:
        row_errors.append(f"expected {expected_count} frame files for {state}, found {len(files)}")
    if args.require_components and method and method != "components":
        row_errors.append(f"{state} used extraction method {method}; regenerate the row or inspect slot slicing")
    elif method and method != "components":
        row_warnings.append(f"{state} used extraction method {method}; component extraction is preferred")

    for index, frame_path in enumerate(files[:expected_count]):
        with Image.open(frame_path) as opened:
            frame = opened.convert("RGBA")
        nontransparent = alpha_nonzero_count(frame)
        bbox = frame.getbbox()
        edge_pixels = edge_alpha_count(frame, args.edge_margin)
        chroma_adjacent_pixels = chroma_adjacent_count(frame, chroma_key, args.chroma_adjacent_threshold)
        info = {
            "index": index,
            "file": str(frame_path),
            "width": frame.width,
            "height": frame.height,
            "nontransparent_pixels": nontransparent,
            "bbox": list(bbox) if bbox else None,
            "edge_pixels": edge_pixels,
            "chroma_adjacent_pixels": chroma_adjacent_pixels,
        }
        frames.append(info)
        areas.append(nontransparent)
        if frame.size != (cell_width, cell_height):
            row_errors.append(f"{state} frame {index:02d} is {frame.width}x{frame.height}; expected {cell_width}x{cell_height}")
        if nontransparent < args.min_used_pixels:
            row_errors.append(f"{state} frame {index:02d} is empty or too sparse ({nontransparent} pixels)")
        if edge_pixels > args.edge_pixel_threshold:
            row_warnings.append(f"{state} frame {index:02d} has {edge_pixels} non-transparent pixels near the cell edge")
        if chroma_adjacent_pixels > args.chroma_adjacent_pixel_threshold:
            row_errors.append(f"{state} frame {index:02d} has {chroma_adjacent_pixels} non-transparent pixels close to the chroma key")

    if areas:
        row_median = median(areas)
        for index, area in enumerate(areas[:expected_count]):
            if row_median > 0 and area < row_median * args.small_outlier_ratio:
                row_warnings.append(f"{state} frame {index:02d} is much smaller than the row median ({area} vs {row_median:.0f})")
            if row_median > 0 and area > row_median * args.large_outlier_ratio:
                row_warnings.append(f"{state} frame {index:02d} is much larger than the row median ({area} vs {row_median:.0f})")

    return {"state": state, "row": int(spec["row"]), "expected_frames": expected_count, "actual_frames": len(files), "extraction_method": method, "ok": not row_errors, "errors": row_errors, "warnings": row_warnings, "frames": frames}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-root", required=True)
    parser.add_argument("--json-out", required=True)
    parser.add_argument("--min-used-pixels", type=int, default=80)
    parser.add_argument("--edge-margin", type=int, default=2)
    parser.add_argument("--edge-pixel-threshold", type=int, default=24)
    parser.add_argument("--chroma-adjacent-threshold", type=float, default=150.0)
    parser.add_argument("--chroma-adjacent-pixel-threshold", type=int, default=800)
    parser.add_argument("--small-outlier-ratio", type=float, default=0.35)
    parser.add_argument("--large-outlier-ratio", type=float, default=2.75)
    parser.add_argument("--require-components", action="store_true", help="Fail rows that fell back to equal-slot extraction.")
    args = parser.parse_args()

    frames_root = Path(args.frames_root).expanduser().resolve()
    manifest = load_manifest(frames_root)
    cell_width = int(manifest.get("cell_width", 128))
    cell_height = int(manifest.get("cell_height", 128))
    chroma_key = load_chroma_key(manifest)
    rows_by_state = manifest_rows(manifest)
    animations = manifest_animations(manifest)
    rows = [inspect_state(frames_root, spec, rows_by_state, chroma_key, cell_width, cell_height, args) for spec in animations]
    errors = [error for row in rows for error in row["errors"]]
    warnings = [warning for row in rows for warning in row["warnings"]]
    result = {"ok": not errors, "frames_root": str(frames_root), "cell_width": cell_width, "cell_height": cell_height, "errors": errors, "warnings": warnings, "rows": rows}
    json_out = Path(args.json_out).expanduser().resolve()
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
