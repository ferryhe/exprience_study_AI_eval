"""Build the C4 sandbox image and verify its frozen local digest."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soa_benchmark.sandbox_docker import docker_executable  # noqa: E402


IMAGE_TAG = "soa-benchmark-codegen-c4:1.0.0"
POLICY_PATH = ROOT / "configs/sandbox/codegen-c4-v1.json"


def main() -> int:
    docker = docker_executable()
    if docker is None:
        print("FAIL: Docker CLI is unavailable.", file=sys.stderr)
        return 2
    environment = os.environ.copy()
    environment["PATH"] = str(Path(docker).parent) + os.pathsep + environment.get("PATH", "")
    build = subprocess.run(
        [
            docker,
            "build",
            "--pull=false",
            "--provenance=false",
            "--tag",
            IMAGE_TAG,
            str(ROOT / "sandbox/codegen-c4"),
        ],
        cwd=ROOT,
        env=environment,
        check=False,
    )
    if build.returncode != 0:
        return build.returncode
    inspect = subprocess.run(
        [docker, "image", "inspect", IMAGE_TAG, "--format", "{{.Id}}"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if inspect.returncode != 0:
        print("FAIL: built image could not be inspected.", file=sys.stderr)
        return 2
    image_digest = inspect.stdout.strip()
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    frozen_digest = policy["isolation"]["image_digest"]
    print(f"built_image_digest={image_digest}")
    print(f"frozen_policy_digest={frozen_digest}")
    if image_digest != frozen_digest:
        print(
            "FAIL: built image differs from the reviewed frozen policy; review and refreeze it.",
            file=sys.stderr,
        )
        return 2
    print("PASS: C4 sandbox image matches the frozen policy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
