# INFRASTRUCTURE.md — szkielet architektury (Docker / Podman + Kubernetes)

> Warstwa **infra** dla T09 *Legacy Code Documenter & Tribal-Knowledge Q&A*.
> Łączy infra (Docker/Podman + k8s) z kodem aplikacji przeniesionym z brancha
> `lk-prototype-adjustment`. Towarzyszy: [SPEC.md](SPEC.md),
> [PLAN.md](PLAN.md), [prototype.md](prototype.md).

## 1. Co to skonteneryzowuje

Aplikacja to **monolit Streamlit** (jeden proces, port `8501`):

- `streamlit run app.py` — całość workflow (System Ready → Analyze → Piaskownica → PR).
- Warstwa deterministyczna (`ast`, retrieval, sandbox: `pytest` + `git` w subprocess).
- Wywołania LLM przez seam `src/agent.py:llm_complete()` (provider: **azure** | anthropic).
- Indeksuje repo z domyślnej ścieżki **`sample/order_service`** (filesystem) — stąd potrzeba wolumenu.
  Docelowo `legacy-satchmo`, gdy dojdzie zapis wyników analizy.

Dlatego obraz zawiera **git** (sandbox/commit, uruchamianie pytest). Transport LLM dla
providera `azure` to `urllib` (stdlib); `requests` jest tylko dla diagnostyki
([`scripts/check_endpoints.py`](../scripts/check_endpoints.py)).

## 2. Topologia

```
                 ┌───────────────────────────────────────────────┐
                 │  kontener: legacy-documenter (python:3.12)     │
   :8501  ──────▶│  entrypoint.sh                                 │
   (HTTP/WS)     │    ├─ app.py istnieje?  → streamlit run app.py │
                 │    └─ nie ma?           → placeholder_app.py   │
                 │  git + pytest (sandbox)                        │
                 │  REPO_PATH ──▶ repo do indeksowania            │
                 │  .index_cache (wolumen, indeks 1×)             │
                 └───────────────┬───────────────────────────────┘
                                 │ HTTPS (urllib, Bearer)
                                 ▼
                 Azure AI Foundry  (ai-remik.services.ai.azure.com)
                   ├─ {AZURE_AI_ENDPOINT}/v1/messages  → claude-opus-4-8  (AKTYWNY: analiza/Q&A + docs)
                   └─ /openai/v1/responses              → gpt-5.4-mini     (PLACEHOLDER: jeszcze niewpięty)
```

**Baked vs mounted:** obraz piecze kod (deployment standalone). W trybie dev
`compose.yaml` bind-montuje całe repo (z `.git`), więc Streamlit przeładowuje się na
żywo, a sandbox commituje do realnej historii git.

## 3. Skąd pochodzi kod (integracja)

| Warstwa | Źródło | Uwaga |
|---|---|---|
| `app.py`, `src/*`, `run.sh` | branch `lk-prototype-adjustment` | skopiowane; logika niezmieniana |
| infra (Containerfile, compose, k8s, docker/, scripts/) | branch `chore/infra-skeleton` | ta warstwa |
| `legacy-satchmo/` | gitlink na `develop` | **przyszły** cel indeksowania (gdy dojdzie zapis wyników); na razie nieużywany |

**Minimalna zmiana w kodzie aplikacji** (ujednolicenie nazw):
- `app.py` — etykieta UI `AZURE_OPENAI_DEPLOYMENT` → `AZURE_AI_DEPLOYMENT` (zgodność z resztą kodu).

Cel indeksowania = `sample/order_service` (toy demo jury). Przejście na `legacy-satchmo`:
zmień default w `app.py`, `REPO_PATH` w configu oraz wpis w `.dockerignore`.

`entrypoint.sh` uruchamia `app.py` jeśli istnieje, inaczej placeholder.

## 4. Kontrakt LLM (env)

Nazwy zgodne z kodem ([`src/agent.py`](../src/agent.py)). Pełny szablon:
[`.env.docker.example`](../.env.docker.example). Wywołanie zweryfikowane (HTTP 200) z wnętrza kontenera.

| Zmienna | Rola |
|---|---|
| `LLM_PROVIDER=azure` | wybór gałęzi w `llm_complete` (alt: `anthropic`) |
| `AZURE_AI_ENDPOINT` | `https://ai-remik.services.ai.azure.com/anthropic` (kod dokleja `/v1/messages`) |
| `AZURE_AI_API_KEY` | auth **Bearer** |
| `AZURE_AI_DEPLOYMENT=claude-opus-4-8` | model AKTYWNY (analiza/Q&A + docs) |
| `AZURE_AI_DEPLOYMENT_FAST=gpt-5.4-mini` | model MAŁY — **placeholder w configu, kod jeszcze nie używa** |
| `REPO_PATH=sample/order_service` | repo do indeksowania (informacyjne; app.py ma własny default) |

Aktualny `src/agent.py:_llm_azure` używa **jednego** deploymentu (`AZURE_AI_DEPLOYMENT`)
dla wszystkich wywołań — gpt nie jest jeszcze routowany. Gdy zostanie wpięty, dodać gałąź
`/openai/v1/responses` (kształt: [`scripts/check_endpoints.py`](../scripts/check_endpoints.py))
oraz `AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_API_KEY`.

> **Diagnostyka łączności:** [`scripts/check_endpoints.py`](../scripts/check_endpoints.py)
> testuje aktywny endpoint (i opcjonalnie gpt, gdy `AZURE_OPENAI_ENDPOINT` ustawiony):
> ```powershell
> podman exec --env PYTHONUTF8=1 <kontener> python scripts/check_endpoints.py
> ```

## 5. Uruchomienie

### Lokalnie (Podman, zalecane)

```bash
cp .env.docker.example .env.docker     # uzupełnij AZURE_AI_API_KEY
podman compose up --build              # http://localhost:8501
```

Gdyby `app.py` zniknął, kontener wstaje na placeholderze (health + status). To samo
działa z `docker compose`.

### Sam obraz

```bash
podman build -t legacy-documenter:dev -f Containerfile .
podman run --rm -p 8501:8501 --env-file .env.docker legacy-documenter:dev
```

### Uwagi Podman na Windows (zweryfikowane na tej maszynie)

- **`HEALTHCHECK` z Containerfile** jest ignorowany, gdy obraz jest w formacie OCI
  (domyślny Podman). Aby go zachować: `podman build --format docker ...`. Niezależnie
  od tego, health działa na poziomie `compose.yaml` (klucz `healthcheck`) i jako probes w k8s.
- **Dostęp z hosta przez `localhost:8501` może nie działać** (rootless Podman+WSL nie
  forwarduje opublikowanego portu na localhost Windows). Aplikacja jest wtedy osiągalna
  pod **IP maszyny WSL**:
  ```powershell
  podman machine ssh hostname -I        # np. 172.22.7.204
  # → http://172.22.7.204:8501
  ```
  Wewnątrz kontenera health zawsze odpowiada `200 ok` na `127.0.0.1:8501/_stcore/health`.

### Kubernetes

Patrz [`deploy/k8s/README.md`](../deploy/k8s/README.md).

## 6. Pliki infry

```
Containerfile              # obraz (python:3.12 + git, deps z requirements.txt)
.dockerignore              # mały kontekst (bez .git, .venv, legacy-satchmo)
compose.yaml               # dev/demo (bind-mount repo, cache indeksu, healthcheck)
.env.docker.example        # kontrakt env (AZURE_AI_*, opus aktywny + gpt placeholder)
docker/
  ├─ entrypoint.sh         # app.py | placeholder
  └─ placeholder_app.py    # strona-szkielet (fallback gdy brak app.py)
scripts/check_endpoints.py # diagnostyka łączności LLM
deploy/k8s/                # generyczny szkielet k8s (placeholder)
docs/INFRASTRUCTURE.md     # ten plik
```

## 7. Świadome decyzje / ograniczenia

- **Kod aplikacji zmieniany minimalnie** — tylko 2 linie w `app.py` (§3). Logika
  `src/*` z `lk-prototype-adjustment` nietknięta (branch nadal się rozwija).
- **`legacy-satchmo` (przyszły cel)** — zagnieżdżone repo git (gitlink, ~487 .py). Na razie
  nieużywane i wykluczone z obrazu (`.dockerignore`). Wejdzie, gdy aplikacja będzie umiała
  zapisywać wyniki analizy; wtedy re-indeks całego repo przy każdym pytaniu (`run_qa`) trzeba
  będzie zoptymalizować po stronie kodu aplikacji.
- **gpt-5.4-mini jest tylko w configu** — `src/agent.py` w trybie azure używa jednego
  deploymentu (opus). Routing do gpt = przyszła zmiana w kodzie aplikacji.
- **Streamlit = stan w pamięci** → domyślnie 1 replika (skalowanie: sticky sessions).
- **Python 3.12** (stabilny dla Streamlit). `test-endpoint/` używa 3.14 — osobny podprojekt.
- **Sekrety** nigdy w obrazie/gicie — wstrzykiwane runtime (env_file / k8s Secret / Key Vault).
