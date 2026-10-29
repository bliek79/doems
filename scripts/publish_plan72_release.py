"""Publish a new pre-release only; API failures never count as absence."""
from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request

from validate_plan72_release import ROOT, VERSION, validate


def require_absent(repository: str, resource: str, token: str) -> None:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/{resource}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raise RuntimeError(f"Refusing to replace an existing resource: {resource} ({response.status})")
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise RuntimeError(f"GitHub lookup failed with HTTP {error.code}; publication blocked") from error


def publish() -> None:
    validate()
    repository = os.environ["GITHUB_REPOSITORY"]
    commit = os.environ["GITHUB_SHA"]
    assert os.environ["GITHUB_REF"] == "refs/heads/doems3-publish-alpha-5-1"
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() == commit
    token = os.environ["GH_TOKEN"]
    tag = "v" + VERSION
    require_absent(repository, "git/ref/tags/" + tag, token)
    require_absent(repository, "releases/tags/" + tag, token)
    for name in ("doems.zip", "SHA256SUMS.txt", "RELEASE_PROVENANCE.json"):
        assert (ROOT / "build" / name).is_file()
    import json
    metadata = json.loads((ROOT / "build/RELEASE_PROVENANCE.json").read_text())
    assert metadata["commit"] == commit and metadata["version"] == VERSION
    import hashlib
    assert hashlib.sha256((ROOT / "build/doems.zip").read_bytes()).hexdigest() == metadata["archive_sha256"]
    subprocess.run([
        "gh", "release", "create", tag,
        "build/doems.zip", "build/SHA256SUMS.txt", "build/RELEASE_PROVENANCE.json",
        "--target", commit, "--prerelease", "--latest=false",
        "--title", "DOEMS 3.0 - Alpha 5.1 - Plan72",
        "--notes-file", f"RELEASE_NOTES_v{VERSION}.md",
    ], cwd=ROOT, check=True)


if __name__ == "__main__":
    publish()
