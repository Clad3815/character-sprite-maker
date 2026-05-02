#!/usr/bin/env python3
"""Compose or normalize a configurable character spritesheet atlas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image

IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def image_files(path: Path) -> list[Path]:
    return sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def load_request(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"request file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return sum((left[index] - right[index]) ** 2 for index in range(3)) ** 0.5


def load_chroma_key(request: dict[str, Any]) -> tuple[int, int, int] | None:
    chroma_key = request.get("chroma_key")
    if not isinstance(chroma_key, dict):
        return None
    rgb = chroma_key.get("rgb")
    if isinstance(rgb, list) and len(rgb) == 3 and all(isinstance(value, int) for value in rgb):
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    raw_hex = chroma_key.get("hex")
    if isinstance(raw_hex, str) and len(raw_hex) == 7 and raw_hex.startswith("#"):
        return tuple(int(raw_hex[index:index + 2], 16) for index in (1, 3, 5))
    return None


def iter_rgba_pixels(image: Image.Image):
    data = image.convert("RGBA").tobytes()
    for index in range(0, len(data), 4):
        yield data[index], data[index + 1], data[index + 2], data[index + 3]


def scrub_hidden_rgb(image: Image.Image, alpha_threshold: int = 0) -> Image.Image:
    rgba = image.convert("RGBA")
    cleaned = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    cleaned.putdata([
        (0, 0, 0, 0) if alpha <= alpha_threshold else (red, green, blue, alpha)
        for red, green, blue, alpha in iter_rgba_pixels(rgba)
    ])
    return cleaned


def scrub_chroma_key_leaks(image: Image.Image, chroma_key: tuple[int, int, int] | None, threshold: float = 32.0) -> Image.Image:
    rgba = image.convert("RGBA")
    if chroma_key is None:
        return scrub_hidden_rgb(rgba)
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha > 0 and color_distance((red, green, blue), chroma_key) <= threshold:
                pixels[x, y] = (0, 0, 0, 0)
    return scrub_hidden_rgb(rgba)


def resize_rgba_alpha_safe(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    rgba = scrub_hidden_rgb(image)
    if rgba.size == size:
        return rgba

    premultiplied = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    premultiplied.putdata([
        (
            round(red * alpha / 255),
            round(green * alpha / 255),
            round(blue * alpha / 255),
            alpha,
        )
        for red, green, blue, alpha in iter_rgba_pixels(rgba)
    ])
    resized = premultiplied.resize(size, Image.Resampling.LANCZOS)
    unpremultiplied = Image.new("RGBA", resized.size, (0, 0, 0, 0))
    pixels = []
    for red, green, blue, alpha in iter_rgba_pixels(resized):
        if alpha <= 0:
            pixels.append((0, 0, 0, 0))
        else:
            pixels.append((
                min(255, round(red * 255 / alpha)),
                min(255, round(green * 255 / alpha)),
                min(255, round(blue * 255 / alpha)),
                alpha,
            ))
    unpremultiplied.putdata(pixels)
    return scrub_hidden_rgb(unpremultiplied)


def request_from_frames_root(frames_root: Path) -> dict[str, Any]:
    candidates = [frames_root.parent / "character_request.json", frames_root / "../character_request.json"]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.is_file():
            return load_request(candidate)
    raise SystemExit("could not find character_request.json beside frames root; pass --request")


def specs_from_request(request: dict[str, Any]) -> tuple[dict[str, int], list[dict[str, Any]]]:
    atlas_raw = request.get("atlas")
    if not isinstance(atlas_raw, dict):
        raise SystemExit("request is missing atlas")
    atlas = {
        "columns": int(atlas_raw.get("columns", 0)),
        "rows": int(atlas_raw.get("rows", 0)),
        "cell_width": int(atlas_raw.get("cell_width", 0)),
        "cell_height": int(atlas_raw.get("cell_height", 0)),
    }
    atlas["width"] = int(atlas_raw.get("width", atlas["columns"] * atlas["cell_width"]))
    atlas["height"] = int(atlas_raw.get("height", atlas["rows"] * atlas["cell_height"]))
    if min(atlas.values()) <= 0:
        raise SystemExit("invalid atlas dimensions in request")
    animations_raw = request.get("animations")
    if not isinstance(animations_raw, list):
        raise SystemExit("request is missing animations")
    animations = []
    for item in animations_raw:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("frames"), int) and isinstance(item.get("row"), int):
            animations.append(item)
    if not animations:
        raise SystemExit("request contains no valid animations")
    return atlas, sorted(animations, key=lambda item: int(item["row"]))


def find_row_frames(root: Path, state: str, row_index: int) -> list[Path]:
    candidates = [root / state, root / f"row-{row_index}", root / f"row{row_index}", root / f"{row_index}-{state}"]
    for candidate in candidates:
        if candidate.is_dir():
            files = image_files(candidate)
            if files:
                return files
    files: list[Path] = []
    for pattern in [f"{state}_*", f"{state}-*", f"row{row_index}_*", f"row-{row_index}-*"]:
        files.extend(p for p in root.glob(pattern) if p.suffix.lower() in IMAGE_SUFFIXES)
    return sorted(set(files))


def paste_centered(atlas_image: Image.Image, source: Image.Image, row: int, column: int, cell_width: int, cell_height: int) -> None:
    frame = scrub_hidden_rgb(source)
    if frame.size != (cell_width, cell_height):
        scale = min(cell_width / frame.width, cell_height / frame.height)
        frame = resize_rgba_alpha_safe(frame, (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))))
    left = column * cell_width + (cell_width - frame.width) // 2
    top = row * cell_height + (cell_height - frame.height) // 2
    atlas_image.alpha_composite(frame, (left, top))


def compose_from_source_atlas(path: Path, atlas: dict[str, int], animations: list[dict[str, Any]], resize_source: bool, chroma_key: tuple[int, int, int] | None) -> Image.Image:
    with Image.open(path) as opened:
        source = opened.convert("RGBA")
    target_size = (atlas["width"], atlas["height"])
    if source.size != target_size:
        if not resize_source:
            raise SystemExit(f"source atlas must be {target_size[0]}x{target_size[1]}; got {source.width}x{source.height}")
        source_ratio = source.width / source.height
        target_ratio = target_size[0] / target_size[1]
        if abs(source_ratio - target_ratio) > 0.02:
            raise SystemExit(f"refusing to resize source atlas because aspect ratio does not match target {target_ratio:.3f}; got {source_ratio:.3f}")
        source = resize_rgba_alpha_safe(source, target_size)
    else:
        source = scrub_chroma_key_leaks(source, chroma_key)
    atlas_image = Image.new("RGBA", target_size, (0, 0, 0, 0))
    cell_width = atlas["cell_width"]
    cell_height = atlas["cell_height"]
    for spec in animations:
        row = int(spec["row"])
        for column in range(int(spec["frames"])):
            left = column * cell_width
            top = row * cell_height
            cell = source.crop((left, top, left + cell_width, top + cell_height))
            atlas_image.alpha_composite(scrub_chroma_key_leaks(cell, chroma_key), (left, top))
    return scrub_chroma_key_leaks(atlas_image, chroma_key)


def compose_from_frames(root: Path, atlas: dict[str, int], animations: list[dict[str, Any]], chroma_key: tuple[int, int, int] | None) -> Image.Image:
    atlas_image = Image.new("RGBA", (atlas["width"], atlas["height"]), (0, 0, 0, 0))
    cell_width = atlas["cell_width"]
    cell_height = atlas["cell_height"]
    for spec in animations:
        state = str(spec["name"])
        row = int(spec["row"])
        frame_count = int(spec["frames"])
        files = find_row_frames(root, state, row)
        if len(files) < frame_count:
            raise SystemExit(f"{state} row needs {frame_count} frames, found {len(files)} under {root}")
        for column, frame_path in enumerate(files[:frame_count]):
            with Image.open(frame_path) as frame:
                paste_centered(atlas_image, frame, row, column, cell_width, cell_height)
    return scrub_chroma_key_leaks(atlas_image, chroma_key)


def save_outputs(atlas_image: Image.Image, output: Path, webp_output: Path | None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    atlas_image = scrub_hidden_rgb(atlas_image)
    atlas_image.save(output)
    if webp_output is not None:
        webp_output.parent.mkdir(parents=True, exist_ok=True)
        atlas_image.save(webp_output, format="WEBP", lossless=True, quality=100, method=6)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-atlas")
    source.add_argument("--frames-root")
    parser.add_argument("--request", default="", help="Path to character_request.json. Inferred from frames root when omitted.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--webp-output")
    parser.add_argument("--resize-source", action="store_true")
    args = parser.parse_args()

    request = load_request(Path(args.request).expanduser().resolve()) if args.request else request_from_frames_root(Path(args.frames_root).expanduser().resolve()) if args.frames_root else load_request(Path(args.source_atlas).expanduser().resolve().parent.parent / "character_request.json")
    atlas, animations = specs_from_request(request)
    chroma_key = load_chroma_key(request)
    if args.source_atlas:
        atlas_image = compose_from_source_atlas(Path(args.source_atlas).expanduser().resolve(), atlas, animations, args.resize_source, chroma_key)
    else:
        atlas_image = compose_from_frames(Path(args.frames_root).expanduser().resolve(), atlas, animations, chroma_key)
    save_outputs(atlas_image, Path(args.output).expanduser().resolve(), Path(args.webp_output).expanduser().resolve() if args.webp_output else None)
    print(f"wrote {Path(args.output).expanduser().resolve()}")
    if args.webp_output:
        print(f"wrote {Path(args.webp_output).expanduser().resolve()}")


if __name__ == "__main__":
    main()
