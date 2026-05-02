#!/usr/bin/env python3
"""Extract generated horizontal animation strips into transparent sprite frames."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image

IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise SystemExit(f"invalid chroma key color: {value}; expected #RRGGBB")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def color_distance(red: int, green: int, blue: int, key: tuple[int, int, int]) -> float:
    return math.sqrt((red - key[0]) ** 2 + (green - key[1]) ** 2 + (blue - key[2]) ** 2)


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


def scrub_chroma_key_leaks(image: Image.Image, chroma_key: tuple[int, int, int], threshold: float) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha > 0 and color_distance(red, green, blue, chroma_key) <= threshold:
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


def request_path_from_decoded(decoded_dir: Path) -> Path:
    return decoded_dir.parent / "character_request.json"


def load_request(decoded_dir: Path) -> dict[str, Any]:
    request_path = request_path_from_decoded(decoded_dir)
    if not request_path.is_file():
        raise SystemExit(f"character_request.json not found beside decoded dir: {request_path}")
    return json.loads(request_path.read_text(encoding="utf-8"))


def animation_specs(request: dict[str, Any]) -> list[dict[str, Any]]:
    animations = request.get("animations")
    if not isinstance(animations, list) or not animations:
        raise SystemExit("character_request.json has no animations list")
    specs: list[dict[str, Any]] = []
    for item in animations:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        frames = item.get("frames")
        row = item.get("row")
        if isinstance(name, str) and isinstance(frames, int) and isinstance(row, int):
            specs.append(item)
    if not specs:
        raise SystemExit("character_request.json contains no valid animations")
    return sorted(specs, key=lambda item: int(item["row"]))


def parse_states(raw: str, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if raw.strip().lower() == "all":
        return specs
    wanted = [item.strip() for item in raw.split(",") if item.strip()]
    by_name = {str(spec["name"]): spec for spec in specs}
    unknown = sorted(set(wanted) - set(by_name))
    if unknown:
        raise SystemExit(f"unknown animation(s): {', '.join(unknown)}")
    return [by_name[name] for name in wanted]


def load_chroma_key(request: dict[str, Any], override: str | None) -> tuple[int, int, int]:
    if override:
        return parse_hex_color(override)
    chroma_key = request.get("chroma_key")
    if isinstance(chroma_key, dict) and isinstance(chroma_key.get("hex"), str):
        return parse_hex_color(chroma_key["hex"])
    return parse_hex_color("#FF00FF")


def remove_chroma_background(image: Image.Image, chroma_key: tuple[int, int, int], threshold: float) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            if color_distance(red, green, blue, chroma_key) <= threshold:
                pixels[x, y] = (red, green, blue, 0)
    return scrub_hidden_rgb(rgba)


def fit_to_cell(image: Image.Image, cell_width: int, cell_height: int) -> Image.Image:
    bbox = image.getbbox()
    target = Image.new("RGBA", (cell_width, cell_height), (0, 0, 0, 0))
    if bbox is None:
        return target
    sprite = image.crop(bbox)
    max_width = cell_width - max(2, min(10, cell_width // 16))
    max_height = cell_height - max(2, min(10, cell_height // 16))
    scale = min(max_width / sprite.width, max_height / sprite.height, 1.0)
    if scale != 1.0:
        sprite = resize_rgba_alpha_safe(sprite, (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))))
    else:
        sprite = scrub_hidden_rgb(sprite)
    left = (cell_width - sprite.width) // 2
    top = (cell_height - sprite.height) // 2
    target.alpha_composite(sprite, (left, top))
    return scrub_hidden_rgb(target)


def connected_components(image: Image.Image) -> list[dict[str, Any]]:
    alpha = image.getchannel("A")
    width, height = image.size
    data = alpha.tobytes()
    visited = bytearray(width * height)
    components: list[dict[str, Any]] = []
    for start, alpha_value in enumerate(data):
        if alpha_value <= 16 or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        pixels: list[int] = []
        min_x = width
        min_y = height
        max_x = 0
        max_y = 0
        while stack:
            current = stack.pop()
            pixels.append(current)
            x = current % width
            y = current // width
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            if x > 0:
                neighbor = current - 1
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if x + 1 < width:
                neighbor = current + 1
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if y > 0:
                neighbor = current - width
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if y + 1 < height:
                neighbor = current + width
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
        components.append({"pixels": pixels, "area": len(pixels), "bbox": (min_x, min_y, max_x + 1, max_y + 1), "center_x": (min_x + max_x + 1) / 2})
    return components


def component_group_image(source: Image.Image, components: list[dict[str, Any]], padding: int = 4) -> Image.Image:
    width, height = source.size
    min_x = max(0, min(component["bbox"][0] for component in components) - padding)
    min_y = max(0, min(component["bbox"][1] for component in components) - padding)
    max_x = min(width, max(component["bbox"][2] for component in components) + padding)
    max_y = min(height, max(component["bbox"][3] for component in components) + padding)
    output = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
    source_pixels = source.load()
    output_pixels = output.load()
    for component in components:
        for pixel_index in component["pixels"]:
            x = pixel_index % width
            y = pixel_index // width
            output_pixels[x - min_x, y - min_y] = source_pixels[x, y]
    return output


def extract_component_frames(strip: Image.Image, frame_count: int, cell_width: int, cell_height: int) -> list[Image.Image] | None:
    components = connected_components(strip)
    if not components:
        return None
    largest_area = max(component["area"] for component in components)
    seed_threshold = max(80, largest_area * 0.20)
    seeds = [component for component in components if component["area"] >= seed_threshold]
    if len(seeds) < frame_count:
        seeds = sorted(components, key=lambda component: component["area"], reverse=True)[:frame_count]
    if len(seeds) < frame_count:
        return None
    seeds = sorted(sorted(seeds, key=lambda component: component["area"], reverse=True)[:frame_count], key=lambda component: component["center_x"])
    seed_ids = {id(seed) for seed in seeds}
    groups: list[list[dict[str, Any]]] = [[seed] for seed in seeds]
    noise_threshold = max(8, largest_area * 0.002)
    for component in components:
        if id(component) in seed_ids or component["area"] < noise_threshold:
            continue
        nearest_index = min(range(len(seeds)), key=lambda idx: abs(seeds[idx]["center_x"] - component["center_x"]))
        groups[nearest_index].append(component)
    return [fit_to_cell(component_group_image(strip, group), cell_width, cell_height) for group in groups]


def extract_slot_frames(strip: Image.Image, frame_count: int, cell_width: int, cell_height: int) -> list[Image.Image]:
    slot_width = strip.width / frame_count
    frames = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        crop = strip.crop((left, 0, right, strip.height))
        frames.append(fit_to_cell(crop, cell_width, cell_height))
    return frames


def extract_state(strip_path: Path, spec: dict[str, Any], output_root: Path, chroma_key: tuple[int, int, int], threshold: float, method: str, cell_width: int, cell_height: int) -> dict[str, Any]:
    state = str(spec["name"])
    frame_count = int(spec["frames"])
    with Image.open(strip_path) as opened:
        strip = remove_chroma_background(opened, chroma_key, threshold)
    state_dir = output_root / state
    state_dir.mkdir(parents=True, exist_ok=True)
    for old in state_dir.iterdir():
        if old.is_file() and old.suffix.lower() in IMAGE_SUFFIXES:
            old.unlink()

    frames = None
    used_method = method
    if method in {"auto", "components"}:
        frames = extract_component_frames(strip, frame_count, cell_width, cell_height)
        if frames is None and method == "components":
            raise SystemExit(f"could not find {frame_count} sprite components in {strip_path}")
        if frames is not None:
            used_method = "components"
    if frames is None:
        frames = extract_slot_frames(strip, frame_count, cell_width, cell_height)
        used_method = "slots"

    outputs = []
    for index, frame in enumerate(frames):
        out = state_dir / f"{index:02d}.png"
        frame = scrub_chroma_key_leaks(frame, chroma_key, max(threshold, 32.0))
        frame.save(out)
        outputs.append(str(out))
    return {"state": state, "row": int(spec["row"]), "frames": frame_count, "method": used_method, "strip": str(strip_path), "outputs": outputs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--states", default="all")
    parser.add_argument("--method", choices=["auto", "components", "slots"], default="auto")
    parser.add_argument("--chroma-key")
    parser.add_argument("--threshold", type=float, default=12.0)
    args = parser.parse_args()

    decoded_dir = Path(args.decoded_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    request = load_request(decoded_dir)
    atlas = request.get("atlas") if isinstance(request.get("atlas"), dict) else {}
    cell_width = int(atlas.get("cell_width", 128))
    cell_height = int(atlas.get("cell_height", 128))
    specs = animation_specs(request)
    selected = parse_states(args.states, specs)
    chroma_key = load_chroma_key(request, args.chroma_key)
    rows = []
    for spec in selected:
        state = str(spec["name"])
        strip_path = decoded_dir / f"{state}.png"
        if not strip_path.is_file():
            raise SystemExit(f"missing decoded strip for {state}: {strip_path}")
        rows.append(extract_state(strip_path, spec, output_dir, chroma_key, args.threshold, args.method, cell_width, cell_height))
    manifest = {
        "schema_version": 1,
        "frames_root": str(output_dir),
        "cell_width": cell_width,
        "cell_height": cell_height,
        "chroma_key": request.get("chroma_key"),
        "animations": request.get("animations"),
        "rows": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "frames-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "frames_root": str(output_dir), "rows": [{"state": row["state"], "frames": row["frames"], "method": row["method"]} for row in rows]}, indent=2))


if __name__ == "__main__":
    main()
