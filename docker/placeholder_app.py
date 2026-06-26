"""placeholder_app.py — strona uruchamiana, gdy właściwy app.py nie jest jeszcze wpięty.

Celowo NIE importuje src/* (poza opcjonalnym sprawdzeniem obecności), żeby działać
zanim instancje T1–T5 dostarczą kod. Pełni rolę "żywego" health-checka szkieletu
infrastruktury i listy punktów wpięcia.
"""
import os

import streamlit as st

ACCENTURE_PURPLE = "#A100FF"

# Moduły, które dostarczają instancje T1–T5 (docs/SPEC.md §6). To są punkty wpięcia.
INTEGRATION_POINTS = [
    ("app.py", "Streamlit UI — pełny workflow (T4/T5)"),
    ("src/ingest.py", "AST → CodeChunk + call graph (T1)"),
    ("src/retriever.py", "keyword retrieval + stałe (T1)"),
    ("src/agent.py", "llm_complete + run_qa + proposals (T2)"),
    ("src/doc_generator.py", "generate_docs + module overview (T2)"),
    ("src/answer_types.py", "szablony + stałe refusal (T2)"),
    ("src/sandbox.py", "apply_edit + run_tests + git_commit (T3)"),
    ("src/jira_planner.py", "generate_jira_plan (T3)"),
]

st.set_page_config(page_title="Legacy Code Documenter — szkielet", page_icon="🧩", layout="wide")

st.markdown(
    f"<h1 style='color:{ACCENTURE_PURPLE}'>🧩 Legacy Code Documenter — szkielet infrastruktury</h1>",
    unsafe_allow_html=True,
)
st.info(
    "Kontener i sieć działają. To strona-placeholder — uruchamia się, gdy `app.py` "
    "nie został jeszcze wpięty. Gdy tylko pojawi się `app.py`, entrypoint przełączy się "
    "na właściwą aplikację (wystarczy restart kontenera / w trybie dev — przeładowanie)."
)

st.subheader("Punkty wpięcia kodu (T1–T5)")
for path, desc in INTEGRATION_POINTS:
    icon = "✅" if os.path.exists(path) else "⬜"
    st.write(f"{icon} `{path}` — {desc}")

st.subheader("Konfiguracja runtime (env)")
cfg = {
    "LLM_PROVIDER": os.environ.get("LLM_PROVIDER", "(brak)"),
    "AZURE_AI_ENDPOINT": os.environ.get("AZURE_AI_ENDPOINT", "(brak)"),
    "AZURE_AI_DEPLOYMENT": os.environ.get("AZURE_AI_DEPLOYMENT", "(brak)"),
    "AZURE_AI_DEPLOYMENT_FAST": os.environ.get("AZURE_AI_DEPLOYMENT_FAST", "(brak)"),
    "REPO_PATH": os.environ.get("REPO_PATH", "(brak)"),
    "AZURE_AI_API_KEY": "✅ ustawiony" if os.environ.get("AZURE_AI_API_KEY") else "⬜ brak",
    "ANTHROPIC_API_KEY": "✅ ustawiony" if os.environ.get("ANTHROPIC_API_KEY") else "⬜ brak",
}
st.table({"zmienna": list(cfg.keys()), "wartość": list(cfg.values())})

st.caption("Szczegóły: docs/INFRASTRUCTURE.md")
