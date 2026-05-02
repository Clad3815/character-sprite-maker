#!/usr/bin/env python3
"""Normalize a generated chroma-key sprite source into an alpha PNG.

This is a deterministic post-processing step for $imagegen outputs whose visual
background is removable but not an exact flat RGB chroma key. The normalized
output is intended to be passed to record_imagegen_result.py.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from statistics import median
from typing import Any

from PIL import Image, ImageFilter


Color = tuple[int, int, int]


def parse_hex_color(value: str) -> Color:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise SystemExit(f"invalid color {value!r}; expected #RRGGBB")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def load_request(run_dir: Path) -> dict[str, Any]:
    request_path = run_dir / "character_request.json"
    if not request_path.is_file():
        raise SystemExit(f"character_request.json not found: {request_path}")
    return json.loads(request_path.read_text(encoding="utf-8"))


def load_chroma_key(run_dir: Path, override: str) -> Color:
    if override:
        return parse_hex_color(override)
    request = load_request(run_dir)
    chroma_key = request.get("chroma_key")
    if isinstance(chroma_key, dict):
        rgb = chroma_key.get("rgb")
        if isinstance(rgb, list) and len(rgb) == 3 and all(isinstance(value, int) for value in rgb):
            return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        raw_hex = chroma_key.get("hex")
        if isinstance(raw_hex, str):
            return parse_hex_color(raw_hex)
    return parse_hex_color("#FF00FF")


def channel_distance(left: Color, right: Color) -> int:
    return max(abs(left[0] - right[0]), abs(left[1] - right[1]), abs(left[2] - right[2]))


def iter_rgba_pixels(image: Image.Image):
    data = image.convert("RGBA").tobytes()
    for index in range(0, len(data), 4):
        yield data[index], data[index + 1], data[index + 2], data[index + 3]


def clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def soft_alpha(distance: int, transparent_threshold: float, opaque_threshold: float) -> int:
    if distance <= transparent_threshold:
        return 0
    if distance >= opaque_threshold:
        return 255
    ratio = (float(distance) - transparent_threshold) / (opaque_threshold - transparent_threshold)
    return clamp(255.0 * smoothstep(ratio))


def spill_channels(key: Color) -> list[int]:
    key_max = max(key)
    if key_max < 128:
        return []
    return [idx for idx, value in enumerate(key) if value >= key_max - 16 and value >= 128]


def key_channel_dominance(rgb: Color, key: Color) -> float:
    spill = spill_channels(key)
    if not spill:
        return 0.0
    channels = [float(value) for value in rgb]
    non_spill = [idx for idx in range(3) if idx not in spill]
    key_strength = min(channels[idx] for idx in spill) if len(spill) > 1 else channels[spill[0]]
    non_key_strength = max((channels[idx] for idx in non_spill), default=0.0)
    return key_strength - non_key_strength


def dominance_alpha(rgb: Color, key: Color) -> int:
    spill = spill_channels(key)
    if not spill:
        return 255

    channels = [float(value) for value in rgb]
    non_spill = [idx for idx in range(3) if idx not in spill]
    key_strength = min(channels[idx] for idx in spill) if len(spill) > 1 else channels[spill[0]]
    non_key_strength = max((channels[idx] for idx in non_spill), default=0.0)
    dominance = key_strength - non_key_strength
    if dominance <= 0:
        return 255

    denominator = max(1.0, float(max(key)) - non_key_strength)
    alpha = 1.0 - min(1.0, dominance / denominator)
    return clamp(alpha * 255.0)


def looks_key_colored(rgb: Color, key: Color, distance: int) -> bool:
    return distance <= 32 or key_channel_dominance(rgb, key) >= 16.0


def cleanup_spill(rgb: Color, key: Color, alpha: int) -> Color:
    if alpha >= 252:
        return rgb
    spill = spill_channels(key)
    if not spill:
        return rgb
    channels = [float(value) for value in rgb]
    non_spill = [idx for idx in range(3) if idx not in spill]
    if non_spill:
        cap = max(0.0, max(channels[idx] for idx in non_spill) - 1.0)
        for idx in spill:
            channels[idx] = min(channels[idx], cap)
    return (clamp(channels[0]), clamp(channels[1]), clamp(channels[2]))


def sample_border_key(image: Image.Image, mode: str, fallback: Color) -> Color:
    if mode == "none":
        return fallback
    rgba = image.convert("RGBA")
    width, height = rgba.size
    samples: list[Color] = []
    pixels = rgba.load()

    if mode == "corners":
        patch = max(1, min(width, height, 12))
        boxes = [
            (0, 0, patch, patch),
            (width - patch, 0, width, patch),
            (0, height - patch, patch, height),
            (width - patch, height - patch, width, height),
        ]
        for left, top, right, bottom in boxes:
            for y in range(top, bottom):
                for x in range(left, right):
                    red, green, blue = pixels[x, y][:3]
                    samples.append((red, green, blue))
    else:
        band = max(1, min(width, height, 6))
        step = max(1, min(width, height) // 256)
        for x in range(0, width, step):
            for y in range(band):
                red, green, blue = pixels[x, y][:3]
                samples.append((red, green, blue))
                red, green, blue = pixels[x, height - 1 - y][:3]
                samples.append((red, green, blue))
        for y in range(0, height, step):
            for x in range(band):
                red, green, blue = pixels[x, y][:3]
                samples.append((red, green, blue))
                red, green, blue = pixels[width - 1 - x, y][:3]
                samples.append((red, green, blue))

    if not samples:
        return fallback
    return (
        int(round(median(sample[0] for sample in samples))),
        int(round(median(sample[1] for sample in samples))),
        int(round(median(sample[2] for sample in samples))),
    )


def transparent_edge_ratio(image: Image.Image) -> float:
    rgba = image.convert("RGBA")
    border = max(4, min(16, min(rgba.size) // 32))
    total = 0
    transparent = 0
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            if x >= border and x < rgba.width - border and y >= border and y < rgba.height - border:
                continue
            total += 1
            if pixels[x, y][3] <= 16:
                transparent += 1
    return transparent / total if total else 0.0


def normalize_image(source: Path, output: Path, key: Color, *, auto_key: str, transparent_threshold: float, opaque_threshold: float, edge_contract: int) -> dict[str, Any]:
    with Image.open(source) as opened:
        rgba = opened.convert("RGBA")
    sampled_key = sample_border_key(rgba, auto_key, key)
    pixels = rgba.load()
    transparent_before = 0
    partial_before = 0
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, alpha = pixels[x, y]
            rgb = (red, green, blue)
            distance = channel_distance(rgb, sampled_key)
            if looks_key_colored(rgb, sampled_key, distance):
                alpha = int(round(
                    min(
                        soft_alpha(distance, transparent_threshold, opaque_threshold),
                        dominance_alpha(rgb, sampled_key),
                    )
                    * (alpha / 255.0)
                ))
                red, green, blue = cleanup_spill(rgb, sampled_key, alpha)
            if alpha <= 8:
                alpha = 0
            if alpha == 0:
                red, green, blue = 0, 0, 0
                transparent_before += 1
            elif alpha < 255:
                partial_before += 1
            pixels[x, y] = (red, green, blue, alpha)

    if edge_contract:
        alpha = rgba.getchannel("A").filter(ImageFilter.MinFilter(edge_contract * 2 + 1))
        rgba.putalpha(alpha)
        rgba = rgba.convert("RGBA")

    rgba.putdata([
        (0, 0, 0, 0) if alpha <= 0 else (red, green, blue, alpha)
        for red, green, blue, alpha in iter_rgba_pixels(rgba)
    ])
    output.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(output)
    return {
        "source": str(source),
        "output": str(output),
        "request_chroma_key": list(key),
        "sampled_key": list(sampled_key),
        "transparent_pixels": transparent_before,
        "partial_pixels": partial_before,
        "transparent_edge_ratio": round(transparent_edge_ratio(rgba), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--key-color", default="")
    parser.add_argument("--auto-key", choices=["none", "corners", "border"], default="border")
    parser.add_argument("--transparent-threshold", type=float, default=18.0)
    parser.add_argument("--opaque-threshold", type=float, default=120.0)
    parser.add_argument("--edge-contract", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    source = Path(args.source).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"source image not found: {source}")
    if output.exists() and not args.force:
        raise SystemExit(f"output already exists: {output}; pass --force to replace it")
    if args.transparent_threshold >= args.opaque_threshold:
        raise SystemExit("--transparent-threshold must be lower than --opaque-threshold")
    if args.edge_contract < 0 or args.edge_contract > 16:
        raise SystemExit("--edge-contract must be between 0 and 16")

    key = load_chroma_key(run_dir, args.key_color)
    result = normalize_image(
        source,
        output,
        key,
        auto_key=args.auto_key,
        transparent_threshold=args.transparent_threshold,
        opaque_threshold=args.opaque_threshold,
        edge_contract=args.edge_contract,
    )
    print(json.dumps({"ok": True, **result}, indent=2))


if __name__ == "__main__":
    main()
