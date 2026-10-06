"""`open_pr_for_files` — PR powstaje z `origin/main`, nie z lokalnego HEAD.

To rozróżnienie jest istotne, bo PR niesie PEŁNĄ treść pliku (nie patcha).
Gdy lokalny klon zostaje w tyle — a zostaje, choćby po merge'u poprzedniego
PR-a z tego samego UI — wysłanie pliku zbudowanego na starej treści CICHO
cofnęłoby zmianę, która trafiła do `main` w międzyczasie.

Testy używają prawdziwego gita na lokalnym „origin" (repo bare w tempie);
jedyne, co jest podstawione, to `gh` — żeby test nigdy nie dotknął GitHuba.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import sandbox

FILE = "src/main/java/com/shop/payment/PaymentService.java"

V1 = """\
package com.shop.payment;

class PaymentService {
    void charge(long orderId) {
    }
}
"""

# Zmiana, która trafiła do `main` z innego PR-a, gdy lokalny klon już stał.
V2_IN_MAIN = V1.replace("    void charge(long orderId) {\n    }",
                        "    void charge(long orderId) {\n        audit(orderId);\n    }")

GENERATED = V1.replace("class PaymentService {",
                       "class PaymentService {\n    // zmiana wygenerowana przez agenta")


def _git(*args: str, cwd: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {result.stderr or result.stdout}")
    return result.stdout


class PullRequestBaseDriftTests(unittest.TestCase):
    """Lokalny klon za `origin/main` nie może cicho nadpisać cudzej zmiany."""

    def setUp(self) -> None:
        # `gh` jest zablokowane dla CAŁEJ klasy, nie per test: gdyby strażnik
        # rozjazdu kiedyś przestał działać, test bez tej blokady poleciałby
        # tworzyć PR-a na prawdziwym GitHubie.
        self.pushed: list[str] = []
        real_run = subprocess.run

        def guarded_run(cmd, *args, **kwargs):
            if cmd and cmd[0] == "gh":
                return subprocess.CompletedProcess(cmd, 1, "", "gh: zablokowane w teście")
            if cmd[:2] == ["git", "-C"] and "push" in cmd:
                self.pushed.append(cmd[-1])
            return real_run(cmd, *args, **kwargs)

        patcher = mock.patch.object(sandbox.subprocess, "run", side_effect=guarded_run)
        patcher.start()
        self.addCleanup(patcher.stop)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)

        # „origin" — zwykłe repo z gałęzią main (bare nie pozwala na commit w treści).
        self.origin = str(root / "origin")
        _git("init", "-b", "main", self.origin)
        _git("config", "user.email", "t@example.com", cwd=self.origin)
        _git("config", "user.name", "T", cwd=self.origin)
        _git("config", "receive.denyCurrentBranch", "ignore", cwd=self.origin)
        target = Path(self.origin, FILE)
        target.parent.mkdir(parents=True)
        target.write_text(V1, encoding="utf-8")
        _git("add", "-A", cwd=self.origin)
        _git("commit", "-m", "init", cwd=self.origin)

        # Lokalny klon agenta.
        self.clone = str(root / "shop-payment")
        _git("clone", self.origin, self.clone)
        _git("config", "user.email", "t@example.com", cwd=self.clone)
        _git("config", "user.name", "T", cwd=self.clone)

    def _advance_origin(self) -> None:
        """`main` w origin idzie do przodu; lokalny klon o tym nie wie."""
        Path(self.origin, FILE).write_text(V2_IN_MAIN, encoding="utf-8")
        _git("add", "-A", cwd=self.origin)
        _git("commit", "-m", "inny PR zmienil ten sam plik", cwd=self.origin)

    def _open_pr(self, base_content: str | None):
        change = {"path": FILE, "content": GENERATED, "allow_create": False}
        if base_content is not None:
            change["base_content"] = base_content
        return sandbox.open_pr_for_files(
            [change], "feat: zmiana", "body",
            "ai-bot-playground/shop-payment", local_repo=self.clone,
        )

    def test_refuses_when_the_file_moved_in_origin_main(self):
        self._advance_origin()

        result = self._open_pr(base_content=V1)   # agent widział jeszcze V1

        self.assertFalse(result["success"], result)
        self.assertIn("origin/main", result["error"])
        self.assertIn(FILE, result["error"])
        # Najważniejsze: nowa treść z origin/main nadal tam jest — nic nie wypchnięto.
        self.assertEqual(V2_IN_MAIN, Path(self.origin, FILE).read_text(encoding="utf-8"))
        self.assertEqual(
            [], _git("branch", "--list", "ai-change/*", cwd=self.origin).split(),
            "gałąź PR-a nie powinna powstać",
        )

    def test_pushes_when_local_clone_matches_origin_main(self):
        result = self._open_pr(base_content=V1)

        self.assertTrue(result["success"], result)
        self.assertTrue(result["branch"].startswith("ai-change/"), result)
        self.assertEqual([result["branch"]], self.pushed, "gałąź nie została wypchnięta")
        self.assertIn("warning", result, "brak PR-a przez gh powinien być zgłoszony jako warning")

        pushed_content = _git("show", f"{result['branch']}:{FILE}", cwd=self.origin)
        self.assertEqual(GENERATED.rstrip("\n"), pushed_content.rstrip("\n"))

    def test_without_base_content_the_check_is_skipped(self):
        """Zgodność wstecz: starsi wołający nie przekazują `base_content`."""
        self._advance_origin()

        result = self._open_pr(base_content=None)

        self.assertTrue(result["success"], result)

    def test_missing_file_still_needs_allow_create(self):
        result = sandbox.open_pr_for_files(
            [{"path": "src/NoSuchFile.java", "content": "class X {}", "base_content": ""}],
            "feat: nowy plik", "body",
            "ai-bot-playground/shop-payment", local_repo=self.clone,
        )

        self.assertFalse(result["success"])
        self.assertIn("nie istnieje w main", result["error"])


class PullRequestInputTests(unittest.TestCase):
    def test_empty_content_is_not_a_pull_request(self):
        result = sandbox.open_pr_for_files(
            [{"path": "a.java", "content": "   "}], "t", "b", "org/repo",
        )

        self.assertFalse(result["success"])
        self.assertIn("Brak treści", result["error"])

    def test_unknown_local_repo_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = sandbox.open_pr_for_files(
                [{"path": "a.java", "content": "class A {}"}], "t", "b",
                "org/repo", local_repo=os.path.join(tmp, "nope"),
            )

        self.assertFalse(result["success"])
        self.assertIn("Nie znaleziono lokalnego repo", result["error"])


if __name__ == "__main__":
    unittest.main()
