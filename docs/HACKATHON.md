# Hackathon T09 — Legacy Code Documenter & Tribal-Knowledge Q&A

## Challenge summary

Build an LLM-based system that:
1. Ingests legacy code
2. Auto-generates documentation (what, how, why)
3. Answers plain-English questions about the code with citations to source
4. Refuses to answer when information is not in the codebase (no hallucination)

**Judging weights:** Impact 30% · Claude/agentic design 25% · Demo completeness 20% · Creativity 15% · Responsible AI 10%

---

## Key decisions

| Topic | Decision | Notes |
|---|---|---|
| Base repo | **Satchmo** (`dokterbob/satchmo`) ✅ | See [REPO.md](REPO.md) |
| LLM | Claude (Anthropic) | Required by rules |
| Demo scenario | billing / inventory / orders | Matches provided examples 1:1 |

---

## Current state

- `acc-ai-hackathon` repo contains `sample/` + planning docs ✅
- Satchmo forked (`https://github.com/Acc-Ai-Hackaton/satchmo.git`) ✅
- Satchmo cloned to `legacy-satchmo/` ✅
- Satchmo explored — billing, inventory, orders confirmed ✅
- Implementation plan ready to be detailed — **next step**

---

## Open questions

- [ ] Decide on UI: CLI vs simple web UI
- [ ] Decide on vector store: in-memory (chromadb) vs hosted
- [ ] Confirm team members and roles

---

## Scenario

Phase 1: demo against provided `sample/` (billing, inventory, orders) — quick smoke test.
Phase 2: main demo against Satchmo modules (`payment/`, `product/`, `satchmo_store/shop/`).
See [SCENARIO.md](SCENARIO.md) for the full question mapping (updated with Satchmo symbols).

---

## Links

- [Repo & legacy code analysis](REPO.md)
- [Demo scenario & Q&A mapping](SCENARIO.md)
- [Implementation plan](PLAN.md)
- [Team playbook](AI_HACKATHON_PLAYBOOK.md)
- [Rules & requirements](TASK_AND_RULES_AND_REQUIREMENTS.md)
- [Task description (PL)](hacaton-polecenie-wymagania.txt)
- Provided examples: `sample/billing.py`, `sample/inventory.py`, `sample/orders.py`
- Evaluation set: `sample/questions.csv`
