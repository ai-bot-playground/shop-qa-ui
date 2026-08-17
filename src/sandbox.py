import os
import subprocess
from pathlib import Path


def _clone_base() -> str:
    """Writable base dir for throwaway worktrees.

    NOT the system %TEMP%: on locked-down corporate Windows, EDR/AV often blocks
    git.exe from creating a work tree there. Default to a folder under the user's
    home; override with SHOPQA_TMP.
    """
    base = os.environ.get("SHOPQA_TMP") or os.path.join(os.path.expanduser("~"), ".shopqa-tmp")
    os.makedirs(base, exist_ok=True)
    return base


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
    """Best-effort opis błędu z CI dla gałęzi PR: tail logu nieudanych kroków."""
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


def compute_diff(old: str, new: str, rel_path: str) -> str:
    """Podglądowy unified diff (difflib) — tylko do wyświetlenia w UI."""
    import difflib
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel_path}", tofile=f"b/{rel_path}",
    ))


def _safe_relative_path(raw_path: str) -> str:
    """Normalize a generated path and reject absolute/path-traversal targets."""
    from pathlib import PurePosixPath

    normalized = (raw_path or "").replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (not normalized or path.is_absolute() or ".." in path.parts
            or (path.parts and ":" in path.parts[0])):
        raise ValueError(f"Niebezpieczna ścieżka pliku: {raw_path!r}")
    return path.as_posix()


def _content_syntax_error(rel_path: str, content: str) -> str:
    """Return a cheap, deterministic syntax error for formats we can parse locally."""
    import json

    suffix = os.path.splitext(rel_path)[1].lower()
    try:
        if suffix == ".json":
            json.loads(content)
        elif suffix in (".yml", ".yaml") and "{{" not in content and "{%" not in content:
            import yaml
            yaml.safe_load(content)
        elif suffix == ".py":
            compile(content, rel_path, "exec")
    except Exception as exc:
        return f"{rel_path}: {exc}"
    return ""


def _project_validation_commands(worktree: str) -> list[list[str]]:
    """Offline build commands for the repository type present in `worktree`."""
    gradle = "gradlew.bat" if os.name == "nt" else "gradlew"
    gradle_path = os.path.join(worktree, gradle)
    if os.path.isfile(gradle_path):
        return [[gradle_path, "--offline", "--no-daemon", "classes", "testClasses"]]

    package_json = os.path.join(worktree, "package.json")
    if os.path.isfile(package_json):
        import json
        try:
            with open(package_json, encoding="utf-8") as fh:
                scripts = (json.load(fh).get("scripts") or {})
        except (OSError, ValueError):
            scripts = {}
        if "build" in scripts:
            npm = "npm.cmd" if os.name == "nt" else "npm"
            commands: list[list[str]] = []
            if os.path.isfile(os.path.join(worktree, "package-lock.json")):
                commands.append([
                    npm, "ci", "--offline", "--ignore-scripts", "--no-audit", "--fund=false",
                ])
            commands.append([npm, "run", "build"])
            return commands

    if any(os.path.isfile(os.path.join(worktree, name)) for name in (
        "pyproject.toml", "requirements.txt", "setup.py",
    )):
        import sys
        return [[sys.executable, "-m", "compileall", "-q", "."]]
    return []


def _validation_failure_kind(command: list[str], output: str) -> str:
    """Classify dependency/tooling failures so they are not sent to the code-repair LLM."""
    text = (output or "").lower()
    environment_markers = (
        "enotcached",
        "cache mode is 'only-if-cached'",
        "no cached version",
        "could not resolve all files",
        "could not install gradle distribution",
        "could not find a java installation",
        "java_home",
        "is not recognized as an internal or external command",
        "command not found",
        "cannot find module",
        "toolchain download repositories have not been configured",
        # Gradle/JVM nie potrafi zestawić pary socketów na loopbacku (Selector.open()).
        # Typowo oprogramowanie ochronne łączące się do świeżo otwartych portów
        # localhost — nie ma to NIC wspólnego z wygenerowanym kodem, więc nie może
        # trafić do LLM jako błąd do naprawy.
        "unable to establish loopback connection",
        "unable to start the daemon process",
        "could not connect to the gradle daemon",
    )
    if any(marker in text for marker in environment_markers):
        return "environment"
    return "code"


def validate_file_changes(file_changes: list[dict], local_repo: str,
                          timeout: int = 600) -> dict:
    """Validate generated files in a detached local worktree, without network or PRs.

    `file_changes` accepts `{path|file_path, content|new_content}` dictionaries.
    Gradle validation compiles main and test sources but does not execute component
    tests, so it does not start Testcontainers or local services.
    """
    import shutil
    import uuid

    result = {
        "success": False,
        "commands": [],
        "output": "",
        "error": "",
        "project_check": False,
        "failure_kind": "",
    }
    if not os.path.isdir(os.path.join(local_repo or "", ".git")):
        result["error"] = f"Nie znaleziono lokalnego repo: {local_repo}"
        result["failure_kind"] = "environment"
        return result

    normalized: list[tuple[str, str]] = []
    try:
        for change in file_changes:
            rel_path = _safe_relative_path(change.get("path") or change.get("file_path") or "")
            content = change.get("content")
            if content is None:
                content = change.get("new_content")
            if content is None:
                continue
            syntax_error = _content_syntax_error(rel_path, str(content))
            if syntax_error:
                result["error"] = f"Błąd składni: {syntax_error}"
                result["failure_kind"] = "code"
                return result
            normalized.append((rel_path, str(content)))
    except ValueError as exc:
        result["error"] = str(exc)
        result["failure_kind"] = "input"
        return result

    if not normalized:
        result["error"] = "Brak wygenerowanych plików do walidacji."
        result["failure_kind"] = "input"
        return result

    worktree = os.path.join(_clone_base(), f"validate-{uuid.uuid4().hex[:10]}")
    added = False
    outputs: list[str] = []
    try:
        add = subprocess.run(
            ["git", "-C", local_repo, "worktree", "add", "--detach", worktree, "HEAD"],
            capture_output=True, text=True,
        )
        if add.returncode != 0:
            result["error"] = f"worktree add: {(add.stderr or add.stdout).strip()}"
            result["failure_kind"] = "environment"
            return result
        added = True

        worktree_root = os.path.abspath(worktree)
        for rel_path, content in normalized:
            target = os.path.abspath(os.path.join(worktree_root, *rel_path.split("/")))
            if os.path.commonpath((worktree_root, target)) != worktree_root:
                result["error"] = f"Ścieżka wychodzi poza worktree: {rel_path}"
                result["failure_kind"] = "input"
                return result
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content if content.endswith("\n") else content + "\n")

        intent = subprocess.run(
            ["git", "-C", worktree, "add", "--intent-to-add", "--all"],
            capture_output=True, text=True,
        )
        if intent.returncode != 0:
            result["error"] = f"git add --intent-to-add: {(intent.stderr or intent.stdout).strip()}"
            result["failure_kind"] = "environment"
            return result

        commands = [["git", "-C", worktree, "diff", "--check"]]
        project_commands = _project_validation_commands(worktree)
        commands.extend(project_commands)
        result["project_check"] = bool(project_commands)

        env = os.environ.copy()
        env["CI"] = "true"
        for command in commands:
            display = subprocess.list2cmdline(command)
            result["commands"].append(display)
            try:
                completed = subprocess.run(
                    command,
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                )
            except subprocess.TimeoutExpired as exc:
                partial = "\n".join(filter(None, [exc.stdout or "", exc.stderr or ""]))
                result["output"] = "\n\n".join(outputs + [partial]).strip()
                result["error"] = f"Przekroczono limit {timeout}s: {display}"
                result["failure_kind"] = "environment"
                return result
            except OSError as exc:
                result["output"] = "\n\n".join(outputs).strip()
                result["error"] = f"Nie można uruchomić `{display}`: {exc}"
                result["failure_kind"] = "environment"
                return result
            output = "\n".join(filter(None, [completed.stdout, completed.stderr])).strip()
            outputs.append(f"> {display}\n{output}".rstrip())
            if completed.returncode != 0:
                result["output"] = "\n\n".join(outputs).strip()
                result["error"] = f"Walidacja nie przeszła (exit {completed.returncode})."
                result["failure_kind"] = _validation_failure_kind(command, output)
                return result

        result["success"] = True
        result["output"] = "\n\n".join(outputs).strip()
        return result
    finally:
        if added:
            subprocess.run(
                ["git", "-C", local_repo, "worktree", "remove", "--force", worktree],
                capture_output=True, text=True,
            )
        shutil.rmtree(worktree, ignore_errors=True)


def validation_passed_for_repos(results: dict, repos) -> bool:
    """True only when every changed repository has a current green result."""
    required = set(repos)
    return bool(required) and all(
        bool((results.get(repo) or {}).get("success")) for repo in required
    )


def _resolve_local_repo(local_repo: str | None, repo_slug: str) -> str | None:
    """Ścieżka do LOKALNEGO klonu serwisu. Najpierw jawnie podany `local_repo`,
    potem SHOP_REPOS_DIR/<nazwa-repo>.

    Fallback liczony jest od położenia TEGO pliku (src/ → shop-qa-ui/ → workspace),
    a nie od cwd: repozytoria `shop-*` leżą jako rodzeństwo shop-qa-ui, więc
    dawne `../ai-bot-playground` nie trafiało w nic niezależnie od katalogu startu.
    """
    candidates = []
    if local_repo:
        candidates.append(local_repo)
    name = repo_slug.split("/")[-1]
    default_root = Path(__file__).resolve().parents[2]
    base_dir = os.environ.get("SHOP_REPOS_DIR") or str(default_root)
    candidates.append(os.path.join(base_dir, name))
    for c in candidates:
        if c and os.path.isdir(os.path.join(c, ".git")):
            return os.path.abspath(c)
    return None


def open_pr_for_files(file_changes: list[dict], title: str, body: str,
                      repo_slug: str, base: str = "main",
                      branch_prefix: str = "ai-change",
                      local_repo: str | None = None) -> dict:
    """JEDEN PR dla repo zbierający WIELE plików. `file_changes` to lista dictów
    {path, content, allow_create}. Wszystkie pliki lądują w jednej gałęzi/commicie.
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
    wt = os.path.join(_clone_base(), f"wt-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}")
    worktree_added = False
    try:
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
                os.makedirs(os.path.dirname(target), exist_ok=True)
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
        if worktree_added:
            subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt],
                           capture_output=True, text=True)
            subprocess.run(["git", "-C", repo, "branch", "-D", branch],
                           capture_output=True, text=True)
        shutil.rmtree(wt, ignore_errors=True)


