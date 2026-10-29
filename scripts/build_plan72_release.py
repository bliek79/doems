"""Package tracked source only, excluding generated Python bytecode."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

from validate_plan72_release import ROOT, VERSION, validate


def build() -> Path:
    provenance = validate()
    # A provenance commit must identify exactly the bytes in the archive.
    # Generated build output is ignored; source edits must be committed first.
    assert not subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True
    ).strip(), "release packaging requires a clean tracked source tree"
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    prefixes = ("custom_components/doems/", "examples/", "docs/")
    selected = sorted(name for name in paths if name and (
        name.startswith(prefixes) or name in {"LICENSE", "README.md", "hacs.json", f"RELEASE_NOTES_v{VERSION}.md"}
    ) and "__pycache__" not in Path(name).parts and not name.endswith((".pyc", ".pyo")))
    required = {"custom_components/doems/planner_72h.py", "custom_components/doems/planner_72h_runtime.py",
                "custom_components/doems/brand/icon.png", "custom_components/doems/manifest.json"}
    assert required <= set(selected), "new source files must be tracked before packaging"
    output = ROOT / "build"
    output.mkdir(exist_ok=True)
    archive = output / "doems.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for name in selected:
            package.write(ROOT / name, name)
    with zipfile.ZipFile(archive) as package:
        assert package.testzip() is None
        assert json.loads(package.read("custom_components/doems/manifest.json"))["version"] == VERSION
        assert all(".." not in Path(name).parts and not name.startswith("/") for name in package.namelist())
        for name, expected in provenance["protected_blobs"].items():
            from validate_plan72_release import git_blob_sha
            assert git_blob_sha(package.read(name)) == expected
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  doems.zip\n")
    provenance.update(commit=commit, generated_at=datetime.now(timezone.utc).isoformat(),
                      archive_sha256=digest, packaged_files=len(selected), physical_execution_enabled=False)
    (output / "RELEASE_PROVENANCE.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))
    return archive


if __name__ == "__main__":
    build()
