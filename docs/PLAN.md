# Implementation plan

> Status: **READY** — Satchmo confirmed, stack finalized.

---

## What we're building

RAG-based conversational Q&A system over legacy Python code:
- ingests `.py` files, chunks by function/class with full location metadata
- embeds chunks into Qdrant (persistent vector store)
- answers plain-English questions with **source citations** (file:line)
- maintains **conversation history** per session (SQLite)
- **refuses** to answer when information is not in the codebase
- evaluates itself against a benchmark Q&A set

---

## Tech stack

| Component | Choice | Reason |
|---|---|---|
| LLM | `claude-sonnet-4-6` | Required; best reasoning for code |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) | Free, local, no extra API key |
| Vector store | **Qdrant** (Docker service) | Persistent, rich payload filtering by file/line/function |
| Conversation history | **SQLite** (file in app container) | Zero infra, sufficient for demo |
| Python parser | `ast` stdlib | Extracts functions/classes with exact line numbers |
| Runtime | Python 3.12 | |
| Container | Podman + podman-compose | User's setup |

---

## Infrastructure

```
podman-compose up
  ├─ app          (Python 3.12, port 8501 if Streamlit)
  │    └─ sqlite.db  (conversation history, on named volume)
  └─ qdrant       (qdrant/qdrant, port 6333, on named volume)
```

`compose.yaml`:
```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

  app:
    build: .
    ports:
      - "8501:8501"
    environment:
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - QDRANT_URL=http://qdrant:6333
    volumes:
      - app_data:/app/data
      - ./legacy-satchmo:/app/codebase:ro
    depends_on:
      - qdrant

volumes:
  qdrant_data:
  app_data:
```

---

## Project structure

```
acc-ai-hackathon/
├── legacy-satchmo/          ← source of truth (read-only mount)
├── sample/                  ← smoke-test dataset
├── src/
│   ├── ingest.py            ← parse .py → chunks with metadata
│   ├── store.py             ← embed + upsert into Qdrant
│   ├── history.py           ← SQLite conversation history
│   ├── agent.py             ← retrieve + Claude Q&A + refusal logic
│   └── eval.py              ← run questions.csv, compute pass rate
├── prompts/
│   └── qa_system.txt        ← system prompt for Q&A agent
├── main.py                  ← CLI: ingest | ask | eval
├── requirements.txt
├── Dockerfile
└── compose.yaml
```

---

## Data model

### Qdrant point (one per function/class/module-level block)

```python
{
    "id":      "<uuid>",
    "vector":  [...],          # sentence-transformers embedding
    "payload": {
        "content":   "def force_recalculate_total(self):\n    ...",
        "file":      "satchmo_store/shop/models.py",
        "line_start": 881,
        "line_end":   980,
        "name":      "force_recalculate_total",
        "type":      "method",   # function | method | class | module
        "class_name": "Order",   # null if top-level
        "repo":      "legacy-satchmo"
    }
}
```

### SQLite — conversation history

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT REFERENCES sessions(id),
    role TEXT,          -- 'user' | 'assistant'
    content TEXT,
    citations TEXT,     -- JSON array of {file, line, name}
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Phases

### Phase 1 — Ingestion (`src/ingest.py`)

Parse Python files with `ast`, extract function/class-level chunks:
- walk target files in `legacy-satchmo/satchmo/apps/`
- for each `FunctionDef`, `AsyncFunctionDef`, `ClassDef` → extract source + metadata
- also capture module-level constants (e.g. `ORDER_STATUS`, `TAX_RATE`)

Target files:
- `satchmo_store/shop/models.py`
- `payment/models.py`
- `payment/modules/base.py`
- `tax/modules/percent/processor.py`
- `product/models.py`
- `product/utils.py`

### Phase 2 — Embedding & store (`src/store.py`)

- embed each chunk with `sentence-transformers`
- upsert into Qdrant collection `legacy_code`
- idempotent: skip if `id` already exists (safe to re-run)

### Phase 3 — Conversation agent (`src/agent.py`)

```
user question + session_id
        │
        ▼
load last N messages from SQLite  (conversation context)
        │
        ▼
Qdrant.search(query_vector, limit=5)   ← optional: filter by file
        │
        ▼
Claude(
  system  = qa_system.txt,
  messages = history + [{"role":"user", "content": question}],
  context  = top-5 chunks with file:line labels
)
        │
        ├─ answer + citations  →  save to SQLite, return
        └─ NOT_IN_CODEBASE     →  save to SQLite, return refusal
```

**System prompt core constraint:**
```
Answer using ONLY the provided source code excerpts.
Every factual claim MUST be followed by a citation [file:line].
If the answer cannot be determined from the excerpts, respond with:
NOT_IN_CODEBASE
Do not speculate. Do not use external knowledge about Satchmo or Django.
```

### Phase 4 — Evaluation (`src/eval.py`)

- reads `sample/questions.csv`
- for each question: run agent (fresh session), compare to expected answer
- scoring:

| Result | Condition |
|---|---|
| PASS | Answer contains expected keywords + valid citation |
| REFUSE_OK | Q10-type + system returns NOT_IN_CODEBASE |
| FAIL | Wrong answer or no citation |

- prints: `Passed: 9/10 (90%)`

### Phase 5 — CLI / UI (`main.py`)

```bash
python main.py ingest                          # ingest + embed
python main.py ask "What is the tax rate?"     # one-off question
python main.py chat                            # interactive session with history
python main.py eval sample/questions.csv     # run benchmark
```

Optional Streamlit UI (if time): question box + answer + highlighted citation + chat history panel.

---

## Bonus targets (if time allows)

| Bonus | Implementation | Effort |
|---|---|---|
| Tool use | Agent calls `get_source(file, line)` tool to fetch exact raw lines | Low |
| Payload filtering | "search only in `shop/models.py`" via Qdrant filter | Low |
| Auto-doc generation | Second prompt: generate docstring for any function | Low |
| Multi-agent | Retriever agent + Answerer agent via Claude tool use | Medium |
| Human-in-the-loop | Show retrieved chunks before answering, ask confirmation | Medium |
| Streamlit UI | Chat interface + source viewer panel | Medium |

---

## requirements.txt

```
anthropic>=0.30
qdrant-client>=1.9
sentence-transformers>=3.0
streamlit>=1.35        # optional UI
```

---

## Responsible AI

**Risk:** Hallucination — LLM invents an answer not grounded in the code.
**Mitigation:**
1. Strict prompt: citation required on every claim
2. `NOT_IN_CODEBASE` fallback enforced in prompt
3. Eval harness measures refusal accuracy (Q10)
4. Retrieved chunks shown to user (transparency)

---

## Work split (8h hackathon, 5 people)

| Person | Task | Hours |
|---|---|---|
| P1 | `ingest.py` + `store.py` | h1–h2 |
| P2 | `agent.py` + `history.py` + system prompt | h1–h3 |
| P3 | `eval.py` + Satchmo Q&A benchmark | h1–h3 |
| P4 | `compose.yaml` + `Dockerfile` + `main.py` CLI | h2–h3 |
| P5 | Streamlit UI + slides + demo script | h3–h6 |
| All | Integration, fix, rehearsal | h4–h8 |

---

## Demo script (3 min)

1. **(0:00–0:30)** Show `shop/models.py` — "1000 lines, no docs, magic strings, author unknown"
2. **(0:30–1:30)** Live Q&A: 3 questions with answers + citations, follow-up question using history
3. **(1:30–2:00)** Ask Q10 (payment retries) — show NOT_IN_CODEBASE refusal
4. **(2:00–2:30)** Show eval output: `Passed: 10/10`
5. **(2:30–3:00)** Responsible AI + next steps slide
