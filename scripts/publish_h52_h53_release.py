"""Publish a new, verified H5.1 alpha pre-release; never replace a tag."""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import zipfile
from publish_plan_store_release import require_absent
from validate_scheduler_release import ROOT, VERSION, validate

BRANCH = "doems3-publish-alpha-8-10-h52-h53"
BASE = "86810c70e380004c31bf13cfa9a12951cb64bf7a"


def publish():
    checks = validate()
    assert VERSION == "0.3.0-alpha.8.10"
    assert os.environ["GITHUB_REPOSITORY"] == "bliek79/doems"
    assert os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH
    commit = os.environ["GITHUB_SHA"]
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == commit
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=True)
    tag = "v" + VERSION
    token = os.environ["GH_TOKEN"]
    require_absent("bliek79/doems", "git/ref/tags/" + tag, token)
    require_absent("bliek79/doems", "releases/tags/" + tag, token)
    outputs = [ROOT / "build" / file for file in ("doems.zip", "SHA256SUMS.txt", "RELEASE_PROVENANCE.json")]
    assert all(p.is_file() for p in outputs)
    info = json.loads(outputs[2].read_text())
    assert info["version"] == VERSION and info["commit"] == commit
    assert info["physical_execution_enabled"] is False
    assert info["protected_blobs"] == checks["protected_blobs"]
    checksum = hashlib.sha256(outputs[0].read_bytes()).hexdigest()
    assert info["archive_sha256"] == checksum
    assert outputs[1].read_text().strip() == checksum + "  doems.zip"
    with zipfile.ZipFile(outputs[0]) as z:
        assert z.testzip() is None
        assert json.loads(z.read("custom_components/doems/manifest.json"))["version"] == VERSION
        assert b"DOEMSSolarForecastRemainingTodaySensor" in z.read("custom_components/doems/solar_sensor.py")
    subprocess.run([
        "gh", "release", "create", tag, *(str(p) for p in outputs),
        "--target", commit, "--prerelease", "--latest=false",
        "--title", "DOEMS 3.0 alpha.8.10 - H5.2 Safety Timing and H5.3 SOC Resolution",
        "--notes-file", f"RELEASE_NOTES_v{VERSION}.md",
    ], cwd=ROOT, check=True)


if __name__ == "__main__":
    publish()
