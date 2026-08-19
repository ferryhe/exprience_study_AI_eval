from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from soa_benchmark.sandbox_docker import (  # noqa: E402
    DockerSandboxUnavailable,
    docker_backend_available,
    docker_executable,
    run_docker_evaluation,
)

DIGEST = "sha256:" + "a" * 64
POLICY = {
    "isolation": {"image_digest": DIGEST},
    "resource_limits": {
        "cpu_seconds": 30,
        "disk_mb": 128,
        "file_count": 200,
        "memory_mb": 512,
        "output_bytes": 1000000,
        "pids": 32,
        "wall_clock_seconds": 60,
    },
    "test_gates": {
        "deterministic_repetitions": 2,
        "exfiltration_suite_id": "codegen-exfiltration-v1",
        "hidden_protocol": "external_black_box",
        "hidden_suite_id": "c4-hidden-actuarial-v1",
        "prompt_injection_suite_id": "codegen-prompt-injection-v1",
        "public_suite_id": "c4-public-v1",
    },
}


def _completed(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _inspect_document(subject_root: Path) -> bytes:
    document = [
        {
            "HostConfig": {
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges=true"],
            },
            "Config": {
                "User": "65532:65532",
                "Env": ["PYTHONDONTWRITEBYTECODE=1", "PYTHONHASHSEED=0"],
            },
            "Mounts": [
                {
                    "Source": str(subject_root.resolve()),
                    "Destination": "/subject",
                    "RW": False,
                }
            ],
        }
    ]
    return json.dumps(document).encode("utf-8")


class DockerExecutableTests(unittest.TestCase):
    def test_docker_executable_prefers_path(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            self.assertEqual(docker_executable(), "/usr/bin/docker")

    def test_docker_executable_returns_none_when_missing(self) -> None:
        with (
            patch("shutil.which", return_value=None),
            patch.dict("os.environ", {}, clear=True),
        ):
            self.assertIsNone(docker_executable())

    def test_backend_available_with_live_daemon(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "soa_benchmark.sandbox_docker._run_cli",
                return_value=_completed(stdout=b"25.0.3\n"),
            ),
        ):
            self.assertTrue(docker_backend_available())

    def test_backend_unavailable_without_daemon_response(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "soa_benchmark.sandbox_docker._run_cli",
                return_value=_completed(stderr=b"cannot connect", returncode=1),
            ),
        ):
            self.assertFalse(docker_backend_available())

    def test_backend_unavailable_when_info_raises(self) -> None:
        with (
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "soa_benchmark.sandbox_docker._run_cli",
                side_effect=OSError("daemon socket missing"),
            ),
        ):
            self.assertFalse(docker_backend_available())


class DockerEvaluationTests(unittest.TestCase):
    @staticmethod
    def _subject_root(directory: str) -> Path:
        root = Path(directory) / "subject"
        root.mkdir()
        (root / "solution.py").write_text("VALUE = 1\n", encoding="utf-8")
        return root

    def _fake_cli(self, subject_root: Path, image_ok: bool = True):
        def cli(docker: str, arguments: list[str], **kwargs):
            if arguments[:2] == ["image", "inspect"]:
                if image_ok:
                    return _completed(stdout=(DIGEST + "\n").encode())
                return _completed(stderr=b"no such image", returncode=1)
            if arguments[:2] == ["container", "inspect"]:
                return _completed(stdout=_inspect_document(subject_root))
            if arguments[:2] == ["container", "start"]:
                return _completed(
                    stdout=json.dumps(
                        {"ok": False, "error": "synthetic bridge failure"}
                    ).encode()
                )
            return _completed()

        return cli

    def test_failing_subject_fails_gates_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            subject_root = self._subject_root(directory)
            with (
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch(
                    "soa_benchmark.sandbox_docker.docker_backend_available",
                    return_value=True,
                ),
                patch(
                    "soa_benchmark.sandbox_docker._run_cli",
                    side_effect=self._fake_cli(subject_root),
                ),
            ):
                evaluation = run_docker_evaluation(
                    policy=POLICY,
                    subject_root=subject_root,
                    evaluation_id="synthetic-evaluation",
                    source_file_count=1,
                    source_bytes=10,
                )
        self.assertEqual(evaluation.machine_disposition, "failed")
        self.assertEqual(
            evaluation.execution["failure_code"], "public_tests_failed"
        )
        self.assertIn("public_tests_failed", evaluation.failure_codes)
        self.assertIn("hidden_actuarial_tests_failed", evaluation.failure_codes)
        self.assertIn("prompt_injection_tests_failed", evaluation.failure_codes)
        self.assertTrue(evaluation.execution["attempted"])
        self.assertTrue(evaluation.execution["backend_available"])
        summary = json.loads(evaluation.stdout)
        self.assertEqual(summary["container_runs"], 5)
        self.assertEqual(
            summary["suite_status"],
            {
                "public": "failed",
                "hidden_actuarial": "failed",
                "prompt_injection": "failed",
                "exfiltration": "passed",
                "reproducibility": "passed",
            },
        )

    def test_missing_digest_pinned_image_blocks_evaluation(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            subject_root = self._subject_root(directory)
            with (
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch(
                    "soa_benchmark.sandbox_docker.docker_backend_available",
                    return_value=True,
                ),
                patch(
                    "soa_benchmark.sandbox_docker._run_cli",
                    side_effect=self._fake_cli(subject_root, image_ok=False),
                ),
                self.assertRaises(DockerSandboxUnavailable) as captured,
            ):
                run_docker_evaluation(
                    policy=POLICY,
                    subject_root=subject_root,
                    evaluation_id="synthetic-evaluation",
                    source_file_count=1,
                    source_bytes=10,
                )
        self.assertEqual(captured.exception.code, "docker_image_unavailable")

    def test_backend_unavailable_blocks_before_image_check(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            subject_root = self._subject_root(directory)
            with (
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch(
                    "soa_benchmark.sandbox_docker.docker_backend_available",
                    return_value=False,
                ),
                self.assertRaises(DockerSandboxUnavailable) as captured,
            ):
                run_docker_evaluation(
                    policy=POLICY,
                    subject_root=subject_root,
                    evaluation_id="synthetic-evaluation",
                    source_file_count=1,
                    source_bytes=10,
                )
        self.assertEqual(captured.exception.code, "docker_backend_unavailable")

    def test_container_names_include_per_process_entropy(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            subject_root = self._subject_root(directory)
            names: list[str] = []

            def cli(docker: str, arguments: list[str], **kwargs):
                if arguments[:2] == ["container", "create"]:
                    names.append(arguments[arguments.index("--name") + 1])
                return self._fake_cli(subject_root)(docker, arguments, **kwargs)

            with (
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch(
                    "soa_benchmark.sandbox_docker.docker_backend_available",
                    return_value=True,
                ),
                patch("soa_benchmark.sandbox_docker._run_cli", side_effect=cli),
            ):
                run_docker_evaluation(
                    policy=POLICY,
                    subject_root=subject_root,
                    evaluation_id="shared-id",
                    source_file_count=1,
                    source_bytes=10,
                )
                first_batch = list(names)
                run_docker_evaluation(
                    policy=POLICY,
                    subject_root=subject_root,
                    evaluation_id="shared-id",
                    source_file_count=1,
                    source_bytes=10,
                )
        self.assertEqual(len(names), 10)
        self.assertEqual(len(set(names)), 10)
        self.assertEqual(len(first_batch), 5)
        for name in names:
            self.assertRegex(name, r"^soa-c4-[0-9a-f]{12}$")
        for first, second in zip(first_batch, names[5:]):
            self.assertNotEqual(first, second)


class IsolationEvidenceTests(unittest.TestCase):
    def _run_with_evidence_mutation(self, mutate) -> DockerSandboxUnavailable:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            subject_root = Path(directory) / "subject"
            subject_root.mkdir()
            document = json.loads(_inspect_document(subject_root))

            def cli(docker: str, arguments: list[str], **kwargs):
                if arguments[:2] == ["image", "inspect"]:
                    return _completed(stdout=(DIGEST + "\n").encode())
                if arguments[:2] == ["container", "inspect"]:
                    mutated = json.loads(json.dumps(document))
                    mutate(mutated[0])
                    return _completed(stdout=json.dumps(mutated).encode())
                return _completed()

            with (
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch(
                    "soa_benchmark.sandbox_docker.docker_backend_available",
                    return_value=True,
                ),
                patch("soa_benchmark.sandbox_docker._run_cli", side_effect=cli),
                self.assertRaises(DockerSandboxUnavailable) as captured,
            ):
                run_docker_evaluation(
                    policy=POLICY,
                    subject_root=subject_root,
                    evaluation_id="synthetic-evaluation",
                    source_file_count=0,
                    source_bytes=0,
                )
            return captured.exception

    def test_network_enabled_fails_isolation_verification(self) -> None:
        error = self._run_with_evidence_mutation(
            lambda doc: doc["HostConfig"].update({"NetworkMode": "bridge"})
        )
        self.assertEqual(error.code, "docker_isolation_verification_failed")
        self.assertIn("network_disabled", str(error))

    def test_repository_mount_fails_isolation_verification(self) -> None:
        def mutate(doc):
            doc["Mounts"].append(
                {"Source": "/repo", "Destination": "/repo", "RW": True}
            )

        error = self._run_with_evidence_mutation(mutate)
        self.assertEqual(error.code, "docker_isolation_verification_failed")
        self.assertIn("repository_not_mounted", str(error))
        self.assertIn("secrets_absent", str(error))

    def test_root_user_fails_isolation_verification(self) -> None:
        error = self._run_with_evidence_mutation(
            lambda doc: doc["Config"].update({"User": "root"})
        )
        self.assertEqual(error.code, "docker_isolation_verification_failed")
        self.assertIn("non_root_user", str(error))

    def test_secret_environment_fails_isolation_verification(self) -> None:
        error = self._run_with_evidence_mutation(
            lambda doc: doc["Config"]["Env"].append("OPENAI_API_KEY=redacted")
        )
        self.assertEqual(error.code, "docker_isolation_verification_failed")
        self.assertIn("secrets_absent", str(error))

    def test_container_create_failure_maps_error_code(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "runs") as directory:
            subject_root = Path(directory) / "subject"
            subject_root.mkdir()

            def cli(docker: str, arguments: list[str], **kwargs):
                if arguments[:2] == ["image", "inspect"]:
                    return _completed(stdout=(DIGEST + "\n").encode())
                if arguments[:2] == ["container", "create"]:
                    return _completed(
                        stderr=b"name is already in use", returncode=1
                    )
                return _completed()

            with (
                patch("shutil.which", return_value="/usr/bin/docker"),
                patch(
                    "soa_benchmark.sandbox_docker.docker_backend_available",
                    return_value=True,
                ),
                patch("soa_benchmark.sandbox_docker._run_cli", side_effect=cli),
                self.assertRaises(DockerSandboxUnavailable) as captured,
            ):
                run_docker_evaluation(
                    policy=POLICY,
                    subject_root=subject_root,
                    evaluation_id="synthetic-evaluation",
                    source_file_count=0,
                    source_bytes=0,
                )
        self.assertEqual(captured.exception.code, "docker_container_create_failed")
        self.assertIn("already in use", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
