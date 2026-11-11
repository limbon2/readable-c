"""Snapshots of files under refactor, kept outside the project.

A snapshot holds the original bytes, the regions and what `start` learned about
them. It lives in the OS temp folder (or READABLE_C_STATE_DIR), so the tool never
writes into the project it works on.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .regions import Region

STATE_DIR_VARIABLE = "READABLE_C_STATE_DIR"
FORMAT_VERSION = 1


class StateError(RuntimeError):
    """The snapshot is missing, unreadable or does not match the file."""


@dataclass
class Snapshot:
    path: Path
    original: bytes
    regions: list[Region]
    created: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    baseline: list[dict[str, object]] = field(default_factory=list)
    frozen: list[dict[str, object]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def state_dir() -> Path:
    configured = os.environ.get(STATE_DIR_VARIABLE)
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "readable-c"


def _key(path: Path) -> str:
    identity = os.path.normcase(str(path.resolve()))
    return hashlib.sha256(identity.encode("utf-8", "surrogateescape")).hexdigest()[:24]


def _paths(path: Path) -> tuple[Path, Path]:
    key = _key(path)
    folder = state_dir()
    return folder / f"{key}.json", folder / f"{key}.orig"


def exists(path: Path) -> bool:
    metadata, _ = _paths(path)
    return metadata.exists()


def save(snapshot: Snapshot) -> Path:
    metadata_path, original_path = _paths(snapshot.path)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_bytes(snapshot.original)
    metadata = {
        "format": FORMAT_VERSION,
        "path": str(snapshot.path.resolve()),
        "created": snapshot.created,
        "original_sha256": hashlib.sha256(snapshot.original).hexdigest(),
        "regions": [region.to_json() for region in snapshot.regions],
        "baseline": snapshot.baseline,
        "frozen": snapshot.frozen,
        "notes": snapshot.notes,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata_path


def load(path: Path) -> Snapshot:
    metadata_path, original_path = _paths(path)
    if not metadata_path.exists():
        raise StateError(
            f"No refactor in progress for {path}. Run `start` first to select regions."
        )
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        original = original_path.read_bytes()
    except (OSError, ValueError) as error:
        raise StateError(
            f"The snapshot for {path} is unreadable ({error}). Run `start --replace`."
        ) from error
    if metadata.get("format") != FORMAT_VERSION:
        raise StateError(
            f"The snapshot for {path} comes from another version of the tool. Run `start --replace`."
        )
    if hashlib.sha256(original).hexdigest() != metadata["original_sha256"]:
        raise StateError(f"The snapshot for {path} is damaged. Run `start --replace`.")
    return Snapshot(
        path=Path(metadata["path"]),
        original=original,
        regions=[Region.from_json(item) for item in metadata["regions"]],
        created=metadata["created"],
        baseline=metadata.get("baseline", []),
        frozen=metadata.get("frozen", []),
        notes=metadata.get("notes", []),
    )


def delete(path: Path) -> bool:
    removed = False
    for file in _paths(path):
        if file.exists():
            file.unlink()
            removed = True
    return removed
