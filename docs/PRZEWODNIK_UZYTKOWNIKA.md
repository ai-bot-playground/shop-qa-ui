# Przewodnik użytkownika — Analizator Kodu

Ten przewodnik jest dla osób, które chcą **korzystać** z aplikacji — bez wiedzy
programistycznej. Tłumaczymy, do czego służy, i prowadzimy Cię krok po kroku przez ekran.

---

## Czym jest ta aplikacja?

To **asystent do starszego kodu**. Wyobraź sobie projekt, który ktoś napisał lata temu,
a osoba, która go znała, dawno odeszła. Nikt już nie pamięta, „dlaczego to działa tak,
a nie inaczej". Ta aplikacja pomaga:

- **zadać pytanie zwykłym językiem** („Dlaczego anulowanie zamówienia nie działa?") i dostać
  odpowiedź **z dokładnym wskazaniem miejsca w kodzie**, na którym jest oparta,
- zobaczyć **co to oznacza dla biznesu** (jak duży problem, ile czasu zajmie naprawa, jakie ryzyko),
- dostać **gotowe propozycje poprawy** i — jeśli się na nią zdecydujesz — **bezpiecznie ją
  przetestować** i przekazać dalej do zespołu.

Najważniejsze: aplikacja **nie zgaduje**. Jeśli odpowiedzi nie ma w kodzie, powie wprost
„Nie znaleziono w kodzie" — zamiast wymyślać.

> 💡 Nie musisz nic instalować ani pisać. Otwierasz adres w przeglądarce i klikasz.

---

## Zanim zaczniesz

1. Otwórz w przeglądarce adres podany przez Twój zespół (np. **http://localhost:8501**).
2. Jeśli u góry zobaczysz żółty pasek **„🧪 Tryb demonstracyjny"**, to znaczy, że aplikacja
   pokazuje **przykładowe odpowiedzi** (do nauki i klikania). Wszystko działa tak samo —
   tylko treść odpowiedzi jest poglądowa. Szczegóły: [§ Tryb demonstracyjny](#tryb-demonstracyjny).

Ekran ma dwie części:

- **panel po lewej** — wybór projektu do analizy i historia Twoich rozmów,
- **główna część** — pasek postępu z czterema krokami i właściwa praca.

Na górze widać **pasek postępu** z czterema etapami. Przechodzisz przez nie po kolei:

```text
   System Ready  →  Analyze  →  Piaskownica  →  PR
   (przygotuj)      (zapytaj)    (przetestuj)    (przekaż)
```

---

## Krok po kroku

### Przygotowanie: wskaż projekt (panel po lewej)

1. W polu **„Ścieżka do repozytorium"** zwykle jest już wpisany przykładowy projekt — możesz
   to zostawić.
2. Kliknij **„⚡ Indeksuj repozytorium"**. Aplikacja „przegląda" kod i wypisuje, ile elementów
   znalazła (np. **„✅ 7 symboli"**). To trochę jak zbudowanie spisu treści książki.
3. Gotowe — możesz zadawać pytania.

> „Symbol" to po prostu pojedynczy element kodu (np. funkcja). Nie musisz tego pamiętać.

### Krok 1 — System Ready (przygotuj)

Tu tylko potwierdzasz, że projekt został wczytany. Zobaczysz listę znalezionych elementów.
Kliknij **„Przejdź dalej →"**.

### Krok 2 — Analyze (zapytaj)

To serce aplikacji.

1. **Wybierz typ odpowiedzi** u góry:
   - **💼 Biznesowy** — język nietechniczny: na czym polega problem, jak duży jest jego wpływ,
     ile czasu zajmie naprawa, jakie jest ryzyko. **To zwykle widok dla Ciebie.**
   - **🔧 Techniczny** — dla programistów: szczegóły i fragmenty kodu.
2. **Wpisz pytanie** w polu tekstowym, zwykłym językiem. Przykłady:
   - *„Dlaczego anulowanie zamówienia cicho nie działa?"*
   - *„Jak obliczana jest opłata za opóźnienie?"*
   - *„Jaka jest polityka zwrotów?"*
3. Kliknij **„Zapytaj ➜"** i poczekaj chwilę.

**Co zobaczysz w odpowiedzi (widok Biznesowy):**

- **Podsumowanie** problemu w 1–2 zdaniach,
- **Czas realizacji** — szacunek: ⏱ Dev (programista), 🧪 Test, 📅 Łącznie,
- **Impact** (jak ważne) i **Obszar**, którego dotyczy,
- **Ryzyko** i **Zależności** (na co jeszcze może wpłynąć zmiana),
- **Propozycje rozwiązania** — patrz niżej.

> W widoku Technicznym dodatkowo rozwiniesz **„📎 Źródła"** — dokładne miejsca w kodzie
> (`plik:linia`), na których oparto odpowiedź. To dowód, że odpowiedź nie jest zmyślona.

**Propozycje rozwiązania.** Pod odpowiedzią aplikacja podaje kilka propozycji. Przy każdej są
kolorowe znaczniki:

| Znacznik | Znaczenie |
| --- | --- |
| 🟢 | mały nakład pracy / niskie ryzyko |
| 🟡 | średni |
| 🔴 | duży nakład / wysokie ryzyko |

Zaznacz „ptaszkiem" te propozycje, które Cię interesują (rozwiną opis), a następnie kliknij
**„✅ Akceptuj wybrane propozycje"**. Pojawi się przycisk **„Przejdź dalej →"**.

### Krok 3 — Piaskownica (przetestuj bezpiecznie)

„Piaskownica" to **bezpieczne miejsce do prób** — jak brudnopis. Nic, co tu zrobisz, nie psuje
prawdziwego projektu, dopóki sam tego nie zatwierdzisz.

1. Po lewej widać **kod oryginalny**, po prawej **propozycję zmiany** (możesz ją czytać; w razie
   potrzeby ktoś techniczny może ją podregulować).
2. Kliknij **„▶ Uruchom testy"**. Aplikacja sprawdza, czy zmiana działa poprawnie, i pokazuje
   wynik, np. **„Testy 5 / 5"** z listą ✅ / ❌.
   - Jeśli coś jest na czerwono, pojawi się przycisk **„🔧 Napraw kod i uruchom ponownie testy"** —
     aplikacja spróbuje poprawić i sprawdzić jeszcze raz.
   - Czasem zielony ✅ ma dopisek *„znany false positive, tak miało być"* — to celowo „błędny test",
     który można świadomie zaakceptować. Nie martw się nim.
3. Gdy wszystko jest zielone, pojawi się sekcja **„Zatwierdź zmiany"**. Wpisz krótki opis zmiany
   (albo zostaw podpowiedziany) i kliknij **„✅ Zatwierdź i zacommituj"**.

> ⚠️ **Ważne:** przycisk „✅ Zatwierdź i zacommituj" to **prawdziwe zapisanie zmiany** w projekcie
> i przekazanie jej dalej. To nie jest już próba. Klikaj go świadomie, gdy naprawdę chcesz zmianę
> przekazać. Wszystkie wcześniejsze kroki możesz klikać bez obaw.

### Krok 4 — PR (przekaż dalej)

„PR" (Pull Request) to **prośba o włączenie Twojej zmiany** do głównej wersji projektu — z prośbą
o przejrzenie przez zespół. Na tym ekranie zobaczysz potwierdzenie, że zmiana została przekazana,
oraz linki, pod którymi zespół może ją sprawdzić i zatwierdzić. Pojawi się też checklista
(co zostało zrobione). To koniec procesu. 🎉

---

## Widoki odpowiedzi: Biznesowy vs Techniczny

- **💼 Biznesowy** — odpowiada na pytanie „co to znaczy i co z tym zrobić": wpływ, czas, ryzyko.
- **🔧 Techniczny** — odpowiada na pytanie „jak to dokładnie działa w kodzie": treść + fragmenty kodu i ich lokalizacja.

Możesz przełączać się między nimi w dowolnej chwili. Pod **„⚙️ Konfiguruj szablon odpowiedzi"**
włączysz lub wyłączysz poszczególne elementy (np. ukryć szacunki czasu).

---

## Wątki i historia

Po lewej, w sekcji **„Historia wątków"**, każda rozmowa to osobny **wątek** (jak osobna notatka):

- **„＋ Nowy wątek"** — zaczynasz świeżą rozmowę,
- **„Wznów"** — wracasz do wcześniejszej,
- **„Kontekst →"** — zakładasz nowy wątek, przenosząc do niego streszczenie poprzedniego
  (przydatne, gdy chcesz drążyć temat dalej).

Dzięki temu możesz prowadzić kilka niezależnych analiz naraz.

---

## Tryb demonstracyjny

Jeśli aplikacja nie ma podłączonego modelu AI (brak „klucza"), działa w **trybie
demonstracyjnym**: pokazuje **przykładowe** odpowiedzi i propozycje. Poznasz go po:

- żółtym pasku **„🧪 Tryb demonstracyjny"** u góry,
- statusie **„🟡 Tryb demo"** w panelu po lewej (zamiast „🟢 LLM Available").

Wszystkie przyciski i kroki działają identycznie — to świetny sposób, żeby **przeklikać i poznać
aplikację** bez żadnej konfiguracji. Gdy zespół podłączy model, odpowiedzi staną się „prawdziwe"
automatycznie, a Ty nie musisz nic zmieniać.

---

## Najczęstsze pytania

**Dostałem/-am „Nie znaleziono w kodzie" — czy to błąd?**
Nie. To celowe i dobre zachowanie: aplikacja nie znalazła podstaw w kodzie i woli o tym
powiedzieć, niż coś zmyślić. Spróbuj zadać pytanie inaczej lub o inny obszar.

**Co oznaczają kolorowe kółka przy propozycjach?**
🟢 = łatwe/bezpieczne, 🟡 = średnie, 🔴 = duże/ryzykowne. Pomagają wybrać, od czego zacząć.

**Czy mogę coś zepsuć, klikając?**
Do kroku „Piaskownica" włącznie — nie. Dopiero przycisk **„✅ Zatwierdź i zacommituj"** zapisuje
prawdziwą zmianę. Wcześniej to bezpieczny brudnopis.

**Po co są „Źródła" / `plik:linia`?**
To wskazanie dokładnego miejsca w kodzie, na którym oparto odpowiedź — dowód, że jest
wiarygodna, a nie zmyślona.

**Odpowiedź długo się ładuje.**
To normalne — model AI „myśli". Poczekaj chwilę po kliknięciu „Zapytaj ➜".

---

## Mały słowniczek

| Termin | Po ludzku |
| --- | --- |
| Repozytorium / projekt | Zbiór plików z kodem, który analizujemy. |
| Indeksowanie | Wstępne „przejrzenie" kodu, żeby aplikacja wiedziała, co w nim jest. |
| Symbol | Pojedynczy element kodu (np. funkcja). |
| Cytowanie (`plik:linia`) | Wskazanie miejsca w kodzie, na którym oparto odpowiedź. |
| Propozycja | Sugerowana zmiana/poprawka wraz z oceną nakładu i ryzyka. |
| Piaskownica | Bezpieczne miejsce do testowania zmian (brudnopis). |
| Commit | Trwałe zapisanie zmiany w historii projektu. |
| PR (Pull Request) | Prośba o włączenie zmiany do głównej wersji, do przejrzenia przez zespół. |

---

Potrzebujesz informacji technicznych (jak to działa „pod maską", jak uruchomić, jak
skonfigurować)? Zajrzyj do [README.md](../README.md).
