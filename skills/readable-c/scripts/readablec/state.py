"""Snapshots of files under refactor, kept outside the project.

A snapshot holds the original bytes, the regions and what `start` learned about
them. It lives in a folder that only the current user can use: their own
subfolder of the OS temp folder, or READABLE_C_STATE_DIR. The tool never writes
into the project it works on.

`restore --whole-file` writes a snapshot back into a source file, so snapshots
must not come from anyone else. On a shared temp folder such as Linux's /tmp,
another user could otherwise create the folder first, plant a link where a
snapshot will be written, or plant a snapshot of their own. Hence the private
folder, the owner check, writes that replace a planted link instead of
following it, and the check that a snapshot belongs to the file it is used for.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .regions import Region

STATE_DIR_VARIABLE = "READABLE_C_STATE_DIR"
FORMAT_VERSION = 1
PRIVATE_FOLDER_MODE = 0o700
GROUP_AND_OTHER_BITS = 0o077


class StateError(RuntimeError):
    """The snapshot is missing, unreadable, not private or does not match the file."""


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
    # Digests of the region text that `reader` wrote a brief for, oldest first.
    reader_briefs: list[str] = field(default_factory=list)
    # Digest of the whole file at the last `verify --final`, which `finish` compares.
    final_digest: str | None = None


def state_dir() -> Path:
    """The private state folder, created and checked before every use."""
    configured = os.environ.get(STATE_DIR_VARIABLE)
    default = Path(tempfile.gettempdir()) / f"readable-c-{_user_tag()}"
    folder = Path(configured) if configured else default
    _ensure_private(folder)
    return folder


def _user_tag() -> str:
    """Tells users apart in a shared temp folder: the numeric uid, or a hash of the name."""
    getuid = getattr(os, "getuid", None)
    if getuid is not None:
        return str(getuid())
    return hashlib.sha256(getpass.getuser().encode("utf-8", "replace")).hexdigest()[:12]


def _ensure_private(folder: Path) -> None:
    folder.mkdir(mode=PRIVATE_FOLDER_MODE, parents=True, exist_ok=True)
    info = os.lstat(folder)
    is_real_folder = stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
    if not is_real_folder:
        raise StateError(
            f"The state folder {folder} is a link or not a folder. Remove it, or set "
            f"{STATE_DIR_VARIABLE} to a folder of your own."
        )
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        # Windows has no uids; each user's temp folder is private through its access list.
        return
    if info.st_uid != getuid():
        raise StateError(
            f"The state folder {folder} belongs to another user, so its snapshots cannot be "
            f"trusted. Set {STATE_DIR_VARIABLE} to a folder of your own."
        )
    if info.st_mode & GROUP_AND_OTHER_BITS:
        folder.chmod(PRIVATE_FOLDER_MODE)


def _key(path: Path) -> str:
    return hashlib.sha256(_identity(path).encode("utf-8", "surrogateescape")).hexdigest()[:24]


def _identity(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _paths(path: Path) -> tuple[Path, Path]:
    key = _key(path)
    folder = state_dir()
    return folder / f"{key}.json", folder / f"{key}.orig"


def _write_private(target: Path, data: bytes) -> None:
    """Write a new file next to the target and rename it into place. A link planted at the
    target's name is replaced, never followed, and the new file is readable by its owner only."""
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=".write-")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
        Path(temporary).replace(target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_private(source: Path) -> bytes:
    if stat.S_ISLNK(os.lstat(source).st_mode):
        raise StateError(f"{source} is a link, not a snapshot. Run `start --replace`.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(source, flags), "rb") as file:
        return file.read()


def file_digest(data: bytes) -> str:
    """Names the exact bytes of a file, so a later command can tell whether it changed."""
    return hashlib.sha256(data).hexdigest()[:16]


def exists(path: Path) -> bool:
    metadata, _ = _paths(path)
    return os.path.lexists(metadata)


def save(snapshot: Snapshot) -> Path:
    metadata_path, original_path = _paths(snapshot.path)
    metadata = {
        "format": FORMAT_VERSION,
        "path": _identity(snapshot.path),
        "created": snapshot.created,
        "original_sha256": hashlib.sha256(snapshot.original).hexdigest(),
        "regions": [region.to_json() for region in snapshot.regions],
        "baseline": snapshot.baseline,
        "frozen": snapshot.frozen,
        "notes": snapshot.notes,
        "reader_briefs": snapshot.reader_briefs,
        "final_digest": snapshot.final_digest,
    }
    _write_private(original_path, snapshot.original)
    _write_private(metadata_path, json.dumps(metadata, indent=2).encode("utf-8"))
    return metadata_path


def load(path: Path) -> Snapshot:
    metadata_path, original_path = _paths(path)
    if not os.path.lexists(metadata_path):
        raise StateError(
            f"No refactor in progress for {path}. Run `start` first to select regions."
        )
    try:
        metadata = json.loads(_read_private(metadata_path).decode("utf-8"))
        original = _read_private(original_path)
    except (OSError, ValueError) as error:
        raise StateError(
            f"The snapshot for {path} is unreadable ({error}). Run `start --replace`."
        ) from error
    if metadata.get("format") != FORMAT_VERSION:
        raise StateError(
            f"The snapshot for {path} comes from another version of the tool. Run `start --replace`."
        )
    if metadata.get("path") != _identity(path):
        raise StateError(
            f"The snapshot found for {path} belongs to another file. Run `start --replace`."
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
        reader_briefs=metadata.get("reader_briefs", []),
        final_digest=metadata.get("final_digest"),
    )


def delete(path: Path) -> bool:
    removed = False
    for file in _paths(path):
        if os.path.lexists(file):
            file.unlink()
            removed = True
    return removed
