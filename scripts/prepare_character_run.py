#!/usr/bin/env python3
"""Prepare a configurable 2D character sprite generation run.

This script does not generate artwork. It creates a run folder, copies references,
chooses a chroma-key background, writes prompts, creates layout guides, and builds
an image-generation job manifest for an agent/skill to execute with $imagegen.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}
DEFAULT_CELL_WIDTH = 128
DEFAULT_CELL_HEIGHT = 128
DEFAULT_FPS = 12
DEFAULT_CHARACTER_NAME = "Hero"
CANONICAL_BASE_PATH = "references/canonical-base.png"
LAYOUT_GUIDE_DIR = "references/layout-guides"

STYLE_PRESETS: dict[str, str] = {
    "pixel-platformer": (
        "2D pixel-art platformer character sprite, side-view, readable at small size, "
        "chunky silhouette, clean 1-2 px dark outline, limited palette, flat cel shading, "
        "crisp pixel edges, no painterly details, no realistic texture, no 3D rendering"
    ),
    "mario-like": (
        "bright family-friendly 2D platformer sprite style inspired by classic mascot platform games, "
        "side-view, rounded readable shapes, bold saturated palette, clean outline, simple face, "
        "snappy poses, not a copy of any copyrighted character"
    ),
    "topdown-rpg": (
        "top-down RPG sprite style, orthographic camera, compact readable body proportions, "
        "clear directional poses, limited palette, crisp outline, flat shading, no perspective scenery"
    ),
    "metroidvania": (
        "side-view action platformer sprite style, slightly heroic proportions, strong silhouette, "
        "limited palette, crisp outline, animation-ready limb shapes, readable weapon/accessory forms"
    ),
    "fighting-game": (
        "2D fighting-game sprite style, side-view combat stance, strong readable silhouette, "
        "clean outline, dramatic but simple poses, limited palette, no painterly key art"
    ),
    "cartoon-hd": (
        "clean 2D cartoon game sprite style, vector-clean edges but raster output, bold outline, "
        "flat cel shading, readable full-body poses, no 3D render, no glossy app icon lighting"
    ),
    "iso-rpg": (
        "isometric RPG sprite style, three-quarter top view, compact readable proportions, crisp edges, "
        "limited palette, flat shading, no detailed background"
    ),
}

ANIMATION_PRESETS: dict[str, list[tuple[str, int, str]]] = {
    "platformer": [
        ("idle", 6, "neutral breathing or blink loop"),
        ("walk-right", 8, "rightward walk cycle"),
        ("walk-left", 8, "leftward walk cycle"),
        ("run-right", 8, "rightward run cycle"),
        ("run-left", 8, "leftward run cycle"),
        ("jump", 6, "anticipation, lift, airborne peak, descent, landing recovery"),
        ("fall", 4, "falling loop with body held in air"),
        ("attack", 6, "short readable attack or action cycle"),
        ("hurt", 4, "hit reaction with recoil"),
    ],
    "mario-like": [
        ("idle", 6, "friendly idle breathing and blink loop"),
        ("walk-right", 8, "rightward platformer walk cycle"),
        ("walk-left", 8, "leftward platformer walk cycle"),
        ("run-right", 8, "rightward fast run cycle"),
        ("run-left", 8, "leftward fast run cycle"),
        ("jump", 6, "squash anticipation, airborne jump, landing settle"),
        ("crouch", 4, "small crouch and hold"),
        ("attack", 6, "simple action gesture without weapon unless specified"),
        ("hurt", 4, "brief bonk or damage reaction"),
    ],
    "topdown-rpg": [
        ("idle-down", 4, "idle facing down"),
        ("walk-down", 6, "walking downward toward camera"),
        ("walk-up", 6, "walking upward away from camera"),
        ("walk-right", 6, "walking right"),
        ("walk-left", 6, "walking left"),
        ("attack-down", 6, "attack facing down"),
        ("attack-up", 6, "attack facing up"),
        ("attack-side", 6, "side attack cycle"),
    ],
    "fighting": [
        ("idle", 6, "combat idle stance"),
        ("walk-forward", 8, "walk forward in fighting-game side view"),
        ("walk-back", 8, "walk backward in fighting-game side view"),
        ("light-attack", 6, "quick light attack"),
        ("heavy-attack", 8, "larger heavy attack"),
        ("block", 4, "guard or block pose"),
        ("hurt", 4, "damage recoil"),
        ("knockdown", 8, "fall and downed recovery pose"),
    ],
    "pet-compatible": [
        ("idle", 6, "neutral breathing/blinking loop"),
        ("running-right", 8, "rightward locomotion loop"),
        ("running-left", 8, "leftward locomotion loop"),
        ("waving", 4, "greeting gesture with raised wave and return"),
        ("jumping", 5, "anticipation, lift, peak, descent, settle"),
        ("failed", 8, "sad, failed, or deflated reaction"),
        ("waiting", 6, "patient waiting loop with small motion"),
        ("running", 6, "generic in-place running loop"),
        ("review", 6, "focused inspecting or review loop"),
    ],
}

TRANSPARENCY_ARTIFACT_RULES = [
    "Use one perfectly flat chroma-key background color across the whole output; the exact RGB value is specified in the chroma-key background contract.",
    "Do not include scenery, ground, UI panels, text, frame numbers, labels, watermarks, visible guide lines, borders, checkerboard transparency, or white/black backgrounds.",
    "Do not draw detached effects such as floating stars, loose sparkles, motion arcs, speed lines, dust clouds, separated smoke, loose tears, speech bubbles, punctuation, or symbols unless the user explicitly requested them and they remain attached to the character silhouette.",
    "Avoid shadows, glows, halos, motion blur, smears, impact bursts, landing marks, and floor patches because they usually break transparent extraction.",
    "Do not use the chroma-key color, or colors close to it, inside the character, props, highlights, shadows, or effects.",
    "Every frame must contain one complete self-contained pose with safe padding. No body part may be clipped or cross into a neighboring frame slot.",
]

STATE_HINTS: dict[str, list[str]] = {
    "idle": ["Use subtle breathing, blink, or small head/hand shifts; do not redesign the character."],
    "walk": ["Show a readable alternating step cycle through legs, arms, body tilt, and props only."],
    "run": ["Show faster locomotion through pose spacing and limb motion only; no speed lines or dust."],
    "jump": ["Show anticipation, lift, airborne peak, descent, and landing settle; avoid shadows or dust."],
    "fall": ["Show a suspended falling pose loop; avoid background cues or motion streaks."],
    "attack": ["Use clear pose changes and weapon/limb motion; no detached slash effects unless explicitly requested."],
    "hurt": ["Use recoil, facial expression, and body pose; avoid floating damage icons or symbols."],
    "death": ["Use fall/collapse poses only; avoid gore unless explicitly requested and allowed."],
    "crouch": ["Keep the same identity and costume; compress the body pose only."],
    "block": ["Show a guarding pose; no shield effects unless part of the character design."],
    "waving": ["Show waving through arm or hand pose only; no wave marks or sparkles."],
}

CHROMA_KEY_CANDIDATES = [
    ("magenta", "#FF00FF"),
    ("cyan", "#00FFFF"),
    ("yellow", "#FFFF00"),
    ("blue", "#0000FF"),
    ("orange", "#FF7F00"),
    ("green", "#00FF00"),
]

@dataclass(frozen=True)
class AnimationSpec:
    name: str
    row: int
    frames: int
    action: str
    fps: int


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def display_from_slug(value: str) -> str:
    words = [word for word in re.split(r"[^a-zA-Z0-9]+", value.strip()) if word]
    return " ".join(word.capitalize() for word in words)


def concept_words(value: str) -> list[str]:
    stop_words = {
        "a", "an", "and", "character", "sprite", "game", "hero", "for", "from", "in", "of", "on",
        "style", "the", "to", "with", "2d", "pixel", "art", "platformer", "rpg", "player",
    }
    return [w.lower() for w in re.findall(r"[a-zA-Z0-9]+", value) if w.lower() not in stop_words]


def sentence(value: str) -> str:
    value = " ".join(value.strip().split())
    if value and value[-1] not in ".!?":
        value += "."
    return value


def parse_animation(raw: str, row: int, default_fps: int) -> AnimationSpec:
    # Supported forms:
    #   name
    #   name:frames
    #   name:frames:action text
    #   name=frames:action text
    raw = raw.strip()
    if not raw:
        raise SystemExit("empty --animation value")
    if "=" in raw and (":" not in raw.split("=", 1)[0]):
        name, rest = raw.split("=", 1)
        parts = [name.strip(), *rest.split(":", 1)]
    else:
        parts = raw.split(":", 2)
    name = slugify(parts[0])
    if not name:
        raise SystemExit(f"invalid animation name in {raw!r}")
    frames = 6
    action = name.replace("-", " ") + " animation cycle"
    if len(parts) >= 2 and parts[1].strip():
        try:
            frames = int(parts[1])
        except ValueError as exc:
            raise SystemExit(f"invalid frame count in --animation {raw!r}") from exc
    if len(parts) >= 3 and parts[2].strip():
        action = parts[2].strip()
    if frames < 1 or frames > 64:
        raise SystemExit(f"animation {name} frame count must be between 1 and 64")
    return AnimationSpec(name=name, row=row, frames=frames, action=action, fps=default_fps)


def preset_animations(name: str, default_fps: int) -> list[AnimationSpec]:
    key = name.strip().lower()
    if key not in ANIMATION_PRESETS:
        available = ", ".join(sorted(ANIMATION_PRESETS))
        raise SystemExit(f"unknown animation preset {name!r}; available: {available}")
    return [AnimationSpec(anim, row, frames, action, default_fps) for row, (anim, frames, action) in enumerate(ANIMATION_PRESETS[key])]


def infer_name(args: argparse.Namespace, reference_paths: list[Path]) -> str:
    for label, raw in [("display", args.display_name), ("name", args.character_name), ("id", args.character_id)]:
        value = str(raw).strip()
        if not value:
            continue
        if label == "id":
            display = display_from_slug(value)
            if display:
                return display
        else:
            return value
    for raw in [args.character_notes, args.description, args.style_notes]:
        words = concept_words(str(raw))
        if words:
            return words[0].capitalize()
    for path in reference_paths:
        display = display_from_slug(path.stem)
        if display:
            return display
    return DEFAULT_CHARACTER_NAME


def infer_description(args: argparse.Namespace, reference_paths: list[Path]) -> str:
    if args.description.strip():
        return sentence(args.description)
    if args.character_notes.strip():
        return sentence(f"A configurable 2D game character sprite: {args.character_notes}")
    if reference_paths:
        return "A configurable 2D game character sprite based on the provided reference image."
    return "A configurable original 2D game character sprite ready for animation."


def infer_character_notes(args: argparse.Namespace, reference_paths: list[Path]) -> str:
    if args.character_notes.strip():
        return args.character_notes.strip()
    if args.description.strip():
        return args.description.strip().rstrip(".")
    if reference_paths:
        return "the character shown in the reference image(s)"
    return "an original 2D game character"


def default_output_dir(character_id: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / "output" / "character-sprite-maker" / f"{character_id}-{timestamp}"


def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise SystemExit(f"invalid chroma key color: {value}; expected #RRGGBB")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[i] - right[i]) ** 2 for i in range(3)))


def sampled_reference_pixels(paths: list[Path]) -> list[tuple[int, int, int]]:
    pixels: list[tuple[int, int, int]] = []
    for path in paths:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
            image.thumbnail((128, 128), Image.Resampling.LANCZOS)
            data = image.tobytes()
            for idx in range(0, len(data), 4):
                red, green, blue, alpha = data[idx:idx + 4]
                if alpha <= 16:
                    continue
                pixels.append((red, green, blue))
    non_white = [p for p in pixels if not (p[0] > 244 and p[1] > 244 and p[2] > 244)]
    return non_white or pixels


def choose_chroma_key(reference_paths: list[Path], requested: str) -> dict[str, Any]:
    if requested.lower() != "auto":
        rgb = parse_hex_color(requested)
        return {"hex": rgb_to_hex(rgb), "rgb": list(rgb), "name": "user-selected", "selection": "manual"}

    pixels = sampled_reference_pixels(reference_paths)
    if not pixels:
        rgb = parse_hex_color("#FF00FF")
        return {"hex": "#FF00FF", "rgb": list(rgb), "name": "magenta", "selection": "fallback"}

    scored: list[tuple[float, int, str, tuple[int, int, int]]] = []
    for preference_index, (name, hex_color) in enumerate(CHROMA_KEY_CANDIDATES):
        rgb = parse_hex_color(hex_color)
        distances = sorted(color_distance(rgb, pixel) for pixel in pixels)
        percentile_index = max(0, min(len(distances) - 1, int(len(distances) * 0.01)))
        scored.append((distances[percentile_index], -preference_index, name, rgb))
    score, _pref, name, rgb = max(scored)
    return {"hex": rgb_to_hex(rgb), "rgb": list(rgb), "name": name, "selection": "auto", "score": round(score, 2)}


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        return {"path": str(path), "width": image.width, "height": image.height, "mode": image.mode, "format": image.format}


def rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def style_contract(style_preset: str, style_notes: str) -> str:
    preset = style_preset.strip().lower() or "pixel-platformer"
    if preset not in STYLE_PRESETS:
        available = ", ".join(sorted(STYLE_PRESETS))
        raise SystemExit(f"unknown style preset {style_preset!r}; available: {available}")
    base = STYLE_PRESETS[preset]
    if style_notes.strip():
        return f"{base}. Additional user style notes: {style_notes.strip()}"
    return base


def chroma_background_contract(chroma_key: dict[str, Any]) -> str:
    chroma_hex = chroma_key["hex"]
    chroma_name = chroma_key["name"]
    return f"""Chroma-key background contract:
- The canvas background outside the sprite must be the exact solid color {chroma_hex} ({chroma_name}) from edge to edge.
- Every non-character background pixel must use that same RGB value. No gradients, vignettes, texture, shadows, glows, floor plane, anti-aliased haze, lighting variation, or alternate background hue.
- Keep a clean uninterrupted {chroma_hex} border around the whole image so automated background auditing can verify the key color.
- If the style lighting conflicts with a flat background, simplify the lighting on the sprite instead of changing, shading, or decorating the background."""


def draw_dashed_line(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], *, fill: str, dash: int = 8, gap: int = 6) -> None:
    x1, y1 = start
    x2, y2 = end
    if x1 == x2:
        for y in range(min(y1, y2), max(y1, y2), dash + gap):
            draw.line((x1, y, x2, min(y + dash, max(y1, y2))), fill=fill)
        return
    if y1 == y2:
        for x in range(min(x1, x2), max(x1, x2), dash + gap):
            draw.line((x, y1, min(x + dash, max(x1, x2)), y2), fill=fill)
        return
    raise ValueError("draw_dashed_line only supports horizontal or vertical lines")


def create_layout_guide(path: Path, animation: AnimationSpec, cell_width: int, cell_height: int, margin_x: int, margin_y: int) -> dict[str, Any]:
    width = animation.frames * cell_width
    height = cell_height
    image = Image.new("RGB", (width, height), "#f7f7f7")
    draw = ImageDraw.Draw(image)
    for index in range(animation.frames):
        left = index * cell_width
        right = left + cell_width - 1
        draw.rectangle((left, 0, right, height - 1), outline="#111111", width=2)
        safe_left = left + margin_x
        safe_top = margin_y
        safe_right = right - margin_x
        safe_bottom = height - 1 - margin_y
        draw.rectangle((safe_left, safe_top, safe_right, safe_bottom), outline="#2f80ed", width=2)
        center_x = left + cell_width // 2
        center_y = height // 2
        draw_dashed_line(draw, (center_x, safe_top), (center_x, safe_bottom), fill="#b8b8b8")
        draw_dashed_line(draw, (safe_left, center_y), (safe_right, center_y), fill="#b8b8b8")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return {
        "animation": animation.name,
        "path": str(path),
        "width": width,
        "height": height,
        "frames": animation.frames,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "safe_margin_x": margin_x,
        "safe_margin_y": margin_y,
        "usage": "layout guide input only; do not copy visible guide lines into generated sprite strips",
    }


def animation_keyword_hints(animation_name: str) -> list[str]:
    hints: list[str] = []
    tokens = animation_name.split("-")
    for key, value in STATE_HINTS.items():
        if key in tokens or animation_name.startswith(key) or key in animation_name:
            hints.extend(value)
    return hints


def base_prompt(args: argparse.Namespace, style: str, chroma_key: dict[str, Any]) -> str:
    character_notes = args.character_notes or "the character shown in the reference image(s)"
    chroma_hex = chroma_key["hex"]
    chroma_name = chroma_key["name"]
    background_contract = chroma_background_contract(chroma_key)
    view_note = f"Camera/view: {args.view.strip()}." if args.view.strip() else ""
    return f"""Create one clean canonical reference sprite for a configurable 2D game character named {args.display_name}.

Character: {character_notes}.
Style contract: {style}.
{view_note}

Use this prompt as an authoritative sprite-production spec. Do not turn it into polished key art, a marketing illustration, a 3D render, a realistic portrait, or a scene.

{background_contract}

Output one centered full-body character sprite pose only, on a perfectly flat pure {chroma_name} {chroma_hex} chroma-key background. The sprite must be fully visible, readable at {args.cell_width}x{args.cell_height}, and suitable as the identity reference for all animation rows.

Preserve any provided reference image identity, costume, proportions, palette, accessories, and silhouette. Simplify excessive detail into an animation-ready game sprite. Do not include scenery, text, labels, borders, checkerboard transparency, detached effects, shadows, glows, or extra props not requested. Do not use {chroma_hex}, pure {chroma_name}, or colors close to that chroma key in the character, props, highlights, shadows, or effects."""


def row_prompt(args: argparse.Namespace, animation: AnimationSpec, style: str, chroma_key: dict[str, Any]) -> str:
    character_notes = args.character_notes or "the same character from the approved base reference"
    chroma_hex = chroma_key["hex"]
    chroma_name = chroma_key["name"]
    artifact_rules = "\n".join(f"- {rule}" for rule in TRANSPARENCY_ARTIFACT_RULES)
    background_contract = chroma_background_contract(chroma_key)
    hints = animation_keyword_hints(animation.name)
    hint_text = ""
    if hints:
        hint_text = "\n\nAnimation-specific requirements:\n" + "\n".join(f"- {hint}" for hint in hints)
    view_note = f"\nCamera/view: {args.view.strip()}." if args.view.strip() else ""
    return f"""Create one horizontal sprite strip for the 2D game character `{args.character_id}` in animation `{animation.name}`.

Use the attached reference image(s) for character identity and the attached base character image as the canonical design. Use the attached layout guide only for frame count, slot spacing, centering, and safe padding. Do not copy visible guide lines, boxes, labels, or background.

Identity lock:
- Do not redesign the character. Only change pose/action for the `{animation.name}` animation.
- Preserve the same head/body proportions, face, costume, markings, palette, outline weight, accessory design, prop attachment, and overall silhouette from the canonical base character.
- Keep every frame recognizably the same individual character, not a related variant.
- If the character has a weapon, tool, backpack, cape, hair style, hat, or accessory, preserve its design and attachment style unless this specific action requires pose-only movement.
- Prefer a subtler animation over any change that mutates identity.

Output exactly {animation.frames} separate animation frames arranged left-to-right in one single row. Each frame must show the same character: {character_notes}.

Style contract: {style}.{view_note}
Animation action: {animation.action}.{hint_text}

Transparency and artifact rules:
{background_contract}

{artifact_rules}

Layout requirements:
- Exactly {animation.frames} full-body frames, left to right, in one horizontal row.
- Treat the image as {animation.frames} equal-width invisible frame slots of {args.cell_width}x{args.cell_height} each.
- Fill every slot with exactly one complete pose.
- Spread poses evenly across the whole image width; do not leave requested slots blank.
- Center one complete pose in each slot. No pose may cross into a neighboring slot.
- Use a perfectly flat pure {chroma_name} {chroma_hex} chroma-key background across the whole image.
- Do not draw visible grid lines, borders, labels, numbers, watermarks, or checkerboard transparency.
- Keep the rendering sprite-like and animation-ready: readable silhouette, limited palette, clean outline/edge treatment, consistent proportions, and minimal tiny detail.
- Keep every frame self-contained with safe padding. No body part should be clipped by the frame slot.
- Avoid motion blur. Use clear pose changes readable at the target cell size.
- Do not use {chroma_hex}, pure {chroma_name}, or colors close to that chroma key inside the character, props, highlights, shadows, motion marks, dust, landing marks, or effects."""


def infer_mirror_pairs(animations: list[AnimationSpec], explicit_pairs: list[str]) -> dict[str, str]:
    names = {animation.name for animation in animations}
    pairs: dict[str, str] = {}
    for raw in explicit_pairs:
        raw = raw.strip()
        if not raw:
            continue
        if "=" not in raw:
            raise SystemExit("--mirror-pair must use target=source, for example walk-left=walk-right")
        target, source = [slugify(part) for part in raw.split("=", 1)]
        if target not in names or source not in names:
            raise SystemExit(f"mirror pair references unknown animation: {raw}")
        pairs[target] = source
    if explicit_pairs:
        return pairs

    for animation in animations:
        name = animation.name
        possible_sources = []
        if name.endswith("-left"):
            possible_sources.append(name[:-5] + "-right")
        if name.endswith("-right"):
            possible_sources.append(name[:-6] + "-left")
        if name == "running-left":
            possible_sources.append("running-right")
        if name == "walk-left":
            possible_sources.append("walk-right")
        if name == "run-left":
            possible_sources.append("run-right")
        for source in possible_sources:
            if source in names and source not in pairs and name not in pairs:
                # Prefer deriving left from right; avoid deriving right from left unless explicit.
                if name.endswith("left") or name.endswith("-left"):
                    pairs[name] = source
                break
    return pairs


def make_jobs(run_dir: Path, copied_refs: list[dict[str, Any]], animations: list[AnimationSpec], mirror_pairs: dict[str, str]) -> list[dict[str, Any]]:
    reference_inputs = [
        {"path": rel(Path(str(ref["copied_path"])), run_dir), "role": "character reference"}
        for ref in copied_refs
    ]
    jobs: list[dict[str, Any]] = [
        {
            "id": "base",
            "kind": "base-character",
            "status": "pending",
            "prompt_file": "prompts/base-character.md",
            "input_images": reference_inputs,
            "output_path": "decoded/base.png",
            "depends_on": [],
            "generation_skill": "$imagegen",
            "requires_grounded_generation": bool(reference_inputs),
            "allow_prompt_only_generation": not reference_inputs,
            "recording_owner": "parent",
        }
    ]

    for animation in animations:
        depends_on = ["base"]
        extra_inputs: list[dict[str, str]] = []
        mirror_policy: dict[str, Any] = {}
        source = mirror_pairs.get(animation.name)
        if source:
            depends_on.append(source)
            extra_inputs.append({"path": f"decoded/{source}.png", "role": f"source animation strip for mirror decision: {source}"})
            mirror_policy = {
                "may_derive_from": source,
                "derivation": "horizontal-mirror",
                "requires_explicit_approval": True,
                "fallback_generation_skill": "$imagegen",
            }
        jobs.append(
            {
                "id": animation.name,
                "kind": "animation-strip",
                "status": "pending",
                "prompt_file": f"prompts/animations/{animation.name}.md",
                "input_images": [
                    *reference_inputs,
                    {"path": f"{LAYOUT_GUIDE_DIR}/{animation.name}.png", "role": f"layout guide for {animation.frames} frame slots; use for spacing only, do not copy guide lines"},
                    {"path": CANONICAL_BASE_PATH, "role": "canonical identity reference"},
                    {"path": "decoded/base.png", "role": "approved base character"},
                    *extra_inputs,
                ],
                "output_path": f"decoded/{animation.name}.png",
                "depends_on": depends_on,
                "generation_skill": "$imagegen",
                "requires_grounded_generation": True,
                "allow_prompt_only_generation": False,
                "identity_reference_paths": [CANONICAL_BASE_PATH, "decoded/base.png"],
                "animation": {"name": animation.name, "row": animation.row, "frames": animation.frames, "fps": animation.fps, "action": animation.action},
                "mirror_policy": mirror_policy,
                "recording_owner": "parent",
            }
        )
    return jobs


def load_config(path: str) -> dict[str, Any]:
    if not path:
        return {}
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise SystemExit(f"config file not found: {config_path}")
    return json.loads(config_path.read_text(encoding="utf-8"))


def apply_config(args: argparse.Namespace, config: dict[str, Any]) -> None:
    # Command-line values win when non-empty/non-default. Config fills gaps.
    mapping = {
        "character_name": "character_name",
        "character_id": "character_id",
        "display_name": "display_name",
        "description": "description",
        "character_notes": "character_notes",
        "style_preset": "style_preset",
        "style_notes": "style_notes",
        "view": "view",
        "cell_width": "cell_width",
        "cell_height": "cell_height",
        "columns": "columns",
        "fps": "fps",
        "chroma_key": "chroma_key",
        "output_dir": "output_dir",
    }
    parser_defaults = build_parser().parse_args([])
    for key, attr in mapping.items():
        if key not in config:
            continue
        current = getattr(args, attr)
        default = getattr(parser_defaults, attr)
        if current == default or current in ("", [], None):
            setattr(args, attr, config[key])
    if not args.reference and isinstance(config.get("references"), list):
        args.reference = [str(item) for item in config["references"]]
    if not args.animation and isinstance(config.get("animations"), list):
        args.animation = []
        for item in config["animations"]:
            if isinstance(item, str):
                args.animation.append(item)
            elif isinstance(item, dict):
                name = item.get("name")
                frames = item.get("frames", 6)
                action = item.get("action", "")
                if not name:
                    raise SystemExit("config animations require name")
                args.animation.append(f"{name}:{frames}:{action}")
    if not args.mirror_pair and isinstance(config.get("mirror_pairs"), dict):
        args.mirror_pair = [f"{target}={source}" for target, source in config["mirror_pairs"].items()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="", help="Optional JSON config file. CLI flags override config defaults.")
    parser.add_argument("--character-name", default="")
    parser.add_argument("--character-id", default="", help="Stable slug. Defaults to slugified character name.")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--character-notes", default="", help="Main concept: species/type/costume/personality/role.")
    parser.add_argument("--style-preset", default="pixel-platformer", choices=sorted(STYLE_PRESETS))
    parser.add_argument("--style-notes", default="", help="Additional art direction, palette, inspiration, restrictions.")
    parser.add_argument("--view", default="", help="Camera/view notes, e.g. side-view, top-down, 3/4, isometric.")
    parser.add_argument("--animation-preset", default="", choices=["", *sorted(ANIMATION_PRESETS)])
    parser.add_argument("--animation", action="append", default=[], help="Animation spec: name:frames:action. Repeatable.")
    parser.add_argument("--mirror-pair", action="append", default=[], help="Optional target=source mirror pair, e.g. walk-left=walk-right. If omitted, left/right pairs are inferred.")
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--cell-width", type=int, default=DEFAULT_CELL_WIDTH)
    parser.add_argument("--cell-height", type=int, default=DEFAULT_CELL_HEIGHT)
    parser.add_argument("--columns", type=int, default=0, help="Atlas columns. Defaults to max animation frame count.")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--chroma-key", default="auto", help="Chroma key as #RRGGBB, or auto.")
    parser.add_argument("--force", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)
    if config:
        apply_config(args, config)

    if args.cell_width < 16 or args.cell_height < 16:
        raise SystemExit("cell size must be at least 16x16")
    if args.fps < 1 or args.fps > 60:
        raise SystemExit("fps must be between 1 and 60")

    raw_reference_paths = [Path(raw).expanduser().resolve() for raw in args.reference]
    args.display_name = infer_name(args, raw_reference_paths)
    args.character_name = (args.character_name or args.display_name).strip()
    args.description = infer_description(args, raw_reference_paths)
    args.character_notes = infer_character_notes(args, raw_reference_paths)
    args.character_id = slugify(args.character_id or args.character_name or args.display_name)
    if not args.character_id:
        raise SystemExit("character id must contain at least one letter or digit")

    if args.animation:
        animations = [parse_animation(raw, row, args.fps) for row, raw in enumerate(args.animation)]
    else:
        preset = args.animation_preset or "platformer"
        animations = preset_animations(preset, args.fps)
    seen: set[str] = set()
    for animation in animations:
        if animation.name in seen:
            raise SystemExit(f"duplicate animation name: {animation.name}")
        seen.add(animation.name)

    columns = args.columns or max(animation.frames for animation in animations)
    if columns < max(animation.frames for animation in animations):
        raise SystemExit("--columns must be at least the max animation frame count")
    if columns > 64:
        raise SystemExit("--columns must be <= 64")

    run_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir(args.character_id).resolve()
    if run_dir.exists() and any(run_dir.iterdir()) and not args.force:
        raise SystemExit(f"{run_dir} already exists and is not empty; pass --force to reuse it")
    run_dir.mkdir(parents=True, exist_ok=True)

    ref_dir = run_dir / "references"
    prompt_dir = run_dir / "prompts"
    anim_prompt_dir = prompt_dir / "animations"
    for directory in [ref_dir, prompt_dir, anim_prompt_dir, run_dir / "decoded", run_dir / "qa"]:
        directory.mkdir(parents=True, exist_ok=True)

    copied_refs: list[dict[str, Any]] = []
    copied_ref_paths: list[Path] = []
    for index, source in enumerate(raw_reference_paths, start=1):
        if not source.is_file():
            raise SystemExit(f"reference not found: {source}")
        if source.suffix.lower() not in IMAGE_SUFFIXES:
            raise SystemExit(f"reference must be an image file: {source}")
        copied = ref_dir / f"reference-{index:02d}{source.suffix.lower()}"
        shutil.copy2(source, copied)
        meta = image_metadata(copied)
        meta["source_path"] = str(source)
        meta["copied_path"] = str(copied)
        copied_refs.append(meta)
        copied_ref_paths.append(copied)

    chroma_key = choose_chroma_key(copied_ref_paths, str(args.chroma_key))
    style = style_contract(str(args.style_preset), str(args.style_notes))
    margin_x = max(4, min(24, args.cell_width // 10))
    margin_y = max(4, min(24, args.cell_height // 10))
    guides = [
        create_layout_guide(run_dir / LAYOUT_GUIDE_DIR / f"{animation.name}.png", animation, args.cell_width, args.cell_height, margin_x, margin_y)
        for animation in animations
    ]
    mirror_pairs = infer_mirror_pairs(animations, args.mirror_pair)

    atlas = {
        "columns": columns,
        "rows": len(animations),
        "cell_width": args.cell_width,
        "cell_height": args.cell_height,
        "width": columns * args.cell_width,
        "height": len(animations) * args.cell_height,
    }
    request = {
        "schema_version": 1,
        "character_id": args.character_id,
        "display_name": args.display_name,
        "description": args.description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "atlas": atlas,
        "animations": [animation.__dict__ for animation in animations],
        "layout_guides": [{**guide, "path": rel(Path(str(guide["path"])), run_dir)} for guide in guides],
        "references": copied_refs,
        "chroma_key": chroma_key,
        "character_notes": args.character_notes,
        "style_preset": args.style_preset,
        "style_notes": args.style_notes,
        "style_contract": style,
        "view": args.view,
        "mirror_pairs": mirror_pairs,
        "primary_generation_skill": "$imagegen",
    }
    (run_dir / "character_request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")

    write_text(prompt_dir / "base-character.md", base_prompt(args, style, chroma_key))
    for animation in animations:
        write_text(anim_prompt_dir / f"{animation.name}.md", row_prompt(args, animation, style, chroma_key))

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "primary_generation_skill": "$imagegen",
        "jobs": make_jobs(run_dir, copied_refs, animations, mirror_pairs),
    }
    (run_dir / "imagegen-jobs.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "run_dir": str(run_dir),
        "request": str(run_dir / "character_request.json"),
        "jobs": str(run_dir / "imagegen-jobs.json"),
        "ready_jobs": ["base"],
        "animations": [animation.name for animation in animations],
        "atlas": atlas,
        "mirror_pairs": mirror_pairs,
    }, indent=2))


if __name__ == "__main__":
    main()
