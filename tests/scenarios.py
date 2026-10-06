"""Katalog scenariuszy zmian — od najprostszej po zmianę przez cały system.

Po co osobny katalog, skoro jest już `src/fake_llm.py`:
atrapa offline dopisuje komentarz na końcu pliku. Sprawdza, że MECHANIKA
przepływu działa, ale nie sprawdza niczego, co wymaga **realnego kodu** —
build Gradle przechodzi tak samo dla komentarza jak dla pustej zmiany.
Scenariusze poniżej niosą prawdziwe, kompilowalne zmiany w prawdziwych
serwisach `shop-*`, więc lokalna bramka (`gradlew classes testClasses`,
`npm ci && npm run build`) naprawdę coś weryfikuje: nowa metoda musi się
skompilować, nowa składowa rekordu musi być użyta we wszystkich miejscach,
a `V2__*.sql` musi być poprawnym SQL-em.

Skala scenariuszy rośnie celowo:

| ID | Zasięg                                   | Co sprawdza w aplikacji |
|----|------------------------------------------|-------------------------|
| S1 | 1 repo, 1 plik (modify)                  | najkrótsza ścieżka plan → generacja → walidacja |
| S2 | 1 repo, 3 pliki (2 modify + 1 create)    | tworzenie plików, migracja Flyway, spójność pól |
| S3 | 2 repa, 2 języki (Java + React)          | walidacja per repo: Gradle ORAZ npm muszą być zielone |
| S4 | 4 repa (3 × Java + React)                | zmiana przez warstwy: dane → logika → zdarzenia → UI → testy akceptacyjne |
| S5 | 1 repo, kod celowo niekompilowalny       | bramka wyłapuje błąd, pętla naprawcza go usuwa |

Każdy plik opisany jest funkcją `build(oryginał) -> nowa treść`, a nie
literałem: dzięki temu scenariusz nadąża za repozytorium. Gdy kotwica
(`_replace`) zniknie z kodu, test pada z czytelnym komunikatem zamiast po
cichu walidować coś innego, niż zakładał autor.
"""

from dataclasses import dataclass, field
from typing import Callable


class AnchorMissing(AssertionError):
    """Kotwica scenariusza nie występuje już w repozytorium (kod się rozjechał)."""


def _replace(original: str, anchor: str, replacement: str, *, where: str) -> str:
    """Podmiana po kotwicy, z twardym błędem gdy kotwicy brak.

    Cicha zgoda na brak kotwicy jest tu najgorszym wariantem: scenariusz
    „przeszedłby" walidację, nie zmieniając w istocie nic.
    """
    if anchor not in original:
        raise AnchorMissing(f"{where}: brak kotwicy w pliku:\n{anchor!r}")
    if original.count(anchor) != 1:
        raise AnchorMissing(
            f"{where}: kotwica występuje {original.count(anchor)}× (oczekiwano 1):\n{anchor!r}"
        )
    return original.replace(anchor, replacement)


@dataclass(frozen=True)
class PlannedFile:
    """Jeden plik planu — dokładnie to, co zwraca `agent.plan_change`, plus treść."""

    repo: str
    path: str
    action: str                      # modify | create
    reason: str
    build: Callable[[str], str]      # (oryginał; "" dla create) -> nowa treść


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    question: str
    proposals: list[dict]
    files: list[PlannedFile]
    # Fragmenty, które MUSZĄ znaleźć się w wygenerowanej treści — chronią przed
    # scenariuszem, który „przechodzi", bo tak naprawdę nic nie zmienił.
    expect_content: dict[str, list[str]] = field(default_factory=dict)
    # Scenariusz celowo niekompilowalny: bramka ma go odrzucić (S5).
    expect_validation_failure: bool = False
    repair: dict[str, Callable[[str], str]] = field(default_factory=dict)

    @property
    def repos(self) -> list[str]:
        out: list[str] = []
        for f in self.files:
            if f.repo not in out:
                out.append(f.repo)
        return out

    def plan_json(self) -> dict:
        return {
            "files": [
                {"repo": f.repo, "path": f.path, "action": f.action, "reason": f.reason}
                for f in self.files
            ]
        }


# ── S1 — jeden serwis, jeden plik ────────────────────────────────────────────
# Najprostsza możliwa zmiana o realnej wartości: nowy endpoint zliczający
# produkty. Jeden plik, jedno repo, brak nowych zależności.

_CATALOG_CONTROLLER = "src/main/java/com/shop/catalog/api/ProductController.java"


def _s1_controller(original: str) -> str:
    return _replace(
        original,
        '    @GetMapping("/{id}")',
        '    @GetMapping("/count")\n'
        "    public long count() {\n"
        "        return repo.count();\n"
        "    }\n"
        "\n"
        '    @GetMapping("/{id}")',
        where=_CATALOG_CONTROLLER,
    )


S1_SINGLE_FILE = Scenario(
    id="S1",
    title="Jeden serwis, jeden plik — nowy endpoint GET /products/count",
    question="Dodaj endpoint zwracający liczbę produktów w katalogu.",
    proposals=[{
        "title": "Licznik produktów w katalogu",
        "description": "GET /products/count zwraca liczbę rekordów z ProductRepository.",
        "commit_hint": "feat(catalog): endpoint GET /products/count",
    }],
    files=[PlannedFile(
        repo="shop-catalog", path=_CATALOG_CONTROLLER, action="modify",
        reason="Nowy endpoint licznika produktów.", build=_s1_controller,
    )],
    expect_content={_CATALOG_CONTROLLER: ["/products/count".rsplit("/", 1)[-1], "repo.count()"]},
)


# ── S2 — jeden serwis, wiele warstw (dane + encja + DTO) ─────────────────────
# Dodanie pola `sku`: migracja Flyway (NOWY plik), encja JPA i DTO odpowiedzi.
# Sprawdza ścieżkę `action=create`, walidację składni `.sql` oraz to, że pole
# musi być nazwane tak samo w trzech plikach, inaczej Java się nie skompiluje.

_CATALOG_PRODUCT = "src/main/java/com/shop/catalog/domain/Product.java"
_CATALOG_RESPONSE = "src/main/java/com/shop/catalog/api/ProductResponse.java"
_CATALOG_MIGRATION = "src/main/resources/db/migration/V2__product_sku.sql"

_SKU_MIGRATION = """\
-- Kod SKU produktu. Dodawany addytywnie: V1 jest już zastosowana i nietykalna.
ALTER TABLE products ADD COLUMN sku VARCHAR(64);

UPDATE products SET sku = 'SKU-' || id WHERE sku IS NULL;

CREATE UNIQUE INDEX idx_products_sku ON products (sku);
"""


def _s2_product(original: str) -> str:
    with_field = _replace(
        original,
        '    @Column(name = "image_url")\n    private String imageUrl;\n',
        '    @Column(name = "image_url")\n    private String imageUrl;\n'
        "\n"
        '    @Column(length = 64)\n    private String sku;\n',
        where=_CATALOG_PRODUCT,
    )
    return _replace(
        with_field,
        "    public String getImageUrl() {\n        return imageUrl;\n    }\n",
        "    public String getImageUrl() {\n        return imageUrl;\n    }\n"
        "\n"
        "    public String getSku() {\n        return sku;\n    }\n",
        where=_CATALOG_PRODUCT,
    )


def _s2_response(original: str) -> str:
    with_component = _replace(
        original,
        "        String imageUrl,\n        String category) {",
        "        String imageUrl,\n        String sku,\n        String category) {",
        where=_CATALOG_RESPONSE,
    )
    return _replace(
        with_component,
        "                p.getImageUrl(),\n                p.getCategory()",
        "                p.getImageUrl(),\n                p.getSku(),\n                p.getCategory()",
        where=_CATALOG_RESPONSE,
    )


S2_SINGLE_REPO_MULTIFILE = Scenario(
    id="S2",
    title="Jeden serwis, trzy warstwy — pole SKU (migracja + encja + DTO)",
    question="Dodaj produktom kod SKU: kolumnę w bazie, pole w encji i w odpowiedzi API.",
    proposals=[{
        "title": "Pole SKU w katalogu",
        "description": "Migracja V2 dodaje kolumnę sku; encja i ProductResponse ją wystawiają.",
        "commit_hint": "feat(catalog): pole SKU produktu",
    }],
    files=[
        PlannedFile(repo="shop-catalog", path=_CATALOG_MIGRATION, action="create",
                    reason="Addytywna migracja Flyway dodająca kolumnę sku.",
                    build=lambda _original: _SKU_MIGRATION),
        PlannedFile(repo="shop-catalog", path=_CATALOG_PRODUCT, action="modify",
                    reason="Pole sku w encji JPA (schemat z migracji, ddl-auto=none).",
                    build=_s2_product),
        PlannedFile(repo="shop-catalog", path=_CATALOG_RESPONSE, action="modify",
                    reason="Wystawienie sku w odpowiedzi API.", build=_s2_response),
    ],
    expect_content={
        _CATALOG_MIGRATION: ["ALTER TABLE products ADD COLUMN sku"],
        _CATALOG_PRODUCT: ["private String sku;", "public String getSku()"],
        _CATALOG_RESPONSE: ["String sku,", "p.getSku()"],
    },
)


# ── S3 — dwa repozytoria, dwa języki ─────────────────────────────────────────
# S2 + widoczność zmiany w UI. Kluczowy test bramki: zielone musi być OBA repo,
# każde innym narzędziem (Gradle dla Javy, npm/Vite dla Reacta).

_UI_APP = "src/App.jsx"


def _s3_ui(original: str) -> str:
    return _replace(
        original,
        "              <strong>{p.name}</strong>\n",
        "              <strong>{p.name}</strong>\n"
        "              {p.sku ? (\n"
        "                <code style={{ marginLeft: '0.5rem', fontSize: '0.75rem', color: '#6b7280' }}>\n"
        "                  {p.sku}\n"
        "                </code>\n"
        "              ) : null}\n",
        where=_UI_APP,
    )


S3_TWO_REPOS_TWO_LANGUAGES = Scenario(
    id="S3",
    title="Dwa serwisy, dwa języki — SKU od bazy aż po UI",
    question="Pokaż kod SKU produktu także na liście produktów w sklepie.",
    proposals=[{
        "title": "SKU widoczne dla klienta",
        "description": "Backend wystawia sku w ProductResponse, frontend renderuje je przy nazwie.",
        "commit_hint": "feat: SKU produktu widoczne w UI",
    }],
    files=[
        *S2_SINGLE_REPO_MULTIFILE.files,
        PlannedFile(repo="shop-ui", path=_UI_APP, action="modify",
                    reason="Render kodu SKU obok nazwy produktu.", build=_s3_ui),
    ],
    expect_content={
        **S2_SINGLE_REPO_MULTIFILE.expect_content,
        _UI_APP: ["p.sku"],
    },
)


# ── S4 — zmiana przez cały system ────────────────────────────────────────────
# Priorytet zamówienia (flash-sale VIP) przechodzi przez wszystkie warstwy:
# dane (migracja) → encja → API (DTO + kontroler) → logika sagi (OrderService,
# payload zdarzenia) → konsument zdarzeń (shop-notification) → frontend →
# testy akceptacyjne cross-service. Cztery repozytoria, dwa języki, jeden
# słownik pojęć: pole nazywa się `priority` wszędzie albo Java się nie skompiluje.

_ORDER_REQUEST = "src/main/java/com/shop/order/api/CreateOrderRequest.java"
_ORDER_ENTITY = "src/main/java/com/shop/order/domain/Order.java"
_ORDER_CONTROLLER = "src/main/java/com/shop/order/api/OrderController.java"
_ORDER_SERVICE = "src/main/java/com/shop/order/service/OrderService.java"
_ORDER_MIGRATION = "src/main/resources/db/migration/V2__order_priority.sql"
_NOTIFICATION_SERVICE = "src/main/java/com/shop/notification/service/NotificationService.java"

_ORDER_PRIORITY_MIGRATION = """\
-- Priorytet zamówienia (flash-sale). Addytywnie, z wartością domyślną dla
-- rekordów już istniejących — V1 pozostaje nietknięta.
ALTER TABLE orders ADD COLUMN priority VARCHAR(16) NOT NULL DEFAULT 'STANDARD';
"""

_ORDER_REQUEST_NEW = """\
package com.shop.order.api;

/**
 * Żądanie utworzenia zamówienia.
 *
 * <p>{@code priority} jest opcjonalne — starzy klienci nie wysyłają tego pola,
 * więc Jackson ustawi {@code null}, a serwis znormalizuje je do STANDARD.
 */
public record CreateOrderRequest(String productId, long quantity, String priority) {
}
"""


def _s4_entity(original: str) -> str:
    with_field = _replace(
        original,
        '    @Column(name = "payment_deadline")\n    private OffsetDateTime paymentDeadline;\n',
        '    @Column(name = "payment_deadline")\n    private OffsetDateTime paymentDeadline;\n'
        "\n"
        '    @Column(nullable = false)\n    private String priority;\n',
        where=_ORDER_ENTITY,
    )
    with_ctor = _replace(
        with_field,
        "    public Order(String id, String idempotencyKey, String productId, long quantity, "
        "BigDecimal amount, String status) {\n",
        "    public Order(String id, String idempotencyKey, String productId, long quantity, "
        "BigDecimal amount, String status) {\n"
        '        this(id, idempotencyKey, productId, quantity, amount, status, "STANDARD");\n'
        "    }\n"
        "\n"
        "    public Order(String id, String idempotencyKey, String productId, long quantity, "
        "BigDecimal amount, String status, String priority) {\n",
        where=_ORDER_ENTITY,
    )
    return _replace(
        with_ctor,
        "    public String getStatus() {\n        return status;\n    }\n",
        "    public String getStatus() {\n        return status;\n    }\n"
        "\n"
        "    public String getPriority() {\n        return priority;\n    }\n",
        where=_ORDER_ENTITY,
    )


def _s4_controller(original: str) -> str:
    return _replace(
        original,
        "        Order order = service.createOrder(idempotencyKey, req.productId(), req.quantity());",
        "        Order order = service.createOrder(\n"
        "                idempotencyKey, req.productId(), req.quantity(), req.priority());",
        where=_ORDER_CONTROLLER,
    )


def _s4_service(original: str) -> str:
    with_signature = _replace(
        original,
        "    public Order createOrder(String idempotencyKey, String productId, long quantity) {",
        "    /** Priorytet nieznany/pusty normalizujemy do STANDARD — kolumna jest NOT NULL. */\n"
        "    static String normalizePriority(String priority) {\n"
        "        if (priority == null || priority.isBlank()) {\n"
        '            return "STANDARD";\n'
        "        }\n"
        "        String upper = priority.trim().toUpperCase(java.util.Locale.ROOT);\n"
        '        return upper.equals("VIP") ? "VIP" : "STANDARD";\n'
        "    }\n"
        "\n"
        "    @Transactional\n"
        "    public Order createOrder(String idempotencyKey, String productId, long quantity,\n"
        "                             String priority) {",
        where=_ORDER_SERVICE,
    )
    # Stary @Transactional stoi teraz nad `normalizePriority` — usuwamy go stamtąd.
    with_signature = _replace(
        with_signature,
        "    @Transactional\n    /** Priorytet nieznany",
        "    /** Priorytet nieznany",
        where=_ORDER_SERVICE,
    )
    with_entity = _replace(
        with_signature,
        '        Order order = new Order(orderId, idempotencyKey, productId, quantity, amount, "PENDING");',
        "        String normalized = normalizePriority(priority);\n"
        "        Order order = new Order(orderId, idempotencyKey, productId, quantity, amount,\n"
        '                "PENDING", normalized);',
        where=_ORDER_SERVICE,
    )
    return _replace(
        with_entity,
        '        emit(orderTopic, "OrderCreated", orderId,\n'
        '                Map.of("orderId", orderId, "productId", productId, "quantity", quantity));',
        '        emit(orderTopic, "OrderCreated", orderId,\n'
        '                Map.of("orderId", orderId, "productId", productId, "quantity", quantity,\n'
        '                        "priority", normalized));',
        where=_ORDER_SERVICE,
    )


def _s4_notification(original: str) -> str:
    """Konsument musi TOLEROWAĆ brak pola — zdarzenia sprzed zmiany go nie mają."""
    return _replace(
        original,
        '        String orderId = e.path("orderId").asText();\n'
        '        log.info("Sending \'{}\' notification for order {}", message, orderId);\n'
        '        sent.save(new SentNotification(eventId, "log", type, orderId, message));',
        '        String orderId = e.path("orderId").asText();\n'
        "        // Pole dodane w zmianie „priorytet zamówienia”; starsze zdarzenia go nie mają.\n"
        '        String priority = e.path("priority").asText("STANDARD");\n'
        '        String decorated = "VIP".equals(priority) ? message + " (priorytet VIP)" : message;\n'
        '        log.info("Sending \'{}\' notification for order {} (priority {})",\n'
        "                decorated, orderId, priority);\n"
        '        sent.save(new SentNotification(eventId, "log", type, orderId, decorated));',
        where=_NOTIFICATION_SERVICE,
    )


def _s4_ui(original: str) -> str:
    with_state = _replace(
        original,
        "  const [userId, setUserIdState] = useState(getUserId());\n",
        "  const [userId, setUserIdState] = useState(getUserId());\n"
        "  const [vip, setVip] = useState(false);\n",
        where=_UI_APP,
    )
    with_payload = _replace(
        with_state,
        "        body: JSON.stringify({ productId: String(product.id), quantity: 1 }),",
        "        body: JSON.stringify({\n"
        "          productId: String(product.id),\n"
        "          quantity: 1,\n"
        "          priority: vip ? 'VIP' : 'STANDARD',\n"
        "        }),",
        where=_UI_APP,
    )
    return _replace(
        with_payload,
        "      {error && <p style={{ color: 'crimson' }}>{error}</p>}\n",
        "      {error && <p style={{ color: 'crimson' }}>{error}</p>}\n"
        "\n"
        "      <label style={{ display: 'block', margin: '0.5rem 0', fontSize: '0.9rem' }}>\n"
        "        <input type=\"checkbox\" checked={vip} onChange={(e) => setVip(e.target.checked)} />{' '}\n"
        "        Zamówienie priorytetowe (VIP)\n"
        "      </label>\n",
        where=_UI_APP,
    )


# Bramka preprod-gate uruchamia pakiet akceptacyjny, więc zmiana widoczna
# cross-service MUSI przyjść razem ze scenariuszem, który ją potwierdza
# (KROK 1 pkt 7 procedury z `agent._CHANGE_PLAYBOOK`).
_ACCEPTANCE_CLIENT = "src/test/java/com/shop/acceptance/support/ShopClient.java"
_ACCEPTANCE_STEPS = "src/test/java/com/shop/acceptance/steps/PurchaseSteps.java"
_ACCEPTANCE_FEATURE = "src/test/resources/features/purchase.feature"


# Java w tych blokach niesie własne `\"` z literałów JSON-a, więc stringi są
# surowe (r"""…"""); inaczej Python zjadłby ukośniki i podmiana nie trafiłaby.
_ACCEPTANCE_CLIENT_OLD = r'''    /** POST /api/orders (Idempotency-Key) -> 202 { "orderId": "<id>" } */
    public String createOrder(String productId, long quantity) {
        String payload = "{\"productId\":\"" + productId + "\",\"quantity\":" + quantity + "}";
'''

_ACCEPTANCE_CLIENT_NEW = r'''    /** POST /api/orders (Idempotency-Key) -> 202 { "orderId": "<id>" } */
    public String createOrder(String productId, long quantity) {
        return createOrder(productId, quantity, "STANDARD");
    }

    /** Jak wyżej, ale z priorytetem zamówienia (STANDARD / VIP). */
    public String createOrder(String productId, long quantity, String priority) {
        String payload = "{\"productId\":\"" + productId + "\",\"quantity\":" + quantity
                + ",\"priority\":\"" + priority + "\"}";
'''

_ACCEPTANCE_STEP_ANCHOR = '    @Then("the order eventually becomes {string}")'

_ACCEPTANCE_STEP_NEW = '''    @When("a VIP buyer orders {int} unit(s) of the product")
    public void aVipBuyerOrders(int quantity) {
        ctx.orderId = ctx.shop.createOrder(ctx.productId, quantity, "VIP");
        assertThat(ctx.orderId).as("created VIP order id").isNotBlank();
    }

''' + _ACCEPTANCE_STEP_ANCHOR

_FEATURE_ANCHOR = '''    Then the order eventually becomes "CANCELLED"
    And the available stock of the product is 5
'''

_FEATURE_NEW = _FEATURE_ANCHOR + '''
  # Priorytet jest addytywny: zamówienie VIP przechodzi tę samą sagę,
  # więc obserwowalny wynik musi pozostać identyczny.
  Scenario: VIP priority - order still confirmed and stock decremented
    Given a test product priced 49.99 with 5 units in stock
    When a VIP buyer orders 2 units of the product
    Then the order eventually becomes "CONFIRMED"
    And the available stock of the product is 3
'''


def _s4_acceptance_client(original: str) -> str:
    return _replace(original, _ACCEPTANCE_CLIENT_OLD, _ACCEPTANCE_CLIENT_NEW,
                    where=_ACCEPTANCE_CLIENT)


def _s4_acceptance_steps(original: str) -> str:
    return _replace(original, _ACCEPTANCE_STEP_ANCHOR, _ACCEPTANCE_STEP_NEW,
                    where=_ACCEPTANCE_STEPS)


def _s4_acceptance_feature(original: str) -> str:
    return _replace(original, _FEATURE_ANCHOR, _FEATURE_NEW, where=_ACCEPTANCE_FEATURE)


S4_CROSS_SERVICE = Scenario(
    id="S4",
    title="Cztery repozytoria — priorytet zamówienia przez wszystkie warstwy",
    question=(
        "Klienci VIP mają mieć priorytet w flash-sale: pozwól oznaczyć zamówienie "
        "jako priorytetowe, przenieś to przez sagę i zdarzenia aż do powiadomień, "
        "i dodaj przełącznik w sklepie."
    ),
    proposals=[{
        "title": "Priorytet zamówienia (VIP)",
        "description": (
            "Nowa kolumna orders.priority, pole w CreateOrderRequest i encji, "
            "propagacja w payloadzie OrderCreated, obsługa w shop-notification, "
            "przełącznik w shop-ui."
        ),
        "commit_hint": "feat: priorytet zamówienia dla klientów VIP",
    }],
    files=[
        PlannedFile(repo="shop-order", path=_ORDER_MIGRATION, action="create",
                    reason="Kolumna priority z domyślną wartością dla istniejących rekordów.",
                    build=lambda _o: _ORDER_PRIORITY_MIGRATION),
        PlannedFile(repo="shop-order", path=_ORDER_REQUEST, action="modify",
                    reason="Opcjonalne pole priority w żądaniu utworzenia zamówienia.",
                    build=lambda _o: _ORDER_REQUEST_NEW),
        PlannedFile(repo="shop-order", path=_ORDER_ENTITY, action="modify",
                    reason="Pole priority w encji + konstruktor zgodny wstecz.",
                    build=_s4_entity),
        PlannedFile(repo="shop-order", path=_ORDER_CONTROLLER, action="modify",
                    reason="Przekazanie priorytetu z żądania do sagi.", build=_s4_controller),
        PlannedFile(repo="shop-order", path=_ORDER_SERVICE, action="modify",
                    reason="Normalizacja priorytetu, zapis i wypisanie go w OrderCreated.",
                    build=_s4_service),
        PlannedFile(repo="shop-notification", path=_NOTIFICATION_SERVICE, action="modify",
                    reason="Konsument odczytuje priority (tolerując jego brak).",
                    build=_s4_notification),
        PlannedFile(repo="shop-ui", path=_UI_APP, action="modify",
                    reason="Przełącznik VIP i wysyłka pola priority.", build=_s4_ui),
        PlannedFile(repo="shop-acceptance-tests", path=_ACCEPTANCE_CLIENT, action="modify",
                    reason="Klient e2e potrafi złożyć zamówienie priorytetowe.",
                    build=_s4_acceptance_client),
        PlannedFile(repo="shop-acceptance-tests", path=_ACCEPTANCE_STEPS, action="modify",
                    reason="Krok Cucumbera dla kupującego VIP.", build=_s4_acceptance_steps),
        PlannedFile(repo="shop-acceptance-tests", path=_ACCEPTANCE_FEATURE, action="modify",
                    reason="Scenariusz akceptacyjny potwierdzający zmianę cross-service.",
                    build=_s4_acceptance_feature),
    ],
    expect_content={
        _ORDER_MIGRATION: ["ALTER TABLE orders ADD COLUMN priority"],
        _ORDER_REQUEST: ["String priority"],
        _ORDER_ENTITY: ["private String priority;", "getPriority()"],
        _ORDER_CONTROLLER: ["req.priority()"],
        _ORDER_SERVICE: ["normalizePriority", '"priority", normalized'],
        _NOTIFICATION_SERVICE: ['e.path("priority")'],
        _UI_APP: ["priority: vip ? 'VIP' : 'STANDARD'"],
        _ACCEPTANCE_CLIENT: ["long quantity, String priority"],
        _ACCEPTANCE_STEPS: ["aVipBuyerOrders"],
        _ACCEPTANCE_FEATURE: ["a VIP buyer orders 2 units"],
    },
)


# ── S5 — zmiana, która się NIE kompiluje (test bramki i pętli naprawczej) ────
# Bramka ma być prawdziwa: kod odwołujący się do nieistniejącej metody musi
# zapalić czerwone światło, zostać zaklasyfikowany jako błąd KODU (nie
# środowiska) i dać się naprawić na podstawie logu.

def _s5_broken(original: str) -> str:
    return _replace(
        original,
        '    @GetMapping("/{id}")',
        '    @GetMapping("/count")\n'
        "    public long count() {\n"
        "        return repo.totalCount();   // metoda nie istnieje w ProductRepository\n"
        "    }\n"
        "\n"
        '    @GetMapping("/{id}")',
        where=_CATALOG_CONTROLLER,
    )


S5_BROKEN_THEN_REPAIRED = Scenario(
    id="S5",
    title="Kod niekompilowalny — bramka blokuje, pętla naprawcza poprawia",
    question="Dodaj endpoint zwracający liczbę produktów w katalogu.",
    proposals=S1_SINGLE_FILE.proposals,
    files=[PlannedFile(
        repo="shop-catalog", path=_CATALOG_CONTROLLER, action="modify",
        reason="Nowy endpoint licznika produktów (pierwsza, błędna próba).",
        build=_s5_broken,
    )],
    expect_validation_failure=True,
    # Naprawa po logu: `totalCount()` nie istnieje, `count()` z CrudRepository — tak.
    repair={_CATALOG_CONTROLLER: lambda current: current.replace(
        "repo.totalCount();   // metoda nie istnieje w ProductRepository", "repo.count();"
    )},
)


ALL_SCENARIOS = [
    S1_SINGLE_FILE,
    S2_SINGLE_REPO_MULTIFILE,
    S3_TWO_REPOS_TWO_LANGUAGES,
    S4_CROSS_SERVICE,
    S5_BROKEN_THEN_REPAIRED,
]
