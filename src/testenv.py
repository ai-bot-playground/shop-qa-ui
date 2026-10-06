"""Środowisko testowe na Kubernetes dla jednej zmiany — ZANIM powstanie PR.

Product Owner opisuje zmianę, agent ją generuje i waliduje lokalnie, a ten moduł
wdraża ją na osobny namespace klastra `kind-preprod` i daje PO linki do działającej
aplikacji. Dopiero gdy PO potwierdzi, że działa, aplikacja wystawia PR (i dalej
bramka `preprod-gate` + merge, jak dotąd).

Dlaczego osobny namespace, a nie wspólny preprod: kandydat wdrożony na preprod
przez bramkę zostaje tam tylko do następnej bramki dowolnego repo — PO mógłby
oglądać już nie swoją zmianę. Namespace `test-<id>` ma pełny, własny stos
(Postgres/Redis/Kafka + serwisy) z chartu `shop-infra/helm`; zmienione serwisy
dostają obrazy kandydackie, reszta — obrazy bazowe z `main` (promote).

Wymaga tego samego co bramka: podman, kind, kubectl, helm na PATH i lokalnego
klonu `shop-infra`. Działa wyłącznie w wariancie natywnym (run-local.ps1).
"""

import os
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from src.sandbox import _clone_base, _safe_relative_path

CONTEXT = os.environ.get("QA_TEST_ENV_CONTEXT", "kind-preprod")
KIND_CLUSTER = os.environ.get("QA_TEST_ENV_KIND_CLUSTER", "preprod")
HELM_TIMEOUT = os.environ.get("QA_TEST_ENV_HELM_TIMEOUT", "10m")

# Linki dla PO: sklep (nginx w shop-ui proxuje /api do gatewaya w TYM SAMYM
# namespace) oraz bezpośrednio gateway — do sprawdzania endpointów w przeglądarce.
_FORWARDS = {"ui": ("svc/shop-ui", 80, "/"), "api": ("svc/shop-gateway", 8080, "/actuator/health")}


def _infra_dir() -> str:
    root = os.environ.get("SHOP_REPOS_DIR") or str(Path(__file__).resolve().parents[2])
    return os.path.join(root, "shop-infra")


def chart_services(infra_dir: str | None = None) -> set[str]:
    """Serwisy wdrażane przez chart (klucze `services:` w helm/values.yaml)."""
    import yaml
    path = os.path.join(infra_dir or _infra_dir(), "helm", "values.yaml")
    try:
        with open(path, encoding="utf-8") as fh:
            return set((yaml.safe_load(fh) or {}).get("services") or {})
    except OSError:
        return set()


def new_namespace() -> str:
    """`test-MMDD-HHMMSS-xxxx` — poprawna nazwa DNS-1123, unikalna per zmiana."""
    return f"test-{datetime.now():%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"


def _run(cmd: list[str], log: list[str], timeout: int = 1800, env: dict | None = None) -> bool:
    log.append(f"> {subprocess.list2cmdline(cmd)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.append(f"!! {exc}")
        return False
    out = "\n".join(filter(None, [r.stdout, r.stderr])).strip()
    if out:
        log.append(out[-4000:])
    return r.returncode == 0


def _build_candidate(repo: str, local_repo: str, files: list[dict], image: str, log: list[str]) -> bool:
    """Obraz z lokalnego HEAD + wygenerowanych plików (jak walidacja, tylko `podman build`)."""
    worktree = os.path.join(_clone_base(), f"testenv-{uuid.uuid4().hex[:10]}")
    if not _run(["git", "-C", local_repo, "worktree", "add", "--detach", worktree, "HEAD"], log):
        return False
    try:
        for f in files:
            rel = _safe_relative_path(f.get("path") or f.get("file_path") or "")
            content = f.get("content") if f.get("content") is not None else f.get("new_content")
            if content is None:
                continue
            target = os.path.join(worktree, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(content if content.endswith("\n") else content + "\n")
        return _run(["podman", "build", "-t", image, worktree], log)
    finally:
        _run(["git", "-C", local_repo, "worktree", "remove", "--force", worktree], log)
        shutil.rmtree(worktree, ignore_errors=True)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _probe(url: str, timeout: float = 3) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


def start_links(namespace: str) -> dict:
    """Port-forwardy do UI i gatewaya na wolnych portach localhost. Zwraca {urls, pids}."""
    urls, pids = {}, {}
    for name, (target, remote, _health) in _FORWARDS.items():
        port = _free_port()
        proc = subprocess.Popen(
            ["kubectl", "--context", CONTEXT, "-n", namespace, "port-forward", target, f"{port}:{remote}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        urls[name] = f"http://localhost:{port}"
        pids[name] = proc.pid
    return {"urls": urls, "pids": pids}


def links_alive(env: dict) -> dict[str, bool]:
    return {name: _probe(env["urls"][name].rstrip("/") + _FORWARDS[name][2])
            for name in env.get("urls", {})}


def _stop_pids(pids: dict) -> None:
    for pid in (pids or {}).values():
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, 15)
        except Exception:
            pass


def reconnect_links(env: dict) -> dict:
    """Port-forward ginie przy restarcie poda — nowe linki (porty mogą się zmienić)."""
    _stop_pids(env.get("pids"))
    env.update(start_links(env["namespace"]))
    deadline = time.time() + 30
    while time.time() < deadline and not all(links_alive(env).values()):
        time.sleep(2)
    return env


def deploy_test_env(changes_by_repo: dict[str, dict], namespace: str | None = None) -> dict:
    """Wdróż zmianę na świeży namespace i zwróć linki dla PO.

    `changes_by_repo`: {repo: {"repo_path": ..., "files": [{path, content}]}}.
    Repozytoria spoza chartu (np. shop-acceptance-tests) nie są wdrażane — to nie
    jest działająca aplikacja; trafiają do `skipped`.
    """
    namespace = namespace or new_namespace()
    infra = _infra_dir()
    services = chart_services(infra)
    log: list[str] = []
    result = {"success": False, "namespace": namespace, "images": {}, "skipped": [],
              "urls": {}, "pids": {}, "log": log, "error": ""}

    deployable = {r: c for r, c in changes_by_repo.items() if r in services}
    result["skipped"] = sorted(set(changes_by_repo) - set(deployable))
    if not deployable:
        result["error"] = "Zmiana nie dotyczy żadnego wdrażanego serwisu — nie ma czego pokazać na środowisku."
        return result

    for repo, change in deployable.items():
        image = f"localhost/{repo}:{namespace}"
        if not _build_candidate(repo, change["repo_path"], change["files"], image, log):
            result["error"] = f"Budowa obrazu {repo} nie powiodła się."
            return result
        result["images"][repo] = image

    tar = os.path.join(_clone_base(), f"{namespace}-images.tar")
    kind_env = {**os.environ, "KIND_EXPERIMENTAL_PROVIDER": "podman"}
    try:
        if not _run(["podman", "save", "-o", tar, *result["images"].values()], log):
            result["error"] = "podman save nie powiódł się."
            return result
        if not _run(["kind", "load", "image-archive", tar, "--name", KIND_CLUSTER], log, env=kind_env):
            result["error"] = f"kind load do klastra {KIND_CLUSTER} nie powiódł się."
            return result
    finally:
        if os.path.exists(tar):
            os.remove(tar)

    helm = ["helm", "upgrade", "--install", "shop", os.path.join(infra, "helm"),
            "--kube-context", CONTEXT, "-n", namespace, "--create-namespace",
            "-f", os.path.join(infra, "helm", "values.yaml"),
            "-f", os.path.join(infra, "helm", "values-preprod.yaml"),
            # Środowisko PO nie potrzebuje własnego Prometheusa/Grafany.
            "--set", "observability.enabled=false",
            "--wait", "--timeout", HELM_TIMEOUT]
    for repo, image in result["images"].items():
        helm += ["--set-string", f"services.{repo}.image={image}"]
    if not _run(helm, log):
        result["error"] = f"helm install w namespace {namespace} nie powiódł się."
        return result

    result.update(start_links(namespace))
    deadline = time.time() + 60
    while time.time() < deadline and not all(links_alive(result).values()):
        time.sleep(2)
    alive = links_alive(result)
    if not all(alive.values()):
        result["error"] = f"Środowisko stoi, ale linki nie odpowiadają: {alive}."
        return result
    result["success"] = True
    return result


def destroy_test_env(env: dict) -> bool:
    """Zamknij linki i usuń namespace (z całym stosem). Obrazów w węźle nie ruszamy."""
    _stop_pids(env.get("pids"))
    log = env.setdefault("log", [])
    ok = _run(["kubectl", "--context", CONTEXT, "delete", "namespace", env["namespace"],
               "--wait=false"], log, timeout=120)
    for image in (env.get("images") or {}).values():
        _run(["podman", "rmi", image], log, timeout=120)
    return ok
