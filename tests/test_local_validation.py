import os
import subprocess
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()