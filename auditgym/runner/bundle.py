"""Build a source-and-evidence candidate archive, not a published release."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from auditgym import ENV_VERSION

from .snapshot import digest_files, source_files


def assemble(payload, metadata, out):
    manifest = {**metadata, "files": {
        name: {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        for name, data in sorted(payload.items())}}
    entries = {**payload, "manifest.json": (json.dumps(
        manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")}
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    verify(out)
    return manifest


def verify(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members")
        if any(PurePosixPath(n).is_absolute() or PureWindowsPath(n).drive
               or ".." in PurePosixPath(n).parts
               or "\\" in n for n in names):
            raise ValueError("Unsafe archive member")
        if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
            raise ValueError("Archive exceeds verification limit")
        manifest = json.loads(archive.read("manifest.json"))
        if set(names) != set(manifest["files"]) | {"manifest.json"}:
            raise ValueError("Archive inventory mismatch")
        for name, expected in manifest["files"].items():
            data = archive.read(name)
            if len(data) != expected["size"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                raise ValueError("Archive checksum mismatch")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--demo", type=Path)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args(argv)
    if args.verify:
        manifest = verify(args.verify)
        print(f"Verified {len(manifest['files'])} archive members")
        return 0
    if not all((args.out, args.validation, args.demo, args.wheel)):
        parser.error("Supply --out, --validation, --demo and --wheel (or --verify)")
    sidecar = Path(str(args.out) + ".sha256")
    if args.out.exists() or sidecar.exists():
        parser.error("Output already exists")
    root = Path(__file__).resolve().parents[2]
    if not (root / "pyproject.toml").is_file() or not (root / "tests").is_dir():
        parser.error("Building a candidate requires a source checkout")
    sources = source_files(root)
    report = json.loads((args.validation / "validation.json").read_text(encoding="utf-8"))
    expected_stages = {"lint", "tests_and_acceptance", "episode_checksums", "four_baselines",
                       "grader_selfcheck"}
    if (report.get("status") != "passed" or report.get("env_version") != ENV_VERSION
        or {s["name"] for s in report["stages"] if s["status"] == "passed"} != expected_stages):
        parser.error("Full validation report must pass for the current version")
    if report.get("source_sha256") != digest_files(sources):
        parser.error("Source changed since validation; run validation again")
    payload = {"source/" + name: content for name, content in sources.items()}
    for filename in ("validation.json", "acceptance.json", "junit.xml"):
        payload["evidence/" + filename] = (args.validation / filename).read_bytes()
    payload["evidence/demo.cast"] = args.demo.read_bytes()
    payload["evidence/demo.json"] = args.demo.with_suffix(".json").read_bytes()
    payload["packages/" + args.wheel.name] = args.wheel.read_bytes()
    parent = (subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
              if (root / ".git").exists() else None)
    manifest = assemble(payload, {"format_version": "1.0", "env_version": ENV_VERSION,
                                  "source_sha256": report["source_sha256"],
                                  "parent_commit": parent, "working_tree_included": True,
                                  "release_status": "candidate_unverified_container",
                                  "container_verified": False}, args.out)
    with sidecar.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(hashlib.sha256(args.out.read_bytes()).hexdigest() + "  " + args.out.name + "\n")
    print(f"Candidate built and verified: {args.out} ({len(manifest['files'])} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
