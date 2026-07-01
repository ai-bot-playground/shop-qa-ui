import os
import subprocess


def _clone_base() -> str:
    """Writable base dir for throwaway worktrees.

    NOT the system %TEMP%: on locked-down corporate Windows, EDR/AV often blocks
    git.exe from creating a work tree there. Default to a folder under the user's
    home; override with SHOPQA_TMP.
    """
    base = os.environ.get("SHOPQA_TMP") or os.path.join(os.path.expanduser("~"), ".shopqa-tmp")
    os.makedirs(base, exist_ok=True)
    return base


def open_pr_for_change(diff_text: str, title: str, body: str, repo_slug: str,
                       base: str = "main", branch_prefix: str = "ai-change") -> dict:
    """Sklonuj repo_slug, zaaplikuj diff na nowej gałęzi, wypchnij i otwórz PR do `base`."""
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
