#!/usr/bin/env python3
"""Record a selected $imagegen output for a character sprite generation job."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

CANONICAL_BASE_PATH = "references/canonical-base.png"
CHROMA_NEAR_THRESHOLD = 12.0
CHROMA_MAX_DISTANCE_THRESHOLD = 32.0
CHROMA_MIN_NEAR_EDGE_RATIO = 0.98
CHROMA_MIN_EXACT_EDGE_RATIO = 0.80


def load_jobs(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"job manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def job_list(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise SystemExit("invalid imagegen-jobs.json: jobs must be a list")
    return [job for job in jobs if isinstance(job, dict)]


def find_job(manifest: dict[str, Any], job_id: str) -> dict[str, Any]:
    for job in job_list(manifest):
        if job.get("id") == job_id:
            return job
    raise SystemExit(f"unknown job id: {job_id}")


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        return {"width": image.width, "height": image.height, "mode": image.mode, "format": image.format}


def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not value.startswith("#") or len(value) != 7:
        raise ValueError(f"invalid chroma key color: {value!r}")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return math.sqrt(sum((left[index] - right[index]) ** 2 for index in range(3)))


def load_request(run_dir: Path) -> dict[str, Any]:
    request_path = run_dir / "character_request.json"
    if not request_path.is_file():
        return {}
    return json.loads(request_path.read_text(encoding="utf-8"))


def load_chroma_key(run_dir: Path) -> tuple[int, int, int] | None:
    request = load_request(run_dir)
    chroma_key = request.get("chroma_key")
    if not isinstance(chroma_key, dict):
        return None
    rgb = chroma_key.get("rgb")
    if isinstance(rgb, list) and len(rgb) == 3 and all(isinstance(value, int) for value in rgb):
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    raw_hex = chroma_key.get("hex")
    if isinstance(raw_hex, str):
        return parse_hex_color(raw_hex)
    return None


def audit_chroma_background(path: Path, chroma_key: tuple[int, int, int]) -> dict[str, Any]:
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    border = max(4, min(16, min(image.width, image.height) // 32))
    total_edge_count = 0
    transparent_edge_count = 0
    distances: list[float] = []
    for y in range(image.height):
        for x in range(image.width):
            if x >= border and x < image.width - border and y >= border and y < image.height - border:
                continue
            total_edge_count += 1
            red, green, blue, alpha = image.getpixel((x, y))
            if alpha <= 16:
                transparent_edge_count += 1
                continue
            distances.append(color_distance((red, green, blue), chroma_key))

    transparent_edge_ratio = transparent_edge_count / total_edge_count if total_edge_count else 0.0
    if not distances:
        warnings = []
        if transparent_edge_ratio < CHROMA_MIN_NEAR_EDGE_RATIO:
            warnings.append(
                "could not audit chroma background because the image border has no opaque pixels, "
                f"but only {transparent_edge_ratio:.1%} of edge pixels were transparent"
            )
        return {
            "ok": not warnings,
            "total_edge_pixel_count": total_edge_count,
            "edge_pixel_count": 0,
            "transparent_edge_count": transparent_edge_count,
            "transparent_edge_ratio": round(transparent_edge_ratio, 4),
            "warnings": warnings,
        }

    exact_count = sum(1 for distance in distances if distance == 0)
    near_count = sum(1 for distance in distances if distance <= CHROMA_NEAR_THRESHOLD)
    max_distance = max(distances)
    mean_distance = sum(distances) / len(distances)
    exact_edge_ratio = exact_count / len(distances)
    near_edge_ratio = near_count / len(distances)
    warnings = []
    if near_edge_ratio < CHROMA_MIN_NEAR_EDGE_RATIO:
        warnings.append(
            f"edge background is not consistently close to the chroma key "
            f"({near_edge_ratio:.1%} within {CHROMA_NEAR_THRESHOLD:g}px color distance)"
        )
    if exact_edge_ratio < CHROMA_MIN_EXACT_EDGE_RATIO:
        warnings.append(f"edge background is not a flat exact key color ({exact_edge_ratio:.1%} exact matches)")
    if max_distance > CHROMA_MAX_DISTANCE_THRESHOLD:
        warnings.append(f"edge background has color drift up to {max_distance:.1f} from the chroma key")

    return {
        "ok": not warnings,
        "total_edge_pixel_count": total_edge_count,
        "edge_pixel_count": len(distances),
        "transparent_edge_count": transparent_edge_count,
        "transparent_edge_ratio": round(transparent_edge_ratio, 4),
        "border_width": border,
        "chroma_rgb": list(chroma_key),
        "exact_edge_ratio": round(exact_edge_ratio, 4),
        "near_edge_ratio": round(near_edge_ratio, 4),
        "mean_edge_distance": round(mean_distance, 2),
        "max_edge_distance": round(max_distance, 2),
        "warnings": warnings,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_relative(path: Path, run_dir: Path) -> str:
    return str(path.resolve().relative_to(run_dir.resolve()))


def completed_job_ids(manifest: dict[str, Any]) -> set[str]:
    return {str(job["id"]) for job in job_list(manifest) if job.get("status") == "complete" and isinstance(job.get("id"), str)}


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_source_path(source: Path, run_dir: Path, allow_run_source: bool) -> str:
    if is_relative_to(source, run_dir) and not allow_run_source:
        raise SystemExit(
            "source image is inside the run directory; record the original $imagegen output instead, "
            "or pass --allow-run-source for controlled normalized/manual imports"
        )
    if is_relative_to(source, run_dir):
        return "normalized-run-source"
    return "built-in-imagegen-or-manual"


def validate_required_grounding(job: dict[str, Any], run_dir: Path) -> None:
    if job.get("allow_prompt_only_generation") is not False:
        return
    inputs = job.get("input_images")
    if not isinstance(inputs, list) or not inputs:
        raise SystemExit(f"job {job.get('id')} does not list input_images; grounded animation jobs must attach references")
    missing = []
    for item in inputs:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise SystemExit(f"job {job.get('id')} has an invalid input image entry")
        path = Path(item["path"])
        if not path.is_absolute():
            path = run_dir / path
        if not path.is_file():
            missing.append(str(path.resolve()))
    if missing:
        raise SystemExit(f"job {job.get('id')} is missing required grounding image(s): " + ", ".join(missing))


def update_base_canonical_reference(run_dir: Path, output: Path, manifest: dict[str, Any], job: dict[str, Any], metadata: dict[str, Any]) -> None:
    if job.get("id") != "base":
        return
    canonical = run_dir / CANONICAL_BASE_PATH
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output, canonical)
    reference = {
        "path": manifest_relative(canonical, run_dir),
        "source_job": "base",
        "sha256": file_sha256(canonical),
        "metadata": metadata,
    }
    job["canonical_reference_path"] = reference["path"]
    manifest["canonical_identity_reference"] = reference
    request_path = run_dir / "character_request.json"
    if request_path.exists():
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["canonical_identity_reference"] = reference
        request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--allow-run-source", action="store_true", help="Allow a source inside the run directory; useful for normalize_chroma_source.py outputs or controlled manual imports.")
    parser.add_argument("--strict-chroma-background", action="store_true", help="Reject the image if its edge background is not a flat chroma-key color.")
    parser.add_argument("--skip-chroma-background-audit", action="store_true", help="Skip the generated-image chroma background audit.")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"source image not found: {source}")
    source_provenance = validate_source_path(source, run_dir, args.allow_run_source)

    manifest_path = run_dir / "imagegen-jobs.json"
    manifest = load_jobs(manifest_path)
    job = find_job(manifest, args.job_id)
    missing_deps = [dep for dep in job.get("depends_on", []) if isinstance(dep, str) and dep not in completed_job_ids(manifest)]
    if missing_deps:
        raise SystemExit(f"job {args.job_id} is not ready; missing dependency result(s): {', '.join(missing_deps)}")
    validate_required_grounding(job, run_dir)

    output_raw = job.get("output_path")
    if not isinstance(output_raw, str):
        raise SystemExit(f"job {args.job_id} has no output_path")
    output = Path(output_raw)
    if not output.is_absolute():
        output = run_dir / output
    if output.exists() and not args.force:
        raise SystemExit(f"{output} already exists; pass --force to replace it")

    metadata = image_metadata(source)
    chroma_audit = None
    chroma_warnings: list[str] = []
    if not args.skip_chroma_background_audit:
        chroma_key = load_chroma_key(run_dir)
        if chroma_key is not None:
            chroma_audit = audit_chroma_background(source, chroma_key)
            raw_warnings = chroma_audit.get("warnings")
            if isinstance(raw_warnings, list):
                chroma_warnings = [str(item) for item in raw_warnings]
            if chroma_warnings and args.strict_chroma_background:
                print(json.dumps({
                    "ok": False,
                    "job_id": args.job_id,
                    "source": str(source),
                    "chroma_background_audit": chroma_audit,
                    "hint": "Regenerate this image with an exact flat chroma-key background, or normalize a visually clean removable chroma source with normalize_chroma_source.py and record that PNG.",
                }, indent=2))
                raise SystemExit(1)

    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)

    job["status"] = "complete"
    job["source_path"] = str(source)
    job["source_provenance"] = source_provenance
    job["source_sha256"] = file_sha256(source)
    job["output_sha256"] = file_sha256(output)
    job["completed_at"] = datetime.now(timezone.utc).isoformat()
    job["metadata"] = metadata
    if chroma_audit is not None:
        job["chroma_background_audit"] = chroma_audit
    if chroma_warnings:
        job["chroma_background_warnings"] = chroma_warnings
    for key in ["last_error", "derived_from", "mirror_decision", "repair_reason", "queued_at"]:
        job.pop(key, None)
    update_base_canonical_reference(run_dir, output, manifest, job, metadata)

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    result: dict[str, Any] = {"ok": True, "job_id": args.job_id, "output": str(output), "metadata": metadata}
    if chroma_audit is not None:
        result["chroma_background_audit"] = chroma_audit
    if chroma_warnings:
        result["warnings"] = chroma_warnings
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
