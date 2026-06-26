# Specyfikacja produktu — Code Intelligence & Tribal-Knowledge Q&A

## Cel produktu

Narzędzie usprawniające pracę z kodem poprzez umożliwienie zadawania pytań w języku
naturalnym i otrzymywania odpowiedzi z dokładnym wskazaniem miejsca w kodzie realizującym
dane zadanie. Produkt redukuje ryzyko, optymalizuje koszty i przyspiesza pracę zarówno
z nieznanym kodem jak i przy tworzeniu nowych funkcjonalności.

Zastosowania:
- **Praca z istniejącym kodem** — analiza legacy code, wyjaśnianie nieudokumentowanej logiki,
  identyfikacja ryzyk przed zmianą
- **Rozwój nowego kodu** — szybkie zrozumienie kontekstu i zależności przed napisaniem
  nowej funkcjonalności
- **Dokumentacja** — automatyczne generowanie opisów funkcji i modułów na podstawie kodu
- **Określanie logiki biznesowej** — przekładanie kodu na język zrozumiały dla biznesu,
  wyjaśnianie co system robi i dlaczego

Produkt ułatwia komunikację między zespołami technicznymi a biznesowymi i wspiera
onboarding nowych członków zespołu.

---

## Grupy docelowe

Dwie szerokie grupy — narzędzie jest użyteczne dla każdego kto pracuje z kodem lub
podejmuje decyzje dotyczące jego zmiany:

- **Użytkownicy techniczni** — developerzy, architekci, QA, DevOps i inni.
  Interesuje ich: ścieżka do pliku i linii, kod źródłowy, cytowania, techniczne szczegóły
  implementacji.

- **Użytkownicy nietechniczni** — managerowie, product ownerzy, analitycy biznesowi,
  stakeholderzy i inni. Interesuje ich: wpływ na biznes, szacowany czas, ryzyko zmiany,
  zależności systemowe — bez kodu.

---

## Workflow użytkownika

Aplikacja prowadzi użytkownika przez cztery etapy w ustalonej kolejności.
Nie można przejść do kolejnego etapu bez ukończenia poprzedniego.
Do ukończonych etapów można wracać.

```
System Ready → Analyze → Piaskownica → PR
```

### 1. System Ready

Użytkownik wskazuje ścieżkę do repozytorium. System indeksuje kod i pokazuje listę
wykrytych symboli (funkcji, klas). Po pomyślnym zaindeksowaniu można przejść dalej.
Kolejne wersje aplikacji umożliwią integrację z innymi źródłami danych jak np Jira, Confluence, dokumentacja techniczna, bazy danych itp.

**Strategia indeksowania:** System nie wykonuje pełnej reindeksacji przy każdym uruchomieniu.
Indeks jest budowany raz i aktualizowany przyrostowo — reindeksacja wyzwalana jest przez
zdarzenie Merge PR, co minimalizuje zbędne przetwarzanie.

### 2. Analyze

Serce aplikacji. Użytkownik zadaje pytanie. Agent zwraca odpowiedź w języku pytania:
System zwraca odpowiedź w dwóch trybach do wyboru:

**Tryb Biznesowy** — odpowiedź bez kodu:
- Opis problemu (co się dzieje i dlaczego to ważne)
- Metryki czasu: Dev / Test / Łącznie
- Impact i obszar biznesowy
- Ryzyko zmiany
- Zależności systemowe

**Tryb Techniczny** — odpowiedź z kodem:
- Treść odpowiedzi
- Ścieżka do pliku i numer linii (format `plik:linia` — klikalny w IDE)
- Kod źródłowy funkcji

Każdy tryb ma konfigurowalny szablon — użytkownik może włączyć lub wyłączyć
poszczególne sekcje odpowiedzi według własnych potrzeb.

**Propozycje rozwiązania** — po otrzymaniu odpowiedzi system proponuje maksymalnie 3
podejścia do naprawy problemu. Jedna propozycja jest oznaczona jako rekomendowana.
Każda propozycja zawiera:
- Tytuł i opis
- Szacowany nakład (Bardzo niski / Niski / Średni)
- Ryzyko (Niski / Średni / Wysoki)
- Sugerowany commit message

Użytkownik zaznacza interesujące go propozycje (checkboxy, wielokrotny wybór) i akceptuje
wybór. Dopiero po akceptacji przynajmniej jednej propozycji pojawia się przycisk przejścia
do kolejnego etapu.

**Historia chatów** — wszystkie pytania i odpowiedzi są przechowywane w sesjach (wątkach).
Użytkownik może tworzyć nowe wątki i wracać do poprzednich.

### 3. Piaskownica (Sandbox)

Użytkownik widzi kod funkcji powiązanej z odpowiedzią i może go edytować.

Górna sekcja pokazuje zaakceptowane propozycje z Analyze jako panel referencyjny
(co chcemy osiągnąć, jakie jest ryzyko).

Po edycji użytkownik uruchamia testy automatyczne. Wyniki pokazują:
- Które testy przeszły
- Które nie przeszły (z detalami: oczekiwano / otrzymano)
- Dla testów które nie przeszły: możliwość zaznaczenia jako **false positive**
  (checkbox przy każdym nieudanym teście — jeśli błąd jest w teście, nie w kodzie)

**Zatwierdzanie zmian** pojawia się gdy wszystkie testy przeszły lub nieudane zostały
zaakceptowane jako false positive. Użytkownik:
- Widzi listę zaakceptowanych propozycji z checkboxami — wybiera które obejmuje ten commit
- Commit message jest automatycznie złożony z hintów zaznaczonych propozycji
- Może ręcznie edytować commit message
- Zatwierdza zmiany (zapis do pliku + git commit)

### 4. PR

Podsumowanie wykonanej pracy. Użytkownik widzi:
- Hash commita i commit message
- Diff zmian
- Formularz Pull Requesta (tytuł, opis)
- Przycisk utworzenia PR

---

## Kluczowe zasady UX

**Nawigacja przez postęp** — stepper na górze strony wizualizuje etapy jako kółka
z numerami połączone linią. Zablokowane = szare, aktywne nieukończone = biała ramka,
ukończone = fioletowe z checkmarkiem, klikalne żeby wrócić.

**Accenture branding** — kolor wiodący #A100FF (fiolet). Przyciski główne w tym kolorze.

**Język** — interfejs w języku polskim.

---

## Architektura agentowa

Prototyp używa hardkodowanych odpowiedzi dopasowywanych słowami kluczowymi.
Docelowa architektura zakłada podpięcie agentów AI jako warstwy pośredniej —
funkcje `run_qa()` i `generate_plan()` są punktami integracji.

**Placeholdery agentów:**

| Agent | Odpowiedzialność |
|---|---|
| `QAAgent` | Odpowiada na pytania w języku naturalnym na podstawie zaindeksowanego kodu |
| `ProposalAgent` | Generuje propozycje rozwiązań z oceną ryzyka i nakładu |
| `PlanAgent` | Tworzy plany implementacji (Jira-ready) z estymacją |
| `IndexAgent` | Zarządza indeksem kodu, wyzwala reindeksację po Merge PR |

comment: nie twórzmy agentów którzy robia czynnosci które moga wykonac skrypty, automatycznie uruchamiane.

**Docelowa integracja:** Azure AI Foundry jako platforma bazowa.
Architektura przewiduje możliwość podpięcia innych dostawców (OpenAI, Anthropic, lokalnych
modeli) przez ujednolicony interfejs agenta.

---

## Struktura techniczna (overview)

```
prototype/
├── app.py                  # Streamlit UI — cały workflow
├── src/
│   ├── ingest.py           # Parsowanie kodu (AST) → CodeChunk
│   ├── retriever.py        # Wyszukiwanie po słowach kluczowych
│   ├── agent.py            # Logika Q&A, kontekst biznesowy, propozycje rozwiązań
│   ├── sandbox.py          # Testy statyczne, zamiana kodu w pliku, git commit
│   ├── answer_types.py     # Definicje typów odpowiedzi i domyślnych szablonów
│   └── jira_planner.py     # Generator planów (przygotowany dla PlanAgent)
└── run.sh                  # Uruchomienie: streamlit run app.py
```

---

## Dane demo

Repozytorium testowe: `acc-ai-hackathon/sample/legacy_billing/billing.py`

Dwie funkcje z hardkodowanymi danymi:

**`cancel_order`** — cicha awaria gdy zamówienie wysłane (zwraca False bez błędu)
- 3 propozycje naprawy: wyjątek / słownik z błędem / logging
- Testy: pending→True, shipped→False

**`calc_lf`** — obliczanie opłat za opóźnienie (stawka 1.5% do 30 dni, 2.5% powyżej)
- 3 propozycje: poprawka granicy / walidacja / parametryzacja stawek
- Testy: 0 dni, 10 dni, 31 dni + 1 celowy false positive (granica 30 dni)

Pytania które działają:
- `Dlaczego anulowanie zamówienia cicho nie działa?`
- `Jak obliczana jest opłata za opóźnienie?`
- `Jakie są stawki opłat?`

---

## Co prototyp demonstruje

1. Zadajesz pytanie biznesowe → dostajesz odpowiedź na poziomie biznesowym (bez kodu)
2. Przełączasz na techniczny → widzisz dokładne miejsce w kodzie z cytowaniem
3. Wybierasz propozycje rozwiązania → przechodzisz do sandboxa z kontekstem
4. Edytujesz kod → uruchamiasz testy → akceptujesz false positive jeśli test jest błędny
5. Commitujesz zmiany z opisem powiązanym z zaakceptowanymi propozycjami
6. Tworzysz Pull Request

Cały flow od pytania do PR bez wychodzenia z aplikacji.
