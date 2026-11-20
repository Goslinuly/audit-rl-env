import json
import zipfile

import pytest

from auditgym.runner.bundle import assemble, verify
from auditgym.runner.snapshot import digest_files, source_files


def test_source_digest_tracks_names_and_bytes_not_dictionary_order():
    assert digest_files({"b": b"2", "a": b"1"}) == digest_files({"a": b"1", "b": b"2"})
    assert digest_files({"a": b"1"}) != digest_files({"a": b"2"})
    assert digest_files({"a": b"1"}) != digest_files({"b": b"1"})


def test_bundle_reproducible_and_inventory_verified(tmp_path):
    payload = {"source/code.py": b"print('ok')\n", "evidence/result.json": b"{}"}
    metadata = {"release_status": "candidate_unverified_container"}
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    assemble(payload, metadata, first)
    assemble(dict(reversed(list(payload.items()))), metadata, second)
    assert first.read_bytes() == second.read_bytes()
    assert len(verify(first)["files"]) == 2


def test_bundle_tampering_is_detected(tmp_path):
    original = tmp_path / "original.zip"
    assemble({"source/code.py": b"safe"}, {}, original)
    with zipfile.ZipFile(original) as archive:
        manifest = archive.read("manifest.json")
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(changed, "w") as archive:
        archive.writestr("manifest.json", manifest)
        archive.writestr("source/code.py", b"evil")
    with pytest.raises(ValueError, match="checksum"):
        verify(changed)


@pytest.mark.parametrize("member", ["../outside", "C:/outside", "C:outside"])
def test_bundle_rejects_path_traversal(tmp_path, member):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, b"bad")
        archive.writestr("manifest.json", json.dumps({"files": {}}))
    with pytest.raises(ValueError, match="Unsafe"):
        verify(path)


def test_source_snapshot_works_without_git_and_excludes_runtime_artifacts(tmp_path):
    (tmp_path / "code.py").write_text("print('ok')")
    (tmp_path / ".env").write_text("private-local-config")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs/log.json").write_text("ignored")
    assert source_files(tmp_path) == {"code.py": b"print('ok')"}
