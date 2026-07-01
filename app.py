import json
import os
import sys
import uuid
from collections import Counter
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd
from src.ingest import ingest_repo, ingest_app
from src.agent import (
    run_qa, generate_code_fix, fix_code_with_tests, generate_change_diff,
    generate_file_change, plan_change, build_repo_map, generate_new_file,
    verify_completeness,
)
from src.sandbox import (
    compute_diff, open_pr_for_files, pr_checks, merge_pr, run_service_tests,
    pr_failure_summary,
)
from src.answer_types import ANSWER_TYPES, get_default_templates


def _lang_for(path: str) -> str:
    """Syntax-highlight language for st.code, derived from the file extension."""
    p = (path or "").lower()
    if p.endswith(".java"):
        return "java"
    if p.endswith((".jsx", ".tsx", ".js", ".ts", ".mjs")):
        return "javascript"
    if p.endswith(".css"):
        return "css"
    if p.endswith((".html", ".htm")):
        return "html"
    if p.endswith((".yml", ".yaml")):
        return "yaml"
    return "python"


def _pr_build_state(data: dict | None) -> str:
    """Agreguje statusy checków PR (z pr_checks) do jednego: success|pending|failure|unknown."""
    if not data or not data.get("available"):
        return "unknown"
    checks = data.get("checks", [])
    if not checks:
        return "pending"  # bramka jeszcze nie wystartowała
    buckets = [(c.get("bucket") or c.get("state") or "").lower() for c in checks]
    if any(b in ("fail", "failure", "error", "cancelled", "timed_out") for b in buckets):
        return "failure"
    if any(b in ("pending", "", "queued", "in_progress", "running", "none", "waiting", "expected", "startup_failure") for b in buckets):
        return "pending"
    if all(b in ("pass", "success", "skipping", "skipped", "neutral") for b in buckets):
        return "success"
    return "pending"


st.set_page_config(
    page_title="shop-qa-ui",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Accenture CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
button[kind="primary"] {
    background-color: #A100FF !important;
    border-color: #A100FF !important;
    color: white !important;
}
button[kind="primary"]:hover {
    background-color: #8500D4 !important;
    border-color: #8500D4 !important;
}
button[kind="secondary"] {
    border-color: #A100FF !important;
    color: #A100FF !important;
}
button[kind="secondary"]:hover {
    background-color: #F3E5FF !important;
}
</style>
""", unsafe_allow_html=True)

# ── Session state init ────────────────────────────────────────────────────────
def _new_session(name: str | None = None) -> dict:
    now = datetime.now().strftime("%d.%m %H:%M")
    return {"id": str(uuid.uuid4()), "name": name or f"Wątek {now}", "messages": []}

if "sessions" not in st.session_state:
    st.session_state.sessions = [_new_session("Wątek główny")]
if "active_session_id" not in st.session_state:
    st.session_state.active_session_id = st.session_state.sessions[0]["id"]
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "ready"
if "answer_templates" not in st.session_state:
    st.session_state.answer_templates = get_default_templates()
if "answer_mode" not in st.session_state:
    st.session_state.answer_mode = "business"

def _active_session() -> dict:
    sid = st.session_state.active_session_id
    return next((s for s in st.session_state.sessions if s["id"] == sid),
                st.session_state.sessions[0])

def _active_messages() -> list:
    return _active_session()["messages"]

# Trwała historia pytań — append-only JSONL (przetrwa restart aplikacji,
# w przeciwieństwie do st.session_state). Jedna linia = jedno zapytanie.
_QLOG_PATH = os.path.join(os.path.dirname(__file__), "logs", "questions.jsonl")

def _log_question(question: str, result: dict, app_id: str | None) -> None:
    """Best-effort zapis pytania do questions.jsonl. Nigdy nie psuje UI."""
    try:
        os.makedirs(os.path.dirname(_QLOG_PATH), exist_ok=True)
        chunks = result.get("retrieved_chunks", []) or []
        feas = result.get("feasibility") or {}
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "session_id": st.session_state.active_session_id,
            "app": app_id,
            "question": question,
            "repos_hit": sorted({c.repo for c in chunks if c.repo}),
            "citations": [f"{c.repo}/{c.file_path}:{c.start_line}" for c in chunks],
            "impacted_services": feas.get("impacted_services", []),
        }
        with open(_QLOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass  # historia jest pomocnicza — cisza przy awarii

# ── Workflow steps ─────────────────────────────────────────────────────────────
STEPS = [
    ("ready",   "System Ready"),
    ("analyze", "Analyze"),
    ("sandbox", "Piaskownica"),
    ("pr",      "PR"),
]
STEP_KEYS = [k for k, _ in STEPS]

def _completed_steps() -> set:
    done = set()
    if st.session_state.get("chunks"):
        done.add("ready")
    if _active_messages():
        done.add("analyze")
    if st.session_state.get("sandbox_results") or st.session_state.get("sandbox_commit_done"):
        done.add("sandbox")
    if st.session_state.get("sandbox_commit_done"):
        done.add("pr")
    return done

def _advance():
    idx = STEP_KEYS.index(st.session_state.active_tab)
    if idx < len(STEPS) - 1:
        st.session_state.active_tab = STEP_KEYS[idx + 1]
        st.rerun()

def _load_app_options():
    """Czyta manifest.yaml i zwraca (lista_aplikacji, domyślne_id_app).

    Każda aplikacja to dict {id, name, repos: [{name, path}]} gdzie repos
    zawiera tylko repozytoria `indexable: true` z istniejącym katalogiem.
    Ścieżki rozwijane względem `workspace_root` z manifestu (nadpisywalne
    SHOP_REPOS_DIR). Fallback: jedna syntetyczna aplikacja z repo shop-*.
    """
    here = os.path.dirname(__file__)
    env_root = os.environ.get("SHOP_REPOS_DIR")
    manifest = None
    try:
        import yaml
        with open(os.path.join(here, "manifest.yaml"), encoding="utf-8") as fh:
            manifest = yaml.safe_load(fh) or {}
    except Exception:
        manifest = None

    if manifest:
        root = env_root or os.path.abspath(os.path.join(here, manifest.get("workspace_root", "..")))
        apps = []
        for app in manifest.get("apps", []):
            repos = [
                {"name": r["name"], "path": os.path.join(root, r["name"])}
                for r in app.get("repos", [])
                if r.get("indexable") and os.path.isdir(os.path.join(root, r["name"]))
            ]
            if repos:
                apps.append({"id": app["id"], "name": app["name"], "repos": repos})
        default_id = apps[0]["id"] if apps else None
        return apps, default_id

    # Fallback — jedna aplikacja ze skanem shop-* (gdy brak manifestu / PyYAML).
    root = env_root or os.path.abspath(os.path.join(here, ".."))
    repos = []
    if os.path.isdir(root):
        repos = [
            {"name": d, "path": os.path.join(root, d)}
            for d in sorted(os.listdir(root))
            if d.startswith("shop-") and os.path.isdir(os.path.join(root, d))
        ]
    apps = [{"id": "shop", "name": "Sklep (fallback)", "repos": repos}] if repos else []
    return apps, (apps[0]["id"] if apps else None)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🔍 Analizator Kodu")
    st.caption("Wiedza plemienna — odblokowana")
    st.divider()

    # Indeksowanie — selektor aplikacji z manifest.yaml. Wybranie aplikacji
    # indeksuje WSZYSTKIE jej repozytoria naraz; użytkownik nie musi wiedzieć,
    # w którym repo leży kod.
    app_options, default_app_id = _load_app_options()
    chosen_app = None
    if app_options:
        app_ids = [a["id"] for a in app_options]
        default_idx = app_ids.index(default_app_id) if default_app_id in app_ids else 0
        chosen_app_id = st.selectbox(
            "Aplikacja", app_ids, index=default_idx,
            format_func=lambda aid: next((a["name"] for a in app_options if a["id"] == aid), aid),
            help="Indeksuje wszystkie repozytoria aplikacji (z manifest.yaml)",
        )
        chosen_app = next((a for a in app_options if a["id"] == chosen_app_id), None)
        if chosen_app:
            repo_names = [r["name"] for r in chosen_app["repos"]]
            st.caption(f"{len(repo_names)} repo: {', '.join(repo_names)}")

    if st.button("⚡ Indeksuj aplikację", use_container_width=True):
        repos_to_index = chosen_app["repos"] if chosen_app else []
        if not repos_to_index:
            st.error("Brak repozytoriów do zaindeksowania — sprawdź manifest.yaml.")
        else:
            with st.spinner(f"Indeksowanie {len(repos_to_index)} repozytoriów…"):
                chunks = ingest_app(repos_to_index)
            st.session_state.chunks = chunks
            st.session_state.repo_paths = {r["name"]: r["path"] for r in repos_to_index}
            st.session_state.active_app_id = chosen_app["id"] if chosen_app else None
            if st.session_state.active_tab == "ready":
                st.session_state.active_tab = "analyze"
            st.rerun()

    if st.session_state.get("chunks"):
        chunks = st.session_state.chunks
        repos_in_index = [r for r in st.session_state.get("repo_paths", {})]
        per_repo = Counter(c.repo for c in chunks)
        st.success(f"✅ {len(chunks)} symboli z {len(repos_in_index)} repo")
        with st.expander(f"Rozkład: {len(repos_in_index)} repozytoriów"):
            st.dataframe(
                pd.DataFrame(
                    [{"Repo": r, "Symboli": per_repo.get(r, 0)} for r in repos_in_index]
                ),
                use_container_width=True, hide_index=True,
            )
        with st.expander("Zaindeksowane symbole"):
            st.dataframe(
                pd.DataFrame([
                    {"Repo": c.repo, "Symbol": c.symbol, "Plik": c.file_path,
                     "Linie": f"{c.start_line}–{c.end_line}"}
                    for c in chunks
                ]),
                use_container_width=True, hide_index=True,
            )

    st.divider()

    # Historia sesji
    st.markdown("**Historia wątków**")
    if st.button("＋ Nowy wątek", use_container_width=True, type="secondary"):
        ns = _new_session()
        st.session_state.sessions.append(ns)
        st.session_state.active_session_id = ns["id"]
        st.session_state.active_tab = "analyze"
        st.rerun()

    active_sid = st.session_state.active_session_id
    for sess in reversed(st.session_state.sessions):
        is_cur = sess["id"] == active_sid
        label = f"{'▶ ' if is_cur else ''}{sess['name']}"
        msg_count = len(sess["messages"])
        with st.expander(f"{label}  ({msg_count})", expanded=is_cur):
            if not is_cur:
                c1, c2 = st.columns(2)
                if c1.button("Wznów", key=f"resume_{sess['id']}", use_container_width=True):
                    st.session_state.active_session_id = sess["id"]
                    st.session_state.active_tab = "analyze"
                    st.rerun()
                if c2.button("Kontekst →", key=f"ctx_{sess['id']}", use_container_width=True):
                    if sess["messages"]:
                        last = sess["messages"][-1]
                        ns = _new_session()
                        st.session_state.sessions.append(ns)
                        st.session_state.active_session_id = ns["id"]
                        st.session_state.context_prefill = (
                            f"Kontekst z poprzedniego wątku:\n{last['answer'][:300]}…\n\n"
                        )
                        st.session_state.active_tab = "analyze"
                        st.rerun()
            if sess["messages"]:
                for m in sess["messages"][-3:]:
                    st.caption(f"↳ {m['question'][:50]}…")

    _active_model = os.environ.get("OPENROUTER_MODEL", "z-ai/glm-5.2")
    st.caption(f"🟢 {_active_model}")

# ── Sync query params → session state (stepper link navigation) ───────────────
if "step" in st.query_params:
    requested = st.query_params["step"]
    if requested in STEP_KEYS and requested != st.session_state.active_tab:
        _completed = _completed_steps()
        req_idx = STEP_KEYS.index(requested)
        cur_idx = STEP_KEYS.index(st.session_state.active_tab) if st.session_state.active_tab in STEP_KEYS else 0
        if req_idx <= cur_idx or requested in _completed:
            st.session_state.active_tab = requested
            st.query_params.clear()
            st.rerun()

# ── Workflow stepper (HTML) ───────────────────────────────────────────────────
completed = _completed_steps()
active_tab = st.session_state.active_tab
active_idx = STEP_KEYS.index(active_tab) if active_tab in STEP_KEYS else 0

def _stepper_html(steps, active_tab, completed, active_idx):
    items = []
    for i, (key, label) in enumerate(steps):
        is_active = key == active_tab
        is_done = key in completed
        is_locked = i > active_idx and key not in completed

        if is_locked:
            circle_bg = "#E0E0E0"
            circle_color = "#AAAAAA"
            label_color = "#AAAAAA"
            circle_content = str(i + 1)
            cursor = "default"
            href = ""
        elif is_active and is_done:  # aktywny i ukończony — pełne wypełnienie
            circle_bg = "#A100FF"
            circle_color = "#FFFFFF"
            label_color = "#A100FF"
            circle_content = "✓"
            cursor = "default"
            href = ""
        elif is_active:  # aktywny, w toku — tylko obramowanie
            circle_bg = "#FFFFFF"
            circle_color = "#A100FF"
            label_color = "#A100FF"
            circle_content = str(i + 1)
            cursor = "default"
            href = ""
        else:  # done, nieaktywny — klikalny
            circle_bg = "#F3E5FF"
            circle_color = "#A100FF"
            label_color = "#6600AA"
            circle_content = "✓"
            cursor = "pointer"
            href = f"?step={key}"

        border_color = "#A100FF" if (is_active or (is_done and not is_locked)) else "#E0E0E0"
        circle_style = (
            f"width:36px;height:36px;border-radius:50%;"
            f"background:{circle_bg};color:{circle_color};"
            f"display:flex;align-items:center;justify-content:center;"
            f"margin:0 auto;font-size:15px;font-weight:bold;"
            f"border:2px solid {border_color};"
        )
        label_style = (
            f"font-size:12px;color:{label_color};margin-top:6px;"
            f"font-weight:{'700' if is_active else '400'};"
        )

        if href:
            node = (
                f"<div style='text-align:center;cursor:{cursor};flex:0 0 80px'>"
                f"<a href='{href}' target='_self' style='text-decoration:none'>"
                f"<div style='{circle_style}'>{circle_content}</div>"
                f"<div style='{label_style}'>{label}</div>"
                f"</a></div>"
            )
        else:
            node = (
                f"<div style='text-align:center;cursor:{cursor};flex:0 0 80px'>"
                f"<div style='{circle_style}'>{circle_content}</div>"
                f"<div style='{label_style}'>{label}</div>"
                f"</div>"
            )
        items.append(node)

        if i < len(steps) - 1:
            line_color = "#A100FF" if i < active_idx or key in completed else "#E0E0E0"
            items.append(
                f"<div style='flex:1;height:2px;background:{line_color};margin-top:17px;'></div>"
            )

    inner = "\n".join(items)
    return (
        f"<div style='margin-bottom:4px;font-size:11px;font-weight:600;"
        f"color:#888;letter-spacing:1px;text-transform:uppercase'>Workflow</div>"
        f"<div style='display:flex;align-items:flex-start;padding:8px 0 16px 0'>{inner}</div>"
    )

st.markdown(_stepper_html(STEPS, active_tab, completed, active_idx), unsafe_allow_html=True)
st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════════
# KROK 1 — System Ready
# ═══════════════════════════════════════════════════════════════════════════════
if active_tab == "ready":
    st.title("System Ready")
    st.markdown("Zaindeksuj repozytorium aby rozpocząć analizę kodu.")

    if st.session_state.get("chunks"):
        chunks = st.session_state.chunks
        st.success(f"✅ Repozytorium zaindeksowane — {len(chunks)} symboli gotowych do analizy.")
        col1, col2 = st.columns(2)
        for i, c in enumerate(chunks):
            (col1 if i % 2 == 0 else col2).info(f"**{c.symbol}**  \n`{c.file_path}:{c.start_line}`")
        st.markdown("")
        if st.button("Przejdź dalej →", type="primary"):
            _advance()
    else:
        st.info("Użyj panelu bocznego: wpisz ścieżkę do repozytorium i kliknij **⚡ Indeksuj repozytorium**.")

# ═══════════════════════════════════════════════════════════════════════════════
# KROK 2 — Analyze
# ═══════════════════════════════════════════════════════════════════════════════
elif active_tab == "analyze":
    st.title("Analyze")

    if "chunks" not in st.session_state:
        st.warning("Najpierw zaindeksuj aplikację (panel boczny).")
    else:
        # ── Pole pytania (główna akcja, na samej górze) ──
        prefill = st.session_state.pop("context_prefill", "")
        col_q, col_btn = st.columns([5, 1])
        with col_q:
            question = st.text_area(
                "Pytanie",
                value=prefill,
                placeholder=(
                    "np. Dlaczego anulowanie zamówienia cicho nie działa?\n"
                    "    Jak obliczana jest opłata za opóźnienie?\n"
                    "    Jaka jest polityka zwrotów?"
                ),
                height=90,
                label_visibility="collapsed",
            )
        with col_btn:
            st.write("")
            st.write("")
            ask_clicked = st.button("Zapytaj ➜", use_container_width=True, type="primary")

        if ask_clicked and question.strip():
            with st.spinner("Szukam…"):
                result = run_qa(question, chunks=st.session_state.chunks)
            _log_question(question, result, st.session_state.get("active_app_id"))
            _active_session()["messages"].insert(0, {
                "question": question,
                "answer": result["answer"],
                "chunks": result["retrieved_chunks"],
                "business_context": result.get("business_context"),
                "feasibility": result.get("feasibility"),
                "test_plan": result.get("test_plan"),
                "proposals": result.get("proposals", []),
                "recommended_index": result.get("recommended_index"),
                "recommended_reason": result.get("recommended_reason"),
                "accepted_proposal_indices": None,
                "ts": datetime.now().strftime("%H:%M"),
            })
            st.rerun()

        # ── Historia aktywnej sesji ──
        messages = _active_messages()
        if not messages:
            st.caption("Brak wiadomości w tym wątku. Zadaj pytanie powyżej.")

        for i, item in enumerate(messages):
            biz = item.get("business_context")
            feas = item.get("feasibility")
            tp = item.get("test_plan")
            chunks_item = item.get("chunks", [])
            proposals = item.get("proposals", [])

            with st.container(border=True):
                st.markdown(f"**🔍 {item['question']}**")
                st.caption(f"🕐 {item.get('ts', '')} — {_active_session()['name']}")

                # ── Odpowiedź w zakładkach ──
                tab_sum, tab_feas, tab_test, tab_src = st.tabs(
                    ["📊 Podsumowanie", "✅ Wykonalność", "🧪 Plan testów", "📎 Źródła"]
                )

                with tab_sum:
                    if biz:
                        m1, m2, m3 = st.columns(3)
                        m1.metric("⏱ Dev", biz.get("time_dev", "—"))
                        m2.metric("🧪 Test", biz.get("time_test", "—"))
                        m3.metric("📅 Łącznie", biz.get("time_total", "—"))
                        c1, c2 = st.columns(2)
                        icon = "🔴" if biz.get("impact") == "Wysoki" else "🟡"
                        c1.markdown(f"**Impact:** {icon} {biz.get('impact', '—')}  \n"
                                    f"**Obszar:** {biz.get('area', '—')}")
                        ricon = "🔴" if "Wysoki" in biz.get("risk", "") else "🟡"
                        c2.markdown(f"**Ryzyko:** {ricon} {biz.get('risk', '—')}")
                        if biz.get("summary"):
                            st.markdown(biz["summary"])
                        if biz.get("dependencies"):
                            st.markdown("**Zależności:** " + ", ".join(biz["dependencies"]))
                    else:
                        st.markdown(item["answer"])

                with tab_feas:
                    if feas:
                        vicon = {"Tak": "🟢", "Z zastrzeżeniami": "🟡", "Nie": "🔴"}.get(feas.get("verdict", ""), "🟡")
                        st.markdown(f"**{vicon} {feas.get('verdict', '—')}** — {feas.get('reason', '')}")
                        if feas.get("impacted_services"):
                            st.markdown("**Serwisy:** " + ", ".join(feas["impacted_services"]))
                        if feas.get("impacted_files"):
                            st.markdown("**Pliki:**")
                            for f in feas["impacted_files"]:
                                st.markdown(f"- `{f}`")
                    else:
                        st.caption("Brak oceny wykonalności.")

                with tab_test:
                    if tp and (tp.get("existing") or tp.get("new")):
                        for t in tp.get("existing", []):
                            st.markdown(f"- ✅ (istnieje) {t}")
                        for t in tp.get("new", []):
                            st.markdown(f"- ➕ (nowy) {t}")
                    else:
                        st.caption("Brak planu testów.")

                with tab_src:
                    st.markdown(item["answer"])
                    if chunks_item:
                        st.divider()
                        for c in chunks_item:
                            display_path = f"{c.repo}/{c.file_path}" if c.repo else c.file_path
                            st.code(
                                f"# {display_path}:{c.start_line}–{c.end_line}  ({c.symbol})\n{c.source}",
                                language=_lang_for(c.file_path),
                            )

                # ── Rekomendacja (jedna, wybrana przez LLM) ──────────────────
                if proposals:
                    st.markdown("---")
                    rec_idx = item.get("recommended_index")
                    if not isinstance(rec_idx, int) or not (0 <= rec_idx < len(proposals)):
                        rec_idx = 0
                    rec = proposals[rec_idx]
                    accepted_indices = item.get("accepted_proposal_indices")

                    effort_icon = "🟢" if rec["effort"] == "Bardzo niski" else ("🟡" if rec["effort"] == "Niski" else "🔴")
                    risk_icon = "🔴" if "Wysoki" in rec["risk"] else ("🟢" if "Niski" in rec["risk"] else "🟡")

                    if accepted_indices is None:
                        st.markdown("**💡 Rekomendowane rozwiązanie**")
                        st.markdown(
                            f"<div style='background:#f0fdf4;border-left:4px solid #22c55e;"
                            f"padding:10px 16px;border-radius:4px;margin-bottom:8px'>"
                            f"<b>{rec['title']}</b><br/>"
                            f"<span style='color:#555;font-size:13px'>{rec['description']}</span><br/>"
                            f"<span style='font-size:12px;color:#888'>Nakład: {effort_icon} {rec['effort']} "
                            f"&nbsp;·&nbsp; Ryzyko: {risk_icon} {rec['risk']}</span></div>",
                            unsafe_allow_html=True,
                        )
                        if item.get("recommended_reason"):
                            st.caption(f"Dlaczego ta opcja: {item['recommended_reason']}")
                        others = [(k, p) for k, p in enumerate(proposals) if k != rec_idx]
                        if others:
                            with st.expander(f"Rozważane alternatywy ({len(others)})"):
                                for _, p in others:
                                    st.markdown(f"- **{p['title']}** — {p['description']}")

                        # Uwagi już uwzględnione w tej rekomendacji (jeśli były iteracje).
                        prior_refinements = item.get("refinements", [])
                        if prior_refinements:
                            with st.expander(f"🗣 Uwzględnione uwagi ({len(prior_refinements)})"):
                                for r in prior_refinements:
                                    st.markdown(f"- {r}")

                        # ── Doprecyzowanie: użytkownik dodaje uwagi → nowa rekomendacja ──
                        with st.expander("✍️ Doprecyzuj — poproś o nową rekomendację"):
                            note = st.text_area(
                                "Uwagi do uwzględnienia",
                                placeholder=(
                                    "np. nie chcę nowej klasy bazowej — wolę zmianę lokalnie w każdym serwisie\n"
                                    "    uwzględnij że logowanie musi być na poziomie INFO i bez danych wrażliwych"
                                ),
                                height=80,
                                key=f"refine_note_{i}",
                                label_visibility="collapsed",
                            )
                            if st.button(
                                "🔄 Wygeneruj nową rekomendację z uwagami",
                                key=f"regen_{i}", use_container_width=True,
                                disabled=not note.strip(),
                            ):
                                item.setdefault("refinements", []).append(note.strip())
                                refinements_txt = "\n".join(f"- {r}" for r in item["refinements"])
                                augmented = (
                                    f"{item['question']}\n\n"
                                    f"UWAGI UŻYTKOWNIKA DO UWZGLĘDNIENIA (doprecyzowanie wcześniejszej "
                                    f"rekomendacji — potraktuj je jako twarde wymagania):\n{refinements_txt}\n\n"
                                    f"Wygeneruj zaktualizowaną analizę i JEDNĄ rekomendację, "
                                    f"uwzględniając powyższe uwagi."
                                )
                                with st.spinner("Generuję nową rekomendację z uwzględnieniem uwag…"):
                                    new_result = run_qa(augmented, chunks=st.session_state.chunks)
                                _log_question(augmented, new_result, st.session_state.get("active_app_id"))
                                item["answer"] = new_result["answer"]
                                item["chunks"] = new_result["retrieved_chunks"]
                                item["business_context"] = new_result.get("business_context")
                                item["feasibility"] = new_result.get("feasibility")
                                item["test_plan"] = new_result.get("test_plan")
                                item["proposals"] = new_result.get("proposals", [])
                                item["recommended_index"] = new_result.get("recommended_index")
                                item["recommended_reason"] = new_result.get("recommended_reason")
                                item["accepted_proposal_indices"] = None
                                st.rerun()

                        if chunks_item and st.button(
                            "✅ Akceptuj rekomendację i przejdź dalej",
                            key=f"accept_{i}", type="primary", use_container_width=True,
                        ):
                            item["accepted_proposal_indices"] = [rec_idx]
                            item["accepted_commit_hints"] = [rec["commit_hint"]]
                            st.session_state.sandbox_preload_symbol = chunks_item[0].symbol
                            st.session_state.sandbox_accepted_proposals = [rec]
                            st.session_state.sandbox_question = item["question"]
                            st.session_state.sandbox_generated_code = None
                            st.session_state.sandbox_code_version = 0
                            st.session_state.sandbox_diff = None
                            st.session_state.sandbox_newfile = None
                            st.session_state.sandbox_error = None
                            st.session_state.sandbox_chunks = chunks_item
                            st.session_state.sandbox_preload_chunks = chunks_item
                            st.session_state.sandbox_multi_changes = None
                            st.session_state.sandbox_plan = None
                            _advance()
                    else:
                        for j in accepted_indices:
                            st.success(f"✅ {proposals[j]['title']}")
                        if chunks_item and st.button("Przejdź dalej →", key=f"next_{i}", type="primary"):
                            st.session_state.sandbox_preload_symbol = chunks_item[0].symbol
                            st.session_state.sandbox_accepted_proposals = [
                                proposals[j] for j in accepted_indices
                            ]
                            st.session_state.sandbox_question = item["question"]
                            st.session_state.sandbox_generated_code = None
                            st.session_state.sandbox_code_version = 0
                            st.session_state.sandbox_diff = None
                            st.session_state.sandbox_newfile = None
                            st.session_state.sandbox_error = None
                            st.session_state.sandbox_chunks = chunks_item
                            st.session_state.sandbox_preload_chunks = chunks_item
                            st.session_state.sandbox_multi_changes = None
                            st.session_state.sandbox_plan = None
                            _advance()


# ═══════════════════════════════════════════════════════════════════════════════
# KROK 3 — Piaskownica
# ═══════════════════════════════════════════════════════════════════════════════
elif active_tab == "sandbox":
    st.title("Piaskownica kodu")

    if "chunks" not in st.session_state:
        st.info("Najpierw zaindeksuj repozytorium w panelu bocznym.")
    else:
        symbol = st.session_state.get("sandbox_preload_symbol")
        question = st.session_state.get("sandbox_question", "")
        accepted_proposals = st.session_state.get("sandbox_accepted_proposals", [])

        if not symbol:
            st.info("Wróć do kroku Analyze, zadaj pytanie i zaakceptuj propozycję zmian.")
        else:
            chunks = st.session_state.chunks
            chunk = next((c for c in chunks if c.symbol == symbol), None)

            if not chunk:
                st.warning(f"Nie znaleziono funkcji '{symbol}' w zaindeksowanym kodzie.")
            else:
                # ── Ścieżka serwisu sklepu (Java/JS/TS/…): pełny plik → diff (git) → PR → bramka ──
                # Obsługuje zarówno single-repo jak i multi-repo (wszystkie chunki z wyników wyszukiwania).
                if not chunk.file_path.endswith(".py"):
                    if question:
                        st.markdown(
                            f"<div style='background:#f0f4ff;border-left:4px solid #6366f1;"
                            f"padding:10px 16px;border-radius:4px;margin-bottom:12px'>"
                            f"<span style='font-size:12px;color:#6366f1;font-weight:600'>ŻĄDANA ZMIANA</span><br/>"
                            f"{question}</div>",
                            unsafe_allow_html=True,
                        )
                    for p in accepted_proposals:
                        st.caption(f"✅ {p['title']} — {p['description']}")

                    repo_paths = st.session_state.get("repo_paths", {})

                    # ── Krok planowania: LLM wskazuje pliki do zmiany/utworzenia w CAŁEJ aplikacji
                    # (na bazie mapy wszystkich repo), zamiast ślepego top-5 z retrievalu. ──
                    if st.session_state.get("sandbox_plan") is None:
                        with st.spinner("Planuję zmianę w całej aplikacji (które pliki zmienić/utworzyć)…"):
                            repo_map = build_repo_map(st.session_state.get("chunks", []))
                            st.session_state.sandbox_plan = plan_change(
                                question, repo_map, accepted_proposals
                            )
                        st.rerun()

                    plan = st.session_state.get("sandbox_plan") or []
                    seen_keys: set = set()
                    targets: list[dict] = []
                    for pf in plan:
                        repo, path, action = pf["repo"], pf["path"], pf["action"]
                        if repo not in repo_paths or path.endswith(".py"):
                            continue
                        if (repo, path) in seen_keys:
                            continue
                        seen_keys.add((repo, path))
                        rpath = repo_paths[repo]
                        orig = ""
                        if action == "modify":
                            try:
                                with open(os.path.join(rpath, path), encoding="utf-8") as _f:
                                    orig = _f.read()
                            except OSError:
                                action = "create"  # plik z planu nie istnieje → utwórz
                        targets.append({
                            "repo": repo, "file_path": path, "action": action,
                            "original": orig, "repo_path": rpath,
                            "reason": pf.get("reason", ""),
                        })

                    # Fallback: planner nic nie zwrócił → użyj plików z retrievalu (stare zachowanie).
                    if not targets:
                        st.warning("Planner nie zwrócił plików — używam wyników wyszukiwania jako kandydatów.")
                        for c in (st.session_state.get("sandbox_preload_chunks") or [chunk]):
                            if c.file_path.endswith(".py") or c.repo not in repo_paths:
                                continue
                            if (c.repo, c.file_path) in seen_keys:
                                continue
                            seen_keys.add((c.repo, c.file_path))
                            rpath = repo_paths.get(c.repo, "")
                            try:
                                with open(os.path.join(rpath, c.file_path), encoding="utf-8") as _f:
                                    orig = _f.read()
                            except OSError:
                                orig = c.source
                            targets.append({"repo": c.repo, "file_path": c.file_path, "action": "modify",
                                             "original": orig, "repo_path": rpath, "reason": ""})

                    n_repos = len({t["repo"] for t in targets})
                    n_files = len(targets)
                    n_new = sum(1 for t in targets if t["action"] == "create")
                    st.caption(
                        f"Plan: {n_files} plik(ów) w {n_repos} repo · {n_new} nowych · base `main`"
                    )
                    with st.expander("📋 Plan zmian", expanded=True):
                        if not targets:
                            st.info("Brak plików do zmiany.")
                        for t in targets:
                            tag = "🆕 utwórz" if t["action"] == "create" else "✏️ zmień"
                            st.markdown(
                                f"- {tag} `{t['repo']}/{t['file_path']}`"
                                + (f" — {t['reason']}" if t.get("reason") else "")
                            )

                    # Inicjuj lub przywróć stan zmian per-plik.
                    if st.session_state.get("sandbox_multi_changes") is None:
                        st.session_state.sandbox_multi_changes = [
                            {**t, "new_content": None, "diff": None, "error": None, "pr_result": None}
                            for t in targets
                        ]
                        st.session_state.sandbox_test_results = {}  # nowe zmiany → testy nieaktualne
                        st.session_state.sandbox_verify = None       # i weryfikacja nieaktualna
                    multi = st.session_state.sandbox_multi_changes

                    # Generuj zmiany dla plików bez wygenerowanej treści.
                    to_gen = [mc for mc in multi if mc["new_content"] is None]
                    if to_gen:
                        with st.spinner(f"Generuję zmiany dla {len(to_gen)}/{len(multi)} pliku/plików…"):
                            for mc in to_gen:
                                try:
                                    if mc.get("action") == "create":
                                        gen = generate_new_file(
                                            question, accepted_proposals,
                                            mc["repo"], mc["file_path"],
                                        ) or ""
                                    else:
                                        gen = generate_file_change(
                                            question, accepted_proposals,
                                            mc["file_path"], mc["original"],
                                        ) or ""
                                    mc["new_content"] = gen
                                    # Pusta treść z modelu = BRAK zmiany, nie usunięcie pliku.
                                    # Bez tego compute_diff(original, "") dałby diff kasujący
                                    # cały plik i trafiłby do PR-a.
                                    mc["diff"] = (
                                        compute_diff(mc["original"], gen, mc["file_path"])
                                        if gen.strip() else ""
                                    )
                                    mc["error"] = None
                                except Exception as exc:
                                    mc["new_content"] = ""
                                    mc["diff"] = ""
                                    mc["error"] = str(exc)
                        st.rerun()

                    # Pokaż diff per-plik.
                    has_any_diff = any((mc.get("diff") or "").strip() for mc in multi)
                    for mc in multi:
                        diff_str = mc.get("diff") or ""
                        tag = "🆕 " if mc.get("action") == "create" else ""
                        label = f"{tag}`{mc['repo']}/{mc['file_path']}`"
                        with st.expander(label, expanded=bool(diff_str.strip())):
                            if mc.get("error"):
                                st.error(f"Błąd LLM: {mc['error']}")
                            elif not (mc.get("new_content") or "").strip():
                                st.warning(
                                    f"Model zwrócił pustą treść dla `{mc['file_path']}` "
                                    f"(serwis **{mc['repo']}**)."
                                )
                            elif not diff_str.strip():
                                st.warning("Wygenerowana treść identyczna z oryginałem (brak zmian).")
                            else:
                                st.code(diff_str, language="diff")
                                with st.expander("Pełna nowa treść"):
                                    st.code(mc["new_content"], language=_lang_for(mc["file_path"]))

                    # ── Kompletność: licznik + ponów puste + agent-recenzent ──
                    produced = [mc for mc in multi if (mc.get("new_content") or "").strip()]
                    empty = [
                        mc for mc in multi
                        if not (mc.get("new_content") or "").strip() and not mc.get("error")
                    ]
                    st.markdown("---")
                    st.caption(
                        f"Wygenerowano treść: **{len(produced)}/{len(multi)}** plików"
                        + (f" · **{len(empty)}** pustych (model nie wygenerował)" if empty else "")
                    )
                    if empty:
                        st.warning(
                            "Część zaplanowanych plików wróciła pusta — model uznał je za nieistotne "
                            "albo nie poradził sobie z treścią. Możesz ponowić ich generowanie."
                        )
                        if st.button("♻️ Ponów generowanie pustych", use_container_width=True):
                            for mc in empty:
                                mc["new_content"] = None  # pętla generowania wygeneruje je ponownie
                            st.rerun()

                    with st.expander("🔍 Weryfikacja kompletności (agent-recenzent)",
                                     expanded=bool(empty)):
                        st.caption(
                            "Agent sprawdza, czy wygenerowany zestaw plików wystarcza, by zmiana "
                            "działała end-to-end (czy nie brakuje plików, do których odwołuje się kod)."
                        )
                        if st.button("Sprawdź kompletność zmiany", use_container_width=True):
                            gen_files = [
                                {
                                    "repo": mc["repo"], "path": mc["file_path"],
                                    "action": mc.get("action", "modify"),
                                    "status": "ok" if (mc.get("new_content") or "").strip() else "empty",
                                    "head": "\n".join((mc.get("new_content") or "").splitlines()[:15]),
                                }
                                for mc in multi
                            ]
                            with st.spinner("Agent weryfikuje kompletność zestawu plików…"):
                                st.session_state.sandbox_verify = verify_completeness(
                                    question, accepted_proposals,
                                    build_repo_map(st.session_state.get("chunks", [])),
                                    gen_files,
                                )
                            st.rerun()

                        verdict = st.session_state.get("sandbox_verify")
                        if verdict:
                            if verdict["complete"]:
                                st.success("✅ Agent: zestaw plików wygląda na kompletny.")
                            else:
                                st.warning(f"⚠️ Agent: zestaw niekompletny. {verdict.get('notes', '')}")
                            if verdict.get("missing"):
                                st.markdown("**Brakujące / do uzupełnienia pliki:**")
                                for m in verdict["missing"]:
                                    tag = "🆕 utwórz" if m["action"] == "create" else "✏️ zmień"
                                    st.markdown(
                                        f"- {tag} `{m['repo']}/{m['path']}`"
                                        + (f" — {m['reason']}" if m.get("reason") else "")
                                    )
                                if st.button("➕ Dodaj brakujące do planu i wygeneruj",
                                             type="primary", use_container_width=True):
                                    repo_paths = st.session_state.get("repo_paths", {})
                                    existing = {(mc["repo"], mc["file_path"]) for mc in multi}
                                    added = 0
                                    for m in verdict["missing"]:
                                        if (m["repo"] not in repo_paths
                                                or (m["repo"], m["path"]) in existing
                                                or m["path"].endswith(".py")):
                                            continue
                                        rpath = repo_paths[m["repo"]]
                                        action, orig = m["action"], ""
                                        if action == "modify":
                                            try:
                                                with open(os.path.join(rpath, m["path"]), encoding="utf-8") as _f:
                                                    orig = _f.read()
                                            except OSError:
                                                action = "create"
                                        multi.append({
                                            "repo": m["repo"], "file_path": m["path"], "action": action,
                                            "original": orig, "repo_path": rpath, "reason": m.get("reason", ""),
                                            "new_content": None, "diff": None, "error": None, "pr_result": None,
                                        })
                                        added += 1
                                    st.session_state.sandbox_verify = None
                                    st.session_state.sandbox_test_results = {}
                                    if added:
                                        st.toast(f"Dodano {added} plik(ów) do planu — generuję…")
                                    st.rerun()

                    # Status PR per-repo (już wystawionych).
                    done_prs = [mc for mc in multi if mc.get("pr_result") is not None]
                    for mc in done_prs:
                        pr = mc["pr_result"]
                        if pr.get("success"):
                            st.success(f"✅ PR otwarty — `{mc['repo']}`: {pr.get('pr_url', '')}")
                        elif pr.get("warning"):
                            st.warning(f"⚠️ `{mc['repo']}`: {pr['warning']}")
                        else:
                            st.error(f"❌ `{mc['repo']}`: {pr.get('error', 'nieznany błąd')}")

                    # ── Bramka: gradle test per serwis PRZED wystawieniem PR ──
                    changed = [mc for mc in multi if (mc.get("diff") or "").strip()]
                    affected_repos: dict = {}
                    for mc in changed:
                        ar = affected_repos.setdefault(
                            mc["repo"], {"repo_path": mc["repo_path"], "files": []}
                        )
                        ar["files"].append((mc["file_path"], mc["new_content"]))

                    test_results = st.session_state.setdefault("sandbox_test_results", {})
                    if changed:
                        st.markdown("---")
                        st.markdown("**🧪 Testy serwisów (gradle test) — opcjonalnie**")
                        st.caption(
                            "Pełne testy (Cucumber + Testcontainers) na czystym worktree z "
                            "`origin/main` + Twoja zmiana. Opcjonalne — autorytatywna bramka "
                            "`preprod-gate` i tak odpali się w CI po wystawieniu PR."
                        )
                        if st.button("▶ Uruchom testy (opcjonalnie)", use_container_width=True):
                            for repo, info in affected_repos.items():
                                with st.spinner(f"gradle test — {repo}… (to może potrwać minuty)"):
                                    test_results[repo] = run_service_tests(
                                        info["repo_path"], info["files"]
                                    )
                            st.session_state.sandbox_test_results = test_results
                            st.rerun()

                        for repo in affected_repos:
                            res = test_results.get(repo)
                            dur = f"{res.get('duration_s', '?')}s" if res else ""
                            if not res:
                                st.markdown(f"⏳ **{repo}** — testy nieuruchomione")
                            elif res.get("success"):
                                st.success(f"✅ {repo} — {res.get('summary', 'OK')}  ({dur})")
                            else:
                                st.error(
                                    f"❌ {repo} — {res.get('summary') or res.get('error', 'niepowodzenie')}  ({dur})"
                                )
                                if res.get("tail"):
                                    with st.expander(f"Log — {repo}"):
                                        st.code(res["tail"], language=None)

                    # Przycisk wystawiania PRów — testy lokalne NIE blokują (walidacja w CI).
                    pending = [
                        mc for mc in multi
                        if mc.get("pr_result") is None and (mc.get("diff") or "").strip()
                    ]
                    if pending and has_any_diff:
                        # Grupuj zmiany po repo — JEDEN PR per repo zbiera wszystkie jego pliki.
                        pending_by_repo: dict = {}
                        for mc in pending:
                            pending_by_repo.setdefault(mc["repo"], []).append(mc)
                        n_repos_p = len(pending_by_repo)
                        default_title = (
                            accepted_proposals[0].get("commit_hint") if accepted_proposals
                            else f"change: {n_repos_p} serwisów"
                        )
                        pr_title = st.text_input("Tytuł PR / commit", value=default_title or "change")
                        st.caption("Walidacja testowa wykona się w CI (`preprod-gate`) po utworzeniu PR.")
                        if st.button(
                            f"🚀 Wystaw {'PR' if n_repos_p == 1 else f'{n_repos_p} PRy/PRów'} "
                            f"({n_repos_p} {'repozytorium' if n_repos_p == 1 else 'repozytoria/repozytoriów'})",
                            type="primary", use_container_width=True,
                        ):
                            with st.spinner(f"Wystawiam {n_repos_p} PR-ów (po jednym na repo)…"):
                                for repo, mcs in pending_by_repo.items():
                                    files = [
                                        {"path": mc["file_path"], "content": mc["new_content"],
                                         "allow_create": mc.get("action") == "create"}
                                        for mc in mcs
                                    ]
                                    rs = open_pr_for_files(
                                        files,
                                        pr_title.strip() or f"change: {repo}",
                                        "PR wygenerowany przez shop-qa-ui. Walidacja: bramka preprod-gate.",
                                        f"ai-bot-playground/{repo}",
                                        local_repo=mcs[0]["repo_path"],
                                    )
                                    for mc in mcs:  # ten sam wynik PR dla wszystkich plików repo
                                        mc["pr_result"] = rs
                            all_attempted = all(
                                mc.get("pr_result") is not None
                                for mc in multi if (mc.get("diff") or "").strip()
                            )
                            if all_attempted:
                                st.session_state.sandbox_commit_done = "multi"
                                # Jeden wpis per repo (nie per plik).
                                by_repo_pr: dict = {}
                                for mc in multi:
                                    if not (mc.get("diff") or "").strip():
                                        continue
                                    pr = mc.get("pr_result") or {}
                                    by_repo_pr[mc["repo"]] = {
                                        "repo": mc["repo"],
                                        "repo_slug": f"ai-bot-playground/{mc['repo']}",
                                        "pr_url": pr.get("pr_url", ""),
                                        "branch": pr.get("branch", ""),
                                        "success": pr.get("success", False),
                                        "error": pr.get("error", ""),
                                        "warning": pr.get("warning", ""),
                                    }
                                st.session_state.qa_multi_prs = list(by_repo_pr.values())
                                _advance()
                            st.rerun()
                    elif not pending and done_prs:
                        if st.button("Przejdź dalej → PR", type="primary"):
                            _advance()
                    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# KROK 4 — PR
# ═══════════════════════════════════════════════════════════════════════════════
elif active_tab == "pr":
    st.title("Pull Request")

    # ── Ścieżka multi-repo (wiele PRów cross-repo) — podsumowanie + status buildów ──
    if st.session_state.get("qa_multi_prs"):
        multi_prs = st.session_state.qa_multi_prs
        opened = [pr for pr in multi_prs if pr["success"]]
        n_repos = len({pr["repo"] for pr in multi_prs})
        st.markdown(f"### Podsumowanie PR — {len(multi_prs)} w {n_repos} repozytoriach")
        st.caption(
            f"{len(opened)}/{len(multi_prs)} otwartych pomyślnie. "
            "Status buildu (`preprod-gate`) odświeża się automatycznie co 15 s."
        )

        @st.fragment(run_every=15)
        def _pr_status_panel():
            agg = {"success": 0, "pending": 0, "failure": 0, "unknown": 0, "nieotwarte": 0}
            rows = []
            for pr in multi_prs:
                if not pr["success"]:
                    agg["nieotwarte"] += 1
                    rows.append((pr, "nieotwarte", None))
                    continue
                data = pr_checks(pr["repo_slug"], pr["branch"]) if pr.get("branch") else None
                state = _pr_build_state(data)
                agg[state] = agg.get(state, 0) + 1
                rows.append((pr, state, data))

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("✅ Success", agg["success"])
            c2.metric("⏳ Pending", agg["pending"] + agg["unknown"])
            c3.metric("❌ Failed", agg["failure"])
            c4.metric("⚠️ Nieotwarte", agg["nieotwarte"])

            icons = {"success": "✅", "pending": "⏳", "failure": "❌",
                     "unknown": "⏳", "nieotwarte": "⚠️"}
            for pr, state, data in rows:
                with st.expander(f"{icons[state]} `{pr['repo_slug']}` — {state}",
                                 expanded=state in ("failure", "nieotwarte")):
                    if state == "nieotwarte":
                        if pr.get("warning"):
                            st.warning(pr["warning"])
                        else:
                            st.error(f"PR nie został otwarty: {pr.get('error', 'nieznany błąd')}")
                        st.caption(f"Gałąź: `{pr.get('branch', '—')}`")
                        continue
                    if pr["pr_url"]:
                        st.link_button("Otwórz PR na GitHub", pr["pr_url"], use_container_width=True)
                    st.caption(f"Gałąź: `{pr['branch']}` · check **preprod-gate**")
                    if state == "success":
                        st.success("Build zielony — PR gotowy do przeglądu/merge.")
                    elif state == "pending":
                        st.info("Build w toku — bramka `preprod-gate` jeszcze się wykonuje.")
                    elif state == "failure":
                        st.error(
                            "❌ Build nieudany. **Deweloper powinien zajrzeć do tego PR i go naprawić** "
                            "— zmiana wygenerowana automatycznie nie przeszła bramki preprod."
                        )
                        # Które checki padły (+ linki do logów na GitHub).
                        failed_checks = [
                            c for c in (data or {}).get("checks", [])
                            if (c.get("bucket") or c.get("state") or "").lower()
                            in ("fail", "failure", "error", "cancelled", "timed_out")
                        ]
                        if failed_checks:
                            st.markdown("**Nieudane checki:**")
                            for c in failed_checks:
                                link = f" — [log CI]({c['link']})" if c.get("link") else ""
                                st.markdown(f"- ❌ {c.get('name', '?')}{link}")
                        # Best-effort opis błędu z logu CI (self-hosted bywa bez logów).
                        summary = pr_failure_summary(pr["repo_slug"], pr["branch"])
                        if summary:
                            with st.expander("Opis błędu (log CI)"):
                                st.code(summary, language=None)
                        elif not failed_checks:
                            st.caption("Brak szczegółów w API — otwórz PR, by zobaczyć log bramki.")
            st.caption(f"Ostatnie odświeżenie: {datetime.now():%H:%M:%S}")

        _pr_status_panel()
        if st.button("🔄 Odśwież teraz", use_container_width=True):
            st.rerun()
        st.stop()

    # ── Ścieżka Java (serwis sklepu): PR + status bramki preprod + merge ──
    if st.session_state.get("qa_repo_slug"):
        slug = st.session_state.qa_repo_slug
        branch = st.session_state.get("qa_pr_branch", "")
        pr_url = st.session_state.get("qa_pr_url", "")
        warn = st.session_state.get("qa_pr_warning", "")

        st.markdown(f"### PR do `{slug}`")
        if pr_url:
            st.success(f"✅ PR otwarty: {pr_url}")
            st.link_button("Otwórz PR na GitHub", pr_url, use_container_width=True)
        elif warn:
            st.warning(warn)
        st.caption(f"Gałąź: `{branch}` · base `main` → wymagany check **preprod-gate / gate**")

        if st.button("🔄 Sprawdź status bramki", use_container_width=True):
            with st.spinner("Pobieram status checków…"):
                st.session_state.qa_checks = pr_checks(slug, branch)
            st.rerun()

        data = st.session_state.get("qa_checks")
        gate_ok = False
        if data:
            if not data.get("available"):
                st.info(f"Brak statusu checków: {data.get('message', '')}")
            else:
                checks = data.get("checks", [])
                if not checks:
                    st.caption("Brak checków — bramka jeszcze nie wystartowała.")
                for c in checks:
                    bucket = (c.get("bucket") or c.get("state") or "").lower()
                    icon = "✅" if bucket in ("pass", "success") else ("❌" if bucket in ("fail", "failure") else "⏳")
                    st.markdown(f"{icon} **{c.get('name', '?')}** — {bucket}")
                    if "preprod-gate" in c.get("name", "") and bucket in ("pass", "success"):
                        gate_ok = True

        if gate_ok:
            st.success("Bramka zielona — kandydat wdrożony na preprod.")
            st.markdown("**Podgląd na preprod (sprawdź czy działa jak chcesz):**")
            st.code("kubectl --context kind-preprod -n shop port-forward svc/shop-gateway 8080:8080", language="bash")
            st.caption("Następnie np. http://localhost:8080/api/products")
            st.divider()
            st.markdown("### Merge (human-in-the-loop)")
            if st.checkbox("Potwierdzam, że zmiana działa na preprod jak chciałem"):
                if st.button("🔀 Merge PR (squash) do main", type="primary"):
                    with st.spinner("Merguję PR…"):
                        mres = merge_pr(slug, branch)
                    if mres.get("success"):
                        st.success("✅ Zmergowano do `main`.")
                        st.balloons()
                    else:
                        st.error(f"Merge nieudany: {mres.get('error')}")
        st.stop()

