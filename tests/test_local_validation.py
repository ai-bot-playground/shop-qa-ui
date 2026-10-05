import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.sandbox import (
    _project_validation_commands,
    _validation_failure_kind,
    validate_file_changes,
    validation_passed_for_repos,
)


class LocalValidationTests(unittest.TestCase):
    def _git_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Test User"],
            check=True,
        )
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )

    def test_gradle_command_is_offline_and_compiles_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper = "gradlew.bat" if os.name == "nt" else "gradlew"
            Path(tmp, wrapper).write_text("", encoding="utf-8")

            commands = _project_validation_commands(tmp)

        self.assertEqual(1, len(commands))
        self.assertIn("--offline", commands[0])
        self.assertIn("classes", commands[0])
        self.assertIn("testClasses", commands[0])
        self.assertNotIn("test", commands[0])

    def _gradle_repo(self, tmp: str, build_gradle: str) -> None:
        Path(tmp, "gradlew.bat" if os.name == "nt" else "gradlew").write_text("", encoding="utf-8")
        Path(tmp, "build.gradle").write_text(build_gradle, encoding="utf-8")

    def test_plain_cucumber_suite_gets_a_dry_run_for_undefined_steps(self):
        # shop-acceptance-tests: bez Springa i Testcontainers, bez własnej bramki na PR.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"SHOPQA_TMP": tmp}):
            self._gradle_repo(tmp, "testImplementation 'io.cucumber:cucumber-junit-platform-engine'\n"
                                   "testImplementation 'io.cucumber:cucumber-picocontainer'\n")
            commands = _project_validation_commands(tmp)
            init_script = Path(commands[1][commands[1].index("--init-script") + 1]).read_text(encoding="utf-8")

        self.assertEqual(2, len(commands))
        self.assertEqual("test", commands[1][-1])
        self.assertIn("--offline", commands[1])
        self.assertIn("cucumber.execution.dry-run", init_script)

    def test_spring_cucumber_suite_is_only_compiled(self):
        # Serwisy: dry-run postawiłby kontekst Springa z Testcontainers — bez dockera pada.
        with tempfile.TemporaryDirectory() as tmp:
            self._gradle_repo(tmp, "testImplementation 'io.cucumber:cucumber-junit-platform-engine'\n"
                                   "testImplementation 'io.cucumber:cucumber-spring'\n"
                                   "testImplementation 'org.testcontainers:postgresql'\n")
            commands = _project_validation_commands(tmp)

        self.assertEqual(1, len(commands))

    def test_node_commands_install_from_cache_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "package.json").write_text(
                '{"scripts": {"build": "vite build"}}', encoding="utf-8"
            )
            Path(tmp, "package-lock.json").write_text("{}", encoding="utf-8")

            commands = _project_validation_commands(tmp)

        self.assertEqual(2, len(commands))
        self.assertIn("ci", commands[0])
        self.assertIn("--offline", commands[0])
        self.assertEqual(["run", "build"], commands[1][1:])

    def test_missing_offline_dependency_is_environment_failure(self):
        output = "npm error code ENOTCACHED: cache mode is 'only-if-cached'"

        self.assertEqual("environment", _validation_failure_kind(["npm", "ci"], output))
        self.assertEqual("code", _validation_failure_kind(["gradlew", "classes"], "error: ';' expected"))

    def test_gradle_loopback_failure_is_environment_not_code(self):
        # Realna awaria na tej maszynie: Selector.open() nie zestawia pary socketów
        # na loopbacku, więc każdy build Gradle pada niezależnie od kodu.
        output = (
            "FAILURE: Build failed with an exception.\n\n* What went wrong:\n"
            "java.io.IOException: Unable to establish loopback connection\n"
        )

        self.assertEqual(
            "environment",
            _validation_failure_kind(["gradlew.bat", "--offline", "classes"], output),
        )

    def test_invalid_json_fails_before_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git_repo(repo)

            result = validate_file_changes(
                [{"path": "config.json", "content": "{not-json}"}],
                str(repo),
            )

        self.assertFalse(result["success"])
        self.assertIn("Błąd składni", result["error"])
        self.assertEqual([], result["commands"])

    def test_static_validation_accepts_valid_new_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._git_repo(repo)

            result = validate_file_changes(
                [{"path": "config.json", "content": '{"enabled": true}'}],
                str(repo),
                timeout=30,
            )

        self.assertTrue(result["success"], result)
        self.assertFalse(result["project_check"])
        self.assertTrue(any("diff --check" in command for command in result["commands"]))

    def test_all_changed_repositories_must_have_green_result(self):
        results = {
            "shop-order": {"success": True},
            "shop-payment": {"success": False},
        }

        self.assertFalse(validation_passed_for_repos(results, ["shop-order", "shop-payment"]))
        self.assertFalse(validation_passed_for_repos(results, ["shop-order", "shop-gateway"]))
        self.assertTrue(validation_passed_for_repos(results, ["shop-order"]))
        self.assertFalse(validation_passed_for_repos(results, []))


class GateLogExcerptTests(unittest.TestCase):
    # Kształt prawdziwego logu `preprod-gate / gate` z API jobów (shop-gateway PR #7).
    LOG = "\n".join([
        "﻿2026-10-05T14:00:03.5635252Z Acquired preprod-gate lock; this gate now owns the shared cluster.",
        "2026-10-05T14:01:01.2413206Z     java.lang.IllegalStateException: HTTP 404 for PUT http://localhost:8080/api/inventory/7",
        "2026-10-05T14:01:01.5384797Z 3 tests completed, 3 failed",
        "2026-10-05T14:01:08.6884453Z \x1b[31;1macceptance suite failed\x1b[0m",
        "2026-10-05T14:01:08.8019827Z ##[error]Process completed with exit code 1.",
        "2026-10-05T14:01:12.4715451Z ##[group]Run Remove-Item -Force image.tar",
        "2026-10-05T14:01:13.0000000Z Post job cleanup.",
    ])

    def test_excerpt_ends_at_first_error_not_at_cleanup(self):
        from src.sandbox import job_log_failure_excerpt

        excerpt = job_log_failure_excerpt(self.LOG, max_lines=4)

        self.assertIn("HTTP 404 for PUT", excerpt)
        self.assertIn("acceptance suite failed", excerpt)
        self.assertTrue(excerpt.endswith("##[error]Process completed with exit code 1."))
        self.assertNotIn("Post job cleanup", excerpt)
        self.assertNotIn("2026-10-05T", excerpt)
        self.assertNotIn("\x1b[", excerpt)

    def test_log_failed_format_keeps_the_step_name(self):
        # `gh run view --log-failed`: job<TAB>krok<TAB>znacznik czasu + linia (shop-ui PR #11).
        from src.sandbox import job_log_failure_excerpt
        log = "\n".join([
            "gate\tSetup Node\t﻿2026-10-05T14:41:16.3067901Z Extracting ...",
            "gate\tSetup Node\t2026-10-05T14:41:25.6073007Z AssignProcessToJobObject: (6) The handle is invalid.",
            "gate\tSetup Node\t2026-10-05T14:41:25.6080000Z ##[error]The process '7zr.exe' failed with exit code 2",
            "gate\tCleanup candidate artifacts\t2026-10-05T14:41:27.3751302Z podman : Error: image not known",
        ])

        excerpt = job_log_failure_excerpt(log, max_lines=10)

        self.assertIn("[Setup Node] AssignProcessToJobObject", excerpt)
        self.assertNotIn("Cleanup candidate artifacts", excerpt)


if __name__ == "__main__":
    unittest.main()