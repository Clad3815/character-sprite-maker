#!/usr/bin/env python3
"""Derive one animation strip by horizontally mirroring another approved strip."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "imagegen-jobs.json"
    if not path.is_file():
        raise SystemExit(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def jobs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("jobs")
    if not isinstance(raw, list):
        raise SystemExit("invalid imagegen-jobs.json")
    return [job for job in raw if isinstance(job, dict)]


def find_job(manifest: dict[str, Any], job_id: str) -> dict[str, Any]:
    for job in jobs(manifest):
        if job.get("id") == job_id:
            return job
    raise SystemExit(f"unknown job id: {job_id}")


def resolve_manifest_path(raw: object, run_dir: Path, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise SystemExit(f"missing {label}")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = run_dir / path
    return path.resolve()


def completed_ids(manifest: dict[str, Any]) -> set[str]:
    return {str(job["id"]) for job in jobs(manifest) if job.get("status") == "complete" and isinstance(job.get("id"), str)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--target", required=True, help="Target animation job to mark complete, e.g. walk-left.")
    parser.add_argument("--source", default="", help="Source animation job. Defaults to the target job's mirror_policy.may_derive_from.")
    parser.add_argument("--confirm-appropriate-mirror", action="store_true", help="Required after visual review confirms mirroring preserves identity and semantics.")
    parser.add_argument("--decision-note", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.confirm_appropriate_mirror:
        raise SystemExit("refusing to mirror without --confirm-appropriate-mirror after visual review")
    if not args.decision_note.strip():
        raise SystemExit("please include --decision-note explaining why mirroring is safe")

    run_dir = Path(args.run_dir).expanduser().resolve()
    manifest_file = run_dir / "imagegen-jobs.json"
    manifest = load_manifest(run_dir)
    target_job = find_job(manifest, args.target)
    mirror_policy = target_job.get("mirror_policy") if isinstance(target_job.get("mirror_policy"), dict) else {}
    source_id = args.source.strip() or str(mirror_policy.get("may_derive_from") or "")
    if not source_id:
        raise SystemExit("source animation not supplied and target has no mirror policy")
    source_job = find_job(manifest, source_id)
    if source_job.get("status") != "complete":
        raise SystemExit(f"source job {source_id} is not complete")
    deps = [dep for dep in target_job.get("depends_on", []) if isinstance(dep, str)]
    missing_deps = [dep for dep in deps if dep not in completed_ids(manifest) and dep != args.target]
    if missing_deps:
        raise SystemExit(f"target job {args.target} is not ready; missing dependencies: {', '.join(missing_deps)}")

    source_path = resolve_manifest_path(source_job.get("output_path"), run_dir, "source output_path")
    output_path = resolve_manifest_path(target_job.get("output_path"), run_dir, "target output_path")
    if not source_path.is_file():
        raise SystemExit(f"source output missing: {source_path}")
    if output_path.exists() and not args.force:
        raise SystemExit(f"{output_path} already exists; pass --force to replace it")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as opened:
        mirrored = ImageOps.mirror(opened.convert("RGBA"))
    mirrored.save(output_path)

    target_job["status"] = "complete"
    target_job["source_path"] = str(source_path)
    target_job["source_provenance"] = "deterministic-mirror"
    target_job["source_sha256"] = file_sha256(source_path)
    target_job["output_sha256"] = file_sha256(output_path)
    target_job["derived_from"] = source_id
    target_job["completed_at"] = datetime.now(timezone.utc).isoformat()
    target_job["mirror_decision"] = {
        "approved": True,
        "source_animation": source_id,
        "target_animation": args.target,
        "note": args.decision_note.strip(),
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    for key in ["last_error", "repair_reason", "queued_at"]:
        target_job.pop(key, None)

    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "target": args.target, "source": source_id, "output": str(output_path)}, indent=2))


if __name__ == "__main__":
    main()
