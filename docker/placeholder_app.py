"""placeholder_app.py — strona uruchamiana, gdy właściwy app.py nie jest jeszcze wpięty.

Celowo NIE importuje src/* (poza opcjonalnym sprawdzeniem obecności), żeby działać nawet
bez kodu aplikacji. Pełni rolę "żywego" health-checka szkieletu infrastruktury i listy
punktów wpięcia kodu.
"""
import os

import streamlit as st

ACCENTURE_PURPLE = "#A100FF"

# Moduły aplikacji — punkty wpięcia kodu (docs/SPEC.md).
INTEGRATION_POINTS = [
    ("app.py", "Streamlit UI — pełny workflow"),
    ("src/ingest.py", "AST → CodeChunk + call graph"),
    ("src/retriever.py", "keyword retrieval + stałe"),
    ("src/agent.py", "llm_complete + run_qa + proposals"),
    ("src/doc_generator.py", "generate_docs + module overview"),
    ("src/answer_types.py", "szablony + stałe refusal"),
    ("src/sandbox.py", "apply_edit + run_tests + git_commit"),
]

st.set_page_config(page_title="shop-qa-ui — szkielet", page_icon="🧩", layout="wide")

st.markdown(
    f"<h1 style='color:{ACCENTURE_PURPLE}'>🧩 shop-qa-ui — szkielet infrastruktury</h1>",
    unsafe_allow_html=True,
)
st.info(
    "Kontener i sieć działają. To strona-placeholder — uruchamia się, gdy `app.py` "
    "nie został jeszcze wpięty. Gdy tylko pojawi się `app.py`, entrypoint przełączy się "
    "na właściwą aplikację (wystarczy restart kontenera / w trybie dev — przeładowanie)."
)

st.subheader("Punkty wpięcia kodu")
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
