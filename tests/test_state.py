"""Snapshots stay private: no planted folder, link or snapshot can steer the tool."""

import json
import os
import stat
from pathlib import Path

import pytest
from readablec import state
from readablec.regions import Region

IS_POSIX = hasattr(os, "getuid")


@pytest.fixture
def state_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "state"
    monkeypatch.setenv(state.STATE_DIR_VARIABLE, str(folder))
    return folder


def snapshot_of(path: Path) -> state.Snapshot:
    return state.Snapshot(
        path=path, original=path.read_bytes(), regions=[Region(0, 4, "lines", "first line")]
    )


def test_save_and_load_round_trip_without_leftovers(tmp_path: Path, state_folder: Path):
    source = tmp_path / "a.c"
    source.write_bytes(b"int x;\r\nint y;\r\n")
    state.save(snapshot_of(source))
    loaded = state.load(source)
    assert loaded.original == b"int x;\r\nint y;\r\n"
    assert not [entry for entry in state_folder.iterdir() if entry.name.startswith(".write-")]
    assert state.delete(source)
    assert not state.exists(source)


def test_a_snapshot_of_another_file_is_refused(tmp_path: Path, state_folder: Path):
    source = tmp_path / "a.c"
    source.write_bytes(b"int x;\n")
    metadata_path = state.save(snapshot_of(source))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["path"] = str(tmp_path / "other.c")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(state.StateError, match="belongs to another file"):
        state.load(source)


def test_the_default_folder_is_per_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.delenv(state.STATE_DIR_VARIABLE, raising=False)
    monkeypatch.setattr(state.tempfile, "gettempdir", lambda: str(tmp_path))
    folder = state.state_dir()
    assert folder.parent == tmp_path
    assert folder.name.startswith("readable-c-")
    assert folder.name != "readable-c-"


@pytest.mark.skipif(not IS_POSIX, reason="permission bits and uids are POSIX")
def test_the_folder_is_created_private_and_kept_private(state_folder: Path):
    state.state_dir()
    assert stat.S_IMODE(state_folder.stat().st_mode) == 0o700
    state_folder.chmod(0o777)
    state.state_dir()
    assert stat.S_IMODE(state_folder.stat().st_mode) == 0o700


def make_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("this system does not let the tests create links")


def test_a_linked_state_folder_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    real = tmp_path / "elsewhere"
    real.mkdir()
    link = tmp_path / "state"
    make_link(link, real)
    monkeypatch.setenv(state.STATE_DIR_VARIABLE, str(link))
    with pytest.raises(state.StateError, match="is a link"):
        state.state_dir()


def test_a_planted_link_is_replaced_not_followed(tmp_path: Path, state_folder: Path):
    source = tmp_path / "a.c"
    source.write_bytes(b"int x;\n")
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"keep me")
    metadata_path, original_path = state._paths(source)
    make_link(original_path, victim)
    state.save(snapshot_of(source))
    assert victim.read_bytes() == b"keep me"
    assert not original_path.is_symlink()
    assert metadata_path.exists()
