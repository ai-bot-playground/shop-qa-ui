import copy
import csv
import os
import subprocess
from pathlib import Path

STATIC_TESTS = [
    # ── apply_discount (billing.py) ─────────────────────────────────────────
    {
        "name": "apply_discount: PROMO10 → 10% z 100 zł = 10 zł",
        "fn": "apply_discount",
        "args": (100, "PROMO10"),
        "expected": 10.0,
    },
    {
        "name": "apply_discount: VIP20 → 20% z 100 zł = 20 zł",
        "fn": "apply_discount",
        "args": (100, "VIP20"),
        "expected": 20.0,
    },
    {
        "name": "apply_discount: STAFF50 → 50% z 100 zł = 50 zł",
        "fn": "apply_discount",
        "args": (100, "STAFF50"),
        "expected": 50.0,
    },
    {
        "name": "apply_discount: nieznany kod → brak rabatu (0 zł)",
        "fn": "apply_discount",
        "args": (100, "UNKNOWN"),
        "expected": 0.0,
    },
    # ── calculate_total (billing.py) ────────────────────────────────────────
    {
        "name": "calculate_total: 100 zł + 23% VAT = 123.0 zł",
        "fn": "calculate_total",
        "args": (100,),
        "expected": 123.0,
    },
    {
        "name": "calculate_total: 0 zł → 0 zł",
        "fn": "calculate_total",
        "args": (0,),
        "expected": 0.0,
    },
    # ── check_stock (inventory.py) ───────────────────────────────────────────
    {
        "name": "check_stock: SKU-001 → 100 szt.",
        "fn": "check_stock",
        "args": ("SKU-001",),
        "expected": 100,
    },
    {
        "name": "check_stock: nieznane SKU → 0",
        "fn": "check_stock",
        "args": ("SKU-999",),
        "expected": 0,
    },
    # ⚠️ FALSE POSITIVE EXAMPLE — błąd w teście, nie w kodzie.
    # apply_discount zwraca procent kwoty total, a nie kwotę po rabacie.
    # Ten test błędnie zakłada że funkcja zwróci kwotę po odjęciu rabatu.
    {
        "name": "⚠️ apply_discount: wynik po rabacie czy kwota rabatu? (błędny test)",
        "fn": "apply_discount",
        "args": (100, "PROMO10"),
        "expected": 90.0,  # zakłada cenę po rabacie — BŁĘDNE; funkcja zwraca 10.0
    },
]


def run_static_tests(source_code: str) -> list[dict]:
    """Execute source_code and run all STATIC_TESTS against it."""
    # Pre-populate globals that legacy modules reference at module level
    namespace: dict = {
        "TAX_RATE": 0.23,
        "STOCK": {"SKU-001": 100, "SKU-002": 45, "SKU-003": 0, "SKU-004": 200, "SKU-005": 12},
    }
    try:
        exec(compile(source_code, "<sandbox>", "exec"), namespace)
    except Exception as e:
        return [
            {
                "name": t["name"],
                "passed": False,
                "expected": t["expected"],
                "got": None,
                "error": f"Błąd kompilacji: {e}",
            }
            for t in STATIC_TESTS
            if t["fn"] in source_code
        ]

    results = []
    for test in STATIC_TESTS:
        fn_name = test["fn"]
        if fn_name not in namespace:
            continue

        # deep-copy mutable args so tests don't interfere with each other
        args = copy.deepcopy(test["args"])
        try:
            got = namespace[fn_name](*args)
            passed = got == test["expected"]
            results.append({
                "name": test["name"],
                "passed": passed,
                "expected": test["expected"],
                "got": got,
                "error": None,
            })
        except Exception as e:
            results.append({
                "name": test["name"],
                "passed": False,
                "expected": test["expected"],
                "got": None,
                "error": str(e),
            })

    return results


def replace_function_in_file(chunk, new_source: str, repo_path: str) -> str:
    """Overwrite the function's lines in the original file with new_source."""
    abs_path = os.path.join(repo_path, chunk.file_path)
    with open(abs_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = new_source.splitlines(keepends=True)
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"

    updated = lines[: chunk.start_line - 1] + new_lines + lines[chunk.end_line :]
    with open(abs_path, "w", encoding="utf-8") as f:
        f.writelines(updated)

    return abs_path


def git_commit_file(file_path: str, message: str, repo_path: str) -> dict:
    """Stage file_path and commit it in the git repo containing repo_path."""
    try:
        root_result = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        git_root = root_result.stdout.strip()

        subprocess.run(
            ["git", "-C", git_root, "add", file_path],
            capture_output=True, text=True, check=True,
        )

        commit_result = subprocess.run(
            ["git", "-C", git_root, "commit", "-m", message],
            capture_output=True, text=True, check=True,
        )

        # Extract short hash from output like "[branch abc1234] message"
        first_line = commit_result.stdout.splitlines()[0] if commit_result.stdout else ""
        commit_hash = ""
        if first_line:
            import re
            match = re.search(r"\b([0-9a-f]{7,})\b", first_line)
            commit_hash = match.group(1) if match else first_line

        return {"success": True, "commit_hash": commit_hash, "output": commit_result.stdout}

    except subprocess.CalledProcessError as e:
        return {"success": False, "commit_hash": "", "output": e.stderr or e.stdout or str(e)}


def commit_and_push_change(
    abs_path: str,
    message: str,
    repo_path: str,
    branch_prefix: str = "ai-sandbox",
) -> dict:
    """Commit abs_path on the current branch, then push that commit to a NEW
    remote branch ``<branch_prefix>/<timestamp>`` (without switching local
    branches, via ``HEAD:refs/heads/...``).

    Pushing this branch is what triggers the GitHub Actions pipeline
    (.github/workflows/sandbox-pr.yml), which rebuilds the image, validates the
    change in Docker, and opens a PR to ``develop``.

    Auth: uses GH_TOKEN / GITHUB_TOKEN from the environment if present (needed
    inside the container); otherwise relies on the ambient git credentials
    (e.g. a developer's ``gh`` login when running the app on the host). On push
    failure the change is still committed locally and ``manual_push_cmd`` tells
    the user how to push it by hand.
    """
    import re
    from datetime import datetime

    commit = git_commit_file(abs_path, message, repo_path)
    if not commit["success"]:
        return {**commit, "pushed": False, "branch": "", "manual_push_cmd": ""}

    branch = f"{branch_prefix}/{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    refspec = f"HEAD:refs/heads/{branch}"

    git_root = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    ).stdout.strip() or repo_path

    remote_url = subprocess.run(
        ["git", "-C", git_root, "remote", "get-url", "origin"],
        capture_output=True, text=True,
    ).stdout.strip()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    push_target, sanitized = "origin", "origin"
    if token and remote_url.startswith("https://"):
        host_path = re.sub(r"^https://([^@]+@)?", "", remote_url)
        push_target = f"https://x-access-token:{token}@{host_path}"
        sanitized = f"https://x-access-token:***@{host_path}"

    push = subprocess.run(
        ["git", "-C", git_root, "push", push_target, refspec],
        capture_output=True, text=True,
    )

    return {
        "success": True,
        "commit_hash": commit["commit_hash"],
        "branch": branch,
        "pushed": push.returncode == 0,
        "push_target": sanitized,
        "output": (push.stderr or push.stdout).strip(),
        "manual_push_cmd": f"git push origin {refspec}",
    }


def run_qa_eval(symbol: str, repo_path: str) -> list[dict]:
    """Run questions from questions.csv that are relevant to the given symbol.

    Finds the CSV in repo_path, filters rows whose expected_answer_location
    contains the symbol name, runs run_qa for each, and scores the answer
    against expected_keywords.
    """
    from .agent import run_qa

    csv_path = Path(repo_path) / "questions.csv"
    if not csv_path.exists():
        return []

    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    relevant = [r for r in rows if symbol in r.get("expected_answer_location", "")]
    if not relevant:
        return []

    results = []
    for row in relevant:
        try:
            qa_result = run_qa(row["question"], repo_path)
            answer = qa_result["answer"]
        except Exception as exc:
            answer = f"ERROR: {exc}"

        answer_lower = answer.lower()
        keywords = [k.strip() for k in row["expected_keywords"].split(",")]

        if row["answer_type"].strip() == "refusal":
            passed = any(
                phrase in answer_lower
                for phrase in ("not found", "cannot", "nie znaleziono", "brak")
            )
            matched = []
        else:
            matched = [k for k in keywords if k.lower() in answer_lower]
            passed = len(matched) == len(keywords)

        results.append({
            "id": row["id"].strip(),
            "question": row["question"].strip(),
            "answer_type": row["answer_type"].strip(),
            "expected_keywords": keywords,
            "matched_keywords": matched,
            "answer": answer,
            "passed": passed,
        })

    return results


# ── Etap 3/4: zmiana jako diff → PR do naszego repo → status bramki preprod ──
def _git_root(repo_path: str) -> str:
    r = subprocess.run(["git", "-C", repo_path, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return r.stdout.strip() or repo_path


def check_diff_applies(diff_text: str, repo_path: str) -> tuple[bool, str]:
    """`git apply --check` diffa względem repo_path. Zwraca (ok, komunikat)."""
    import tempfile
    if not diff_text.strip():
        return False, "Pusty diff (w trybie demo realny diff nie jest generowany)."
    root = _git_root(repo_path)
    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False,
                                     encoding="utf-8", newline="\n") as tf:
        tf.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        patch = tf.name
    try:
        r = subprocess.run(["git", "-C", root, "apply", "--check", patch],
                           capture_output=True, text=True)
        return r.returncode == 0, (r.stderr or r.stdout).strip() or "OK"
    finally:
        os.unlink(patch)


def _clone_base() -> str:
    """Writable base dir for throwaway clones.

    NOT the system %TEMP%: on locked-down corporate Windows, EDR/AV often blocks
    git.exe from creating a work tree there (Python can mkdir, git cannot →
    'could not create work tree dir ... Permission denied'). Default to a folder
    under the user's home; override with SHOPQA_TMP.
    """
    base = os.environ.get("SHOPQA_TMP") or os.path.join(os.path.expanduser("~"), ".shopqa-tmp")
    os.makedirs(base, exist_ok=True)
    return base


def open_pr_for_change(diff_text: str, title: str, body: str, repo_slug: str,
                       base: str = "main", branch_prefix: str = "ai-change") -> dict:
    """Sklonuj repo_slug, zaaplikuj diff na nowej gałęzi, wypchnij i otwórz PR do `base`.

    Działa na jednorazowym klonie (temp), więc robocze kopie użytkownika są
    nietknięte. PR do `main` odpala bramkę preprod sklepu. Auth: gh / GH_TOKEN.
    """
    import shutil
    import tempfile
    from datetime import datetime

    if not diff_text.strip():
        return {"success": False, "error": "Pusty diff — nic do wystawienia."}

    tmp = tempfile.mkdtemp(prefix="shopqa-", dir=_clone_base())
    branch = f"{branch_prefix}/{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    clone_dir = os.path.join(tmp, "repo")
    patch = os.path.join(tmp, "change.patch")
    try:
        cl = subprocess.run(
            ["gh", "repo", "clone", repo_slug, clone_dir, "--",
             "--depth", "1", "--branch", base],
            capture_output=True, text=True,
        )
        if cl.returncode != 0:
            return {"success": False, "error": f"clone: {cl.stderr.strip()}"}

        with open(patch, "w", encoding="utf-8", newline="\n") as f:
            f.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")

        chk = subprocess.run(["git", "-C", clone_dir, "apply", "--check", patch],
                             capture_output=True, text=True)
        if chk.returncode != 0:
            return {"success": False,
                    "error": f"diff nie aplikuje się: {(chk.stderr or chk.stdout).strip()}"}

        for cmd in (
            ["git", "-C", clone_dir, "checkout", "-b", branch],
            ["git", "-C", clone_dir, "apply", patch],
            ["git", "-C", clone_dir, "add", "-A"],
            ["git", "-C", clone_dir, "commit", "-m", title],
            ["git", "-C", clone_dir, "push", "-u", "origin", branch],
        ):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                return {"success": False, "branch": branch,
                        "error": f"{cmd[3]}: {(r.stderr or r.stdout).strip()}"}

        pr = subprocess.run(
            ["gh", "pr", "create", "--repo", repo_slug, "--base", base,
             "--head", branch, "--title", title, "--body", body],
            capture_output=True, text=True,
        )
        if pr.returncode != 0:
            return {"success": True, "branch": branch, "pr_url": "",
                    "warning": f"branch wypchnięty, PR nieautomatyczny: {pr.stderr.strip()}"}
        return {"success": True, "branch": branch, "pr_url": pr.stdout.strip()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pr_checks(repo_slug: str, branch: str) -> dict:
    """Status checków PR-a dla gałęzi (bramka preprod-gate). Best-effort."""
    import json as _json
    r = subprocess.run(
        ["gh", "pr", "checks", branch, "--repo", repo_slug,
         "--json", "name,state,bucket,link"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 and not r.stdout.strip():
        return {"available": False, "message": (r.stderr or "brak danych").strip(), "checks": []}
    try:
        return {"available": True, "checks": _json.loads(r.stdout or "[]")}
    except Exception:
        return {"available": False, "message": "nie udało się odczytać statusu", "checks": []}


def pr_failure_summary(repo_slug: str, branch: str, max_lines: int = 40) -> str:
    """Best-effort opis błędu z CI dla gałęzi PR: tail logu nieudanych kroków.

    Pusty string gdy logu nie ma (np. self-hosted runner bywa nie zachowuje
    logów w API) — wtedy UI pokazuje przynajmniej nazwy nieudanych checków.
    """
    import json as _json
    r = subprocess.run(
        ["gh", "run", "list", "--repo", repo_slug, "--branch", branch, "--limit", "1",
         "--json", "databaseId,conclusion"],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return ""
    try:
        runs = _json.loads(r.stdout)
    except Exception:
        return ""
    if not runs:
        return ""
    rid = str(runs[0].get("databaseId", ""))
    if not rid:
        return ""
    lg = subprocess.run(["gh", "run", "view", rid, "--repo", repo_slug, "--log-failed"],
                        capture_output=True, text=True)
    out = (lg.stdout or "").strip()
    if not out:
        return ""
    return "\n".join(out.splitlines()[-max_lines:])


def merge_pr(repo_slug: str, branch: str, strategy: str = "--squash") -> dict:
    """Merge PR-a danej gałęzi do base (domyślnie squash) i usuń gałąź. Auth: gh."""
    r = subprocess.run(
        ["gh", "pr", "merge", branch, "--repo", repo_slug, strategy, "--delete-branch"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"success": False, "error": (r.stderr or r.stdout).strip()}
    return {"success": True, "output": r.stdout.strip()}


# ── Niezawodna ścieżka zmiany: pełna treść pliku → git liczy diff (bez „corrupt patch") ──
def compute_diff(old: str, new: str, rel_path: str) -> str:
    """Podglądowy unified diff (difflib) — tylko do wyświetlenia w UI."""
    import difflib
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
    ))


def _resolve_local_repo(local_repo: str | None, repo_slug: str) -> str | None:
    """Ścieżka do LOKALNEGO klonu serwisu. Najpierw jawnie podany `local_repo`,
    potem SHOP_REPOS_DIR/<nazwa-repo> (domyślnie ../ai-bot-playground)."""
    candidates = []
    if local_repo:
        candidates.append(local_repo)
    name = repo_slug.split("/")[-1]
    base_dir = os.environ.get("SHOP_REPOS_DIR", os.path.join("..", "ai-bot-playground"))
    candidates.append(os.path.join(base_dir, name))
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return os.path.abspath(c)
    return None


def run_service_tests(repo_path: str, file_changes: list[tuple[str, str]],
                      base: str = "main", timeout: int = 1800) -> dict:
    """Odpala `./gradlew test` dla serwisu Z ZASTOSOWANĄ zmianą, w izolowanym worktree.

    `file_changes` to lista (rel_path, new_content) — wszystkie pliki tego repo,
    które zmienia bieżąca propozycja. Worktree bazuje na świeżym origin/<base>, więc
    testujemy dokładnie to, co pójdzie do PR-a (czysto względem main + nasza zmiana).
    Robocza kopia użytkownika pozostaje nietknięta.

    Zwraca: {success, build_ok, summary, tail, duration_s, error}.
    """
    import shutil
    import time
    import uuid
    from datetime import datetime

    if not os.path.isdir(os.path.join(repo_path, ".git")):
        return {"success": False, "error": f"To nie jest repo git: {repo_path}"}

    gradlew = os.path.join(repo_path, "gradlew")
    if not os.path.isfile(gradlew):
        return {"success": False, "error": "Brak ./gradlew — serwis nie używa Gradle."}

    branch = f"ai-test/{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    wt = os.path.join(_clone_base(), f"wt-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}")
    worktree_added = False
    t0 = time.time()
    try:
        # --prune czyści zepsute/nieistniejące już refy zdalne (np. po usunięciu
        # gałęzi ai-change), które inaczej wywalają fetch „bad object".
        f = subprocess.run(["git", "-C", repo_path, "fetch", "--prune", "origin", base],
                           capture_output=True, text=True)
        if f.returncode != 0:
            return {"success": False, "error": f"fetch origin {base}: {f.stderr.strip()}"}

        wadd = subprocess.run(
            ["git", "-C", repo_path, "worktree", "add", "--detach", wt, f"origin/{base}"],
            capture_output=True, text=True)
        if wadd.returncode != 0:
            return {"success": False, "error": f"worktree add: {wadd.stderr.strip()}"}
        worktree_added = True

        # Nałóż wszystkie zmienione pliki tego repo.
        for rel_path, new_content in file_changes:
            target = os.path.join(wt, rel_path.replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(new_content if new_content.endswith("\n") else new_content + "\n")

        # gradlew test (Testcontainers wymaga Dockera; toolchain może dociągnąć JDK).
        # Uruchamiamy przez `sh gradlew` — w świeżym worktree skrypt bywa bez bitu
        # wykonywalności (+x), więc `./gradlew` rzucałby PermissionError.
        try:
            r = subprocess.run(
                ["sh", "gradlew", "test", "--console=plain", "--no-daemon"],
                cwd=wt, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "build_ok": False,
                    "error": f"Przekroczono limit {timeout}s — testy zbyt długie.",
                    "duration_s": round(time.time() - t0)}
        except OSError as exc:
            return {"success": False, "build_ok": False,
                    "error": f"Nie udało się uruchomić gradlew: {exc}",
                    "duration_s": round(time.time() - t0)}

        out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
        build_ok = r.returncode == 0
        # Wyłuskaj zwięzłe podsumowanie z logu Gradle/JUnit, jeśli jest.
        summary_lines = [ln for ln in out.splitlines()
                         if "tests completed" in ln.lower() or "BUILD SUCCESSFUL" in ln
                         or "BUILD FAILED" in ln or " failed" in ln.lower()]
        summary = " · ".join(summary_lines[-3:]) if summary_lines else (
            "BUILD SUCCESSFUL" if build_ok else "BUILD FAILED")
        tail = "\n".join(out.splitlines()[-40:])
        return {
            "success": build_ok, "build_ok": build_ok, "summary": summary.strip(),
            "tail": tail, "duration_s": round(time.time() - t0),
        }
    finally:
        if worktree_added:
            subprocess.run(["git", "-C", repo_path, "worktree", "remove", "--force", wt],
                           capture_output=True, text=True)
        shutil.rmtree(wt, ignore_errors=True)


def open_pr_for_files(file_changes: list[dict], title: str, body: str,
                      repo_slug: str, base: str = "main",
                      branch_prefix: str = "ai-change",
                      local_repo: str | None = None) -> dict:
    """JEDEN PR dla repo zbierający WIELE plików. `file_changes` to lista dictów
    {path, content, allow_create}. Wszystkie pliki lądują w jednej gałęzi/commicie.

    `git worktree` izoluje operację: bieżąca kopia robocza i gałąź pozostają
    nietknięte, a nowa gałąź bazuje na świeżo pobranym origin/<base> (PR czysty
    względem main). git sam liczy diff/commit. Auth: gh.
    """
    import shutil
    import uuid
    from datetime import datetime

    writable = [fc for fc in file_changes if (fc.get("content") or "").strip()]
    if not writable:
        return {"success": False, "error": "Brak treści plików — nic do wystawienia."}

    repo = _resolve_local_repo(local_repo, repo_slug)
    if not repo:
        return {"success": False,
                "error": f"Nie znaleziono lokalnego repo dla {repo_slug} "
                         f"(ustaw SHOP_REPOS_DIR lub przekaż local_repo)."}

    branch = f"{branch_prefix}/{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    # Ścieżka worktree poza %TEMP% (EDR blokuje tam git); git sam ją utworzy.
    wt = os.path.join(_clone_base(), f"wt-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}")
    worktree_added = False
    try:
        # Świeży base z origin (--prune czyści zepsute refy), by gałąź była czysta wzgl. main.
        f = subprocess.run(["git", "-C", repo, "fetch", "--prune", "origin", base],
                           capture_output=True, text=True)
        if f.returncode != 0:
            return {"success": False, "error": f"fetch origin {base}: {f.stderr.strip()}"}

        wadd = subprocess.run(
            ["git", "-C", repo, "worktree", "add", "-b", branch, wt, f"origin/{base}"],
            capture_output=True, text=True)
        if wadd.returncode != 0:
            return {"success": False, "error": f"worktree add: {wadd.stderr.strip()}"}
        worktree_added = True

        for fc in writable:
            rel_path = fc["path"]
            content = fc["content"]
            target = os.path.join(wt, rel_path.replace("/", os.sep))
            if not os.path.isfile(target):
                if not fc.get("allow_create"):
                    return {"success": False, "error": f"plik nie istnieje w {base}: {rel_path}"}
                os.makedirs(os.path.dirname(target), exist_ok=True)  # nowy plik
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content if content.endswith("\n") else content + "\n")

        stt = subprocess.run(["git", "-C", wt, "status", "--porcelain"],
                             capture_output=True, text=True)
        if not stt.stdout.strip():
            return {"success": False, "error": f"Brak zmian względem origin/{base} (treść identyczna)."}

        for cmd in (
            ["git", "-C", wt, "add", "-A"],
            ["git", "-C", wt, "commit", "-m", title],
            ["git", "-C", wt, "push", "-u", "origin", branch],
        ):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                return {"success": False, "branch": branch,
                        "error": f"{cmd[3]}: {(r.stderr or r.stdout).strip()}"}

        pr = subprocess.run(
            ["gh", "pr", "create", "--repo", repo_slug, "--base", base, "--head", branch,
             "--title", title, "--body", body], capture_output=True, text=True)
        if pr.returncode != 0:
            return {"success": True, "branch": branch, "pr_url": "",
                    "warning": f"branch wypchnięty, PR nieautomatyczny: {pr.stderr.strip()}"}
        return {"success": True, "branch": branch, "pr_url": pr.stdout.strip()}
    finally:
        # Sprzątanie: usuń worktree i lokalną gałąź (jest już na origin).
        if worktree_added:
            subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt],
                           capture_output=True, text=True)
            subprocess.run(["git", "-C", repo, "branch", "-D", branch],
                           capture_output=True, text=True)
        shutil.rmtree(wt, ignore_errors=True)


def open_pr_for_file_change(rel_path: str, new_content: str, title: str, body: str,
                            repo_slug: str, base: str = "main",
                            branch_prefix: str = "ai-change",
                            local_repo: str | None = None,
                            allow_create: bool = False) -> dict:
    """Cienki wrapper na open_pr_for_files dla pojedynczego pliku (kompatybilność)."""
    return open_pr_for_files(
        [{"path": rel_path, "content": new_content, "allow_create": allow_create}],
        title, body, repo_slug, base, branch_prefix, local_repo,
    )
