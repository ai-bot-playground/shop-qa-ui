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
    generate_file_change, is_demo_mode,
)
from src.sandbox import (
    run_static_tests, replace_function_in_file, git_commit_file, commit_and_push_change,
    run_qa_eval, check_diff_applies, open_pr_for_change, compute_diff,
    open_pr_for_file_change, pr_checks, merge_pr,
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


st.set_page_config(
    page_title="Analizator Kodu",
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

    if is_demo_mode():
        st.caption("🟡 Tryb demo — brak klucza API")
    else:
        st.caption("🟢 LLM Available (4.8 Opus)")

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

if is_demo_mode():
    st.info(
        "🧪 **Tryb demonstracyjny** — nie wykryto klucza API, więc odpowiedzi LLM są "
        "przykładowe (mock). Uzupełnij `AZURE_ANTHROPIC_API_KEY` w `.env` "
        "(patrz `.env.example`), aby podłączyć model."
    )

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
    st.markdown(
        "Zadaj pytanie w języku naturalnym i otrzymaj odpowiedź "
        "**z dokładnymi cytowaniami `plik:linia`**. "
        "Przełącz tryb aby zobaczyć widok biznesowy lub techniczny."
    )

    if "chunks" not in st.session_state:
        st.warning("Najpierw zaindeksuj repozytorium (panel boczny).")
    else:
        # ── Typ odpowiedzi ──
        type_labels = [cfg["label"] for cfg in ANSWER_TYPES.values()]
        type_keys = list(ANSWER_TYPES.keys())
        current_mode_idx = type_keys.index(st.session_state.answer_mode) if st.session_state.answer_mode in type_keys else 0
        chosen_label = st.radio(
            "Typ odpowiedzi", type_labels, index=current_mode_idx, horizontal=True,
            label_visibility="collapsed",
        )
        st.session_state.answer_mode = type_keys[type_labels.index(chosen_label)]
        mode = st.session_state.answer_mode

        # ── Konfiguracja szablonu ──
        with st.expander("⚙️ Konfiguruj szablon odpowiedzi"):
            fields = st.session_state.answer_templates.get(mode, [])
            for field in fields:
                field["visible"] = st.checkbox(
                    field["label"], value=field["visible"], key=f"tpl_{mode}_{field['key']}"
                )

        # ── Pole pytania ──
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
            _active_session()["messages"].insert(0, {
                "question": question,
                "answer": result["answer"],
                "chunks": result["retrieved_chunks"],
                "business_context": result.get("business_context"),
                "feasibility": result.get("feasibility"),
                "test_plan": result.get("test_plan"),
                "proposals": result.get("proposals", []),
                "accepted_proposal_idx": None,
                "ts": datetime.now().strftime("%H:%M"),
            })
            st.rerun()

        # ── Historia aktywnej sesji ──
        messages = _active_messages()
        if not messages:
            st.caption("Brak wiadomości w tym wątku.")

        for i, item in enumerate(messages):
            with st.container(border=True):
                st.caption(f"🕐 {item.get('ts', '')}  —  {_active_session()['name']}")
                st.markdown(f"**Pytanie:** {item['question']}")

                biz = item.get("business_context")
                chunks_item = item.get("chunks", [])
                proposals = item.get("proposals", [])

                # ── SEKCJA: Problem ──────────────────────────────────────────
                st.markdown("#### Problem")
                if mode == "business":
                    if biz:
                        visible_keys = {
                            f["key"] for f in st.session_state.answer_templates.get("business", [])
                            if f["visible"]
                        }
                        if "summary" in visible_keys:
                            st.markdown(f"{biz['summary']}")
                            st.markdown("")
                        if "time_metrics" in visible_keys:
                            m1, m2, m3 = st.columns(3)
                            m1.metric("⏱ Dev", biz["time_dev"])
                            m2.metric("🧪 Test", biz["time_test"])
                            m3.metric("📅 Łącznie", biz["time_total"])
                        c1, c2 = st.columns(2)
                        if "impact" in visible_keys:
                            icon = "🔴" if biz["impact"] == "Wysoki" else "🟡"
                            c1.markdown(f"**Impact:** {icon} {biz['impact']}  \n**Obszar:** {biz['area']}")
                        if "risk" in visible_keys:
                            ricon = "🔴" if "Wysoki" in biz["risk"] else "🟡"
                            c2.markdown(f"**Ryzyko:** {ricon} {biz['risk']}")
                        if "dependencies" in visible_keys and biz.get("dependencies"):
                            st.markdown("**Zależności:**")
                            for dep in biz["dependencies"]:
                                st.markdown(f"- {dep}")
                        feas = item.get("feasibility")
                        if "feasibility" in visible_keys and feas:
                            vicon = {"Tak": "🟢", "Z zastrzeżeniami": "🟡", "Nie": "🔴"}.get(feas.get("verdict", ""), "🟡")
                            st.markdown(f"**Wykonalność:** {vicon} {feas.get('verdict', '')} — {feas.get('reason', '')}")
                            if feas.get("impacted_services"):
                                st.caption("Serwisy: " + ", ".join(feas["impacted_services"]))
                            if feas.get("impacted_files"):
                                st.caption("Pliki: " + ", ".join(feas["impacted_files"]))
                        tp = item.get("test_plan")
                        if "test_plan" in visible_keys and tp:
                            st.markdown("**Plan testów:**")
                            for t in tp.get("existing", []):
                                st.markdown(f"- ✅ (istnieje) {t}")
                            for t in tp.get("new", []):
                                st.markdown(f"- ➕ (nowy) {t}")
                    else:
                        st.markdown(item["answer"])
                else:
                    tech_visible = {
                        f["key"] for f in st.session_state.answer_templates.get("technical", [])
                        if f["visible"]
                    }
                    if "answer_text" in tech_visible:
                        st.markdown(item["answer"])
                    if chunks_item and ("file_path" in tech_visible or "source_code" in tech_visible):
                        with st.expander("📎 Źródła"):
                            for c in chunks_item:
                                repo_root = st.session_state.get("repo_paths", {}).get(c.repo, "")
                                display_path = f"{c.repo}/{c.file_path}" if c.repo else c.file_path
                                abs_path = os.path.join(repo_root, c.file_path) if repo_root else display_path
                                if "file_path" in tech_visible:
                                    st.code(f"{display_path}:{c.start_line}", language=None)
                                if "source_code" in tech_visible:
                                    lang = _lang_for(c.file_path)
                                    st.code(
                                        f"# {c.file_path}:{c.start_line}–{c.end_line}  ({c.symbol})\n{c.source}",
                                        language=lang,
                                    )

                # ── SEKCJA: Propozycje rozwiązania ───────────────────────────
                if proposals:
                    st.markdown("---")
                    st.markdown("#### Propozycje rozwiązania")
                    accepted_indices = item.get("accepted_proposal_indices")

                    if accepted_indices is None:
                        for j, p in enumerate(proposals):
                            effort_icon = "🟢" if p["effort"] == "Bardzo niski" else ("🟡" if p["effort"] == "Niski" else "🔴")
                            risk_icon = "🔴" if "Wysoki" in p["risk"] else ("🟢" if "Niski" in p["risk"] else "🟡")
                            checked = st.checkbox(
                                f"**{p['title']}**",
                                key=f"prop_check_{i}_{j}",
                            )
                            if checked:
                                with st.container():
                                    st.markdown(
                                        f"<div style='margin-left:28px;margin-bottom:6px'>"
                                        f"{p['description']}<br/>"
                                        f"<span style='font-size:12px;color:#888'>"
                                        f"Nakład: {effort_icon} {p['effort']} &nbsp;·&nbsp; "
                                        f"Ryzyko: {risk_icon} {p['risk']}</span></div>",
                                        unsafe_allow_html=True,
                                    )

                        selected_indices = [
                            j for j in range(len(proposals))
                            if st.session_state.get(f"prop_check_{i}_{j}", False)
                        ]
                        if st.button(
                            "✅ Akceptuj wybrane propozycje",
                            key=f"accept_{i}",
                            type="primary",
                            disabled=len(selected_indices) == 0,
                        ):
                            item["accepted_proposal_indices"] = selected_indices
                            item["accepted_commit_hints"] = [proposals[j]["commit_hint"] for j in selected_indices]
                            st.rerun()
                    else:
                        for j in accepted_indices:
                            p = proposals[j]
                            st.success(f"✅ {p['title']}")
                        st.caption(f"Sugerowane commity: {len(accepted_indices)}")

                        if chunks_item:
                            if st.button("Przejdź dalej →", key=f"next_{i}", type="primary"):
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
                # Wszystko poza .py (legacy sample) idzie tą ścieżką: Java, JSX/TSX front-endu itd.
                if not chunk.file_path.endswith(".py"):
                    service = chunk.repo or os.path.basename(
                        os.path.normpath(st.session_state.get("repo_paths", {}).get("", "") or "")
                    )
                    repo_path = st.session_state.get("repo_paths", {}).get(service, "")
                    repo_slug = f"ai-bot-playground/{service}"
                    target_rel = chunk.file_path
                    target_abs = os.path.join(repo_path, target_rel) if repo_path else target_rel
                    try:
                        with open(target_abs, encoding="utf-8") as _f:
                            original = _f.read()
                    except OSError:
                        original = chunk.source

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
                    st.caption(f"Plik docelowy: `{target_rel}` · PR → **{repo_slug}** (base `main`)")

                    if st.session_state.get("sandbox_newfile") is None:
                        with st.spinner("Agent generuje zmianę (pełna treść pliku)…"):
                            try:
                                st.session_state.sandbox_newfile = generate_file_change(
                                    question, accepted_proposals, target_rel, original,
                                )
                                st.session_state.sandbox_error = None
                            except Exception as exc:  # noqa: BLE001 — pokaż realny błąd w UI
                                st.session_state.sandbox_newfile = ""
                                st.session_state.sandbox_error = str(exc)
                        st.rerun()

                    new_content = st.session_state.sandbox_newfile or ""
                    sandbox_error = st.session_state.get("sandbox_error")
                    if sandbox_error:
                        st.error(
                            f"Wywołanie LLM nie powiodło się: {sandbox_error}\n\n"
                            "To nie jest brak klucza API. Jeśli to błąd certyfikatu "
                            "(`CERTIFICATE_VERIFY_FAILED`), to przejściowy problem korporacyjnego "
                            "proxy — ponów próbę."
                        )
                    elif not new_content.strip():
                        if is_demo_mode():
                            st.info(
                                "Brak zmiany — tryb demo (bez `OPENROUTER_API_KEY`/`AZURE_ANTHROPIC_API_KEY`). "
                                "Podłącz klucz API."
                            )
                        else:
                            st.warning(
                                "Model zwrócił pustą treść — najczęściej wskazany plik nie pasuje do "
                                f"zmiany. Wybrano `{target_rel}` w serwisie **{service}**; jeśli chcesz "
                                "zmienić inny serwis (np. shop-ui), zaindeksuj go w panelu bocznym i ponów."
                            )
                    else:
                        diff_preview = compute_diff(original, new_content, target_rel)
                        if not diff_preview.strip():
                            st.warning("Wygenerowana treść jest identyczna z oryginałem (brak zmian).")
                        else:
                            st.markdown("**Podgląd zmian (diff liczony przez git):**")
                            st.code(diff_preview, language="diff")
                        with st.expander("Pełna nowa treść pliku"):
                            st.code(new_content, language=_lang_for(target_rel))
                        default_title = (
                            accepted_proposals[0].get("commit_hint")
                            if accepted_proposals else f"change: {service}"
                        )
                        pr_title = st.text_input("Tytuł PR / commit", value=default_title or f"change: {service}")
                        can_pr = bool(diff_preview.strip())
                        if st.button("🚀 Wystaw PR do serwisu", type="primary",
                                     disabled=not can_pr, use_container_width=True):
                            with st.spinner("Tworzę czystą gałąź (git worktree), zapisuję plik, wypycham i otwieram PR…"):
                                res = open_pr_for_file_change(
                                    target_rel, new_content, pr_title.strip() or f"change: {service}",
                                    "PR wygenerowany przez shop-qa-ui. Walidacja: bramka preprod-gate.",
                                    repo_slug, local_repo=repo_path,
                                )
                            if res.get("success"):
                                st.session_state.sandbox_commit_done = res.get("branch", "branch")
                                st.session_state.qa_repo_slug = repo_slug
                                st.session_state.qa_pr_branch = res.get("branch", "")
                                st.session_state.qa_pr_url = res.get("pr_url", "")
                                st.session_state.qa_pr_warning = res.get("warning", "")
                                _advance()
                            else:
                                st.error(f"Nie udało się wystawić PR: {res.get('error')}")
                    st.stop()

                # ── Ścieżka Python (sample/legacy) ────────────────────────────
                # ── Pytanie użytkownika ───────────────────────────────────────
                if question:
                    st.markdown(
                        f"<div style='background:#f0f4ff;border-left:4px solid #6366f1;"
                        f"padding:10px 16px;border-radius:4px;margin-bottom:12px'>"
                        f"<span style='font-size:12px;color:#6366f1;font-weight:600'>PYTANIE</span><br/>"
                        f"{question}</div>",
                        unsafe_allow_html=True,
                    )

                # ── Zaakceptowana propozycja ──────────────────────────────────
                if accepted_proposals:
                    p = accepted_proposals[0]
                    effort_icon = "🟢" if p["effort"] == "Bardzo niski" else ("🟡" if p["effort"] == "Niski" else "🔴")
                    risk_icon = "🔴" if "Wysoki" in p["risk"] else ("🟢" if "Niski" in p["risk"] else "🟡")
                    st.markdown(
                        f"<div style='background:#f0fdf4;border-left:4px solid #22c55e;"
                        f"padding:10px 16px;border-radius:4px;margin-bottom:16px'>"
                        f"<span style='font-size:12px;color:#16a34a;font-weight:600'>PROPOZYCJA AGENTA</span><br/>"
                        f"<b>{p['title']}</b><br/>"
                        f"<span style='color:#555;font-size:13px'>{p['description']}</span><br/>"
                        f"<span style='font-size:12px;color:#888'>Nakład: {effort_icon} {p['effort']} &nbsp;·&nbsp; "
                        f"Ryzyko: {risk_icon} {p['risk']}</span></div>",
                        unsafe_allow_html=True,
                    )

                # ── Generowanie kodu przez LLM (raz, cache w session_state) ──
                if not st.session_state.get("sandbox_generated_code"):
                    with st.spinner("Agent generuje propozycję kodu…"):
                        proposal = accepted_proposals[0] if accepted_proposals else {}
                        generated = generate_code_fix(chunk.source, proposal, question) if proposal else chunk.source
                        st.session_state.sandbox_generated_code = generated
                        st.session_state.sandbox_code_version = st.session_state.get("sandbox_code_version", 0) + 1
                    st.rerun()

                col_original, col_modified = st.columns([1, 1])
                with col_original:
                    st.markdown("**Plik oryginalny**")
                    st.caption(f"`{chunk.file_path}:{chunk.start_line}–{chunk.end_line}`")
                    st.code(chunk.source, language="python")
                with col_modified:
                    st.markdown("**Plik zmodyfikowany**")
                    st.caption(f"`{chunk.file_path}`")
                    edited_code = st.text_area(
                        "Proponowany kod",
                        value=st.session_state.sandbox_generated_code,
                        height=300,
                        label_visibility="collapsed",
                        key=f"sandbox_code_{st.session_state.get('sandbox_code_version', 0)}",
                    )
                # When the last run had real failures, the button becomes a
                # "fix & re-run" action; otherwise it just runs the tests.
                prior_results = st.session_state.get("sandbox_results")
                prior_real_failures = [
                    r for r in (prior_results or [])
                    if not r["passed"] and not r["name"].startswith("⚠️")
                ]
                in_fix_mode = bool(prior_real_failures)

                run_clicked = st.button(
                    "🔧 Napraw kod i uruchom ponownie testy" if in_fix_mode else "▶ Uruchom testy",
                    type="primary", use_container_width=True,
                )

                if run_clicked:
                    if in_fix_mode:
                        with st.spinner("Agent naprawia kod i uruchamia testy ponownie…"):
                            fixed_code = fix_code_with_tests(edited_code, prior_real_failures)
                            results = run_static_tests(fixed_code)
                        st.session_state.sandbox_generated_code = fixed_code
                        st.session_state.sandbox_code_version = st.session_state.get("sandbox_code_version", 0) + 1
                        st.session_state.sandbox_edited_code = fixed_code
                    else:
                        with st.spinner("Uruchamiam testy…"):
                            results = run_static_tests(edited_code)
                        st.session_state.sandbox_edited_code = edited_code

                    st.session_state.sandbox_results = results
                    st.session_state.sandbox_approved = set()
                    st.session_state.sandbox_commit_done = None
                    st.rerun()

                st.markdown("---")
                st.markdown("**Wyniki testów**")
                results = st.session_state.get("sandbox_results")
                if not results:
                    st.caption("Kliknij '▶ Uruchom testy' aby zobaczyć wyniki.")
                else:
                    if "sandbox_approved" not in st.session_state:
                        st.session_state.sandbox_approved = set()
                    for r in results:
                        if r["name"].startswith("⚠️"):
                            st.session_state.sandbox_approved.add(r["name"])
                    passed_count = sum(
                        1 for r in results
                        if r["passed"] or r["name"].startswith("⚠️")
                    )
                    st.metric("Testy", f"{passed_count} / {len(results)}")
                    for r in results:
                        if r["passed"]:
                            st.success(f"✅ {r['name']}")
                        elif r["name"].startswith("⚠️"):
                            st.success(f"✅ {r['name']} — znany false positive, tak miało być")
                        else:
                            detail = f"błąd: {r['error']}" if r["error"] else f"oczekiwano: `{r['expected']}`, otrzymano: `{r['got']}`"
                            st.error(f"❌ {r['name']}\n\n{detail}")

                results = st.session_state.get("sandbox_results")
                if results:
                    approved = st.session_state.get("sandbox_approved", set())
                    all_clear = all(r["passed"] or r["name"] in approved for r in results)

                    if all_clear:
                        st.divider()
                        st.markdown("### Zatwierdź zmiany")
                        accepted_proposals = st.session_state.get("sandbox_accepted_proposals", [])
                        if accepted_proposals:
                            st.markdown("**Które propozycje obejmuje ten commit?**")
                            commit_checked = []
                            for j, p in enumerate(accepted_proposals):
                                if st.checkbox(p["title"], value=True, key=f"commit_prop_{j}"):
                                    commit_checked.append(p)
                            hints = "; ".join(p["commit_hint"] for p in commit_checked)
                        else:
                            hints = ""
                        commit_msg = st.text_input("Commit message", value=hints, placeholder="fix: opisz co zostało zmienione")
                        commit_clicked = st.button(
                            "✅ Zatwierdź i zacommituj", type="primary",
                            disabled=not commit_msg.strip(), use_container_width=True,
                        )
                        if commit_clicked and commit_msg.strip():
                            edited = st.session_state.get("sandbox_edited_code", chunk.source)
                            repo_path = st.session_state.get("repo_paths", {}).get(
                                chunk.repo, st.session_state.get("repo_path", "")
                            )
                            with st.spinner("Zapisuję zmianę, commituję i wypycham branch…"):
                                abs_path = replace_function_in_file(chunk, edited, repo_path)
                                res = commit_and_push_change(abs_path, commit_msg.strip(), repo_path)
                            if not res.get("success"):
                                st.error(f"Błąd commita: {res.get('output') or 'nieznany błąd'}")
                            else:
                                st.session_state.sandbox_commit_done = res["commit_hash"] or "committed"
                                st.session_state.sandbox_commit_msg = commit_msg.strip()
                                st.session_state.sandbox_branch = res.get("branch", "")
                                st.session_state.sandbox_pushed = res.get("pushed", False)
                                st.session_state.sandbox_push_output = res.get("output", "")
                                st.session_state.sandbox_manual_push = res.get("manual_push_cmd", "")
                                st.session_state.sandbox_results = None
                                st.rerun()

                if st.session_state.get("sandbox_commit_done"):
                    st.success(f"✅ Zacommitowano: `{st.session_state.sandbox_commit_done}`")
                    if st.button("Przejdź dalej → PR", type="primary"):
                        _advance()

# ═══════════════════════════════════════════════════════════════════════════════
# KROK 4 — PR
# ═══════════════════════════════════════════════════════════════════════════════
elif active_tab == "pr":
    st.title("Pull Request")

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

    # ── Ścieżka Python (sample/legacy) ────────────────────────────────────────
    commit_hash = st.session_state.get("sandbox_commit_done")
    commit_msg = st.session_state.get("sandbox_commit_msg", "")
    branch = st.session_state.get("sandbox_branch", "")
    pushed = st.session_state.get("sandbox_pushed", False)
    push_output = st.session_state.get("sandbox_push_output", "")
    manual_push = st.session_state.get("sandbox_manual_push", "")
    proposals = st.session_state.get("sandbox_accepted_proposals", [])

    if not commit_hash:
        st.info("Brak zatwierdzonego commita. Wróć do kroku Piaskownica i zatwierdź zmianę.")
    else:
        if pushed:
            st.markdown(
                f"""
                <div style="background:#f0fdf4;border:1.5px solid #86efac;border-radius:12px;padding:16px 20px;margin-bottom:16px">
                    <div style="font-size:18px;font-weight:700;color:#166534">🚀 Branch <code>{branch}</code> wypchnięty</div>
                    <div style="color:#15803d;margin-top:4px;font-size:14px">
                        Pipeline GitHub Actions waliduje zmianę w Dockerze i przygotowuje Pull Request do <code>develop</code> (link w podsumowaniu przebiegu Actions; PR powstaje automatycznie, gdy repo zezwala Actions na tworzenie PR).
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.link_button("▶ Otwórz przebieg pipeline (Actions)",
                           "https://github.com/ai-bot-playground/shop-qa-ui/actions",
                           use_container_width=True)
            st.link_button("🔀 Pull Requesty",
                           "https://github.com/ai-bot-playground/shop-qa-ui/pulls",
                           use_container_width=True)
        else:
            st.warning(
                "Zmiana zacommitowana lokalnie, ale **branch nie został wypchnięty** "
                "(brak tokena GH_TOKEN lub błąd push). Wypchnij ręcznie, aby uruchomić pipeline:"
            )
            if manual_push:
                st.code(manual_push, language="bash")
            if push_output:
                with st.expander("Szczegóły błędu push"):
                    st.code(push_output, language=None)

        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        col1.markdown(f"**Branch źródłowy**  \n`{branch or '—'}`")
        col2.markdown("**Branch docelowy**  \n`develop`")
        col3.markdown(f"**Commit**  \n`{commit_hash}`")

        st.markdown("### 📋 Opis zmian")
        st.markdown(f"**{commit_msg}**")

        if proposals:
            st.markdown("**Zaakceptowane propozycje:**")
            for p in proposals:
                effort_icon = "🟢" if p["effort"] == "Bardzo niski" else ("🟡" if p["effort"] == "Niski" else "🔴")
                risk_icon = "🔴" if "Wysoki" in p["risk"] else ("🟢" if "Niski" in p["risk"] else "🟡")
                st.markdown(
                    f"- **{p['title']}** — nakład: {effort_icon} {p['effort']} · ryzyko: {risk_icon} {p['risk']}"
                )
                st.caption(f"  {p['description']}")

        st.markdown("---")
        st.markdown("### ✅ Checklist")
        st.markdown(f"""
- ✅ Testy statyczne przeszły (lub zaakceptowane false positive)
- ✅ Zmiany przejrzane przez agenta AI
- ✅ Propozycje zaakceptowane przez dewelopera (human-in-the-loop)
- {'✅' if pushed else '⏳'} Branch wypchnięty na GitHub → trigger pipeline
- ⏳ CI/CD pipeline waliduje w Dockerze i tworzy PR do `develop`
""")
        if pushed:
            st.balloons()

