# Fridge Web UI — specification for Claude Design

Status: design-ready product specification  
Language of the interface: Russian  
Primary platform: mobile web/PWA  
Secondary platform: desktop web  
Last updated: 2026-08-17

## 1. Product objective

Design a visual web application called **«Холодильник»**. It turns products
imported from receipts into a browsable virtual fridge and lets the user create
meal-prep batches without manually calculating nutrition.

The primary journey is:

```text
Fridge storefront
  → select several products and quantities
  → review total ingredients and nutrition
  → name the dish manually or with one magic-wand action
  → enter the actual cooked yield
  → split the batch into containers
  → attach a photo
  → automatically calculate nutrition per container
  → save containers and optionally print labels
```

This is not a generic calorie tracker or grocery shop. It should feel like
looking into one's own fridge: visual, tangible, fast and calm.

## 2. Non-negotiable UX principles

- Never require follow-up questions in the happy path.
- Prefer visual selection, presets and sensible defaults over forms.
- Keep automatic decisions reversible through `Отменить` and `Изменить`.
- A photo is used to identify and illustrate food, never as the source of exact
  nutrition. Nutrition comes from the selected ingredients.
- Clearly distinguish `Проверено`, `Оценка` and `Нужно уточнить` nutrition.
- Do not recommend insulin doses.
- Do not hide incomplete or uncertain product data.
- Never silently consume inventory. Selection reserves it; final confirmation
  performs the actual write-off.
- Preserve the user's context when navigating back from any step.
- Creating one normal four-container batch should take under two minutes.

## 3. Information architecture

Primary navigation has three destinations:

1. **Холодильник** — raw products and packages currently available.
2. **Милпрепы** — prepared batches and individual containers.
3. **Добавить** — receipt/QR import and manual fallback.

Desktop uses a compact left sidebar. Mobile uses a bottom navigation bar with a
prominent central `＋` action.

Routes to design:

```text
/fridge
/products/:productId
/meal-preps
/meal-preps/new
/meal-preps/:batchId
/containers/:containerId
```

## 4. Visual direction

Use a warm, modern kitchen aesthetic rather than a clinical health dashboard.

- Light warm-grey background, near-white cards and subtle borders.
- Deep green is the primary action colour.
- Amber indicates expiring products or estimated nutrition.
- Muted red is reserved for expired/depleted/error states.
- Product photography is prominent and uses consistent rounded 4:3 frames.
- Typography is highly legible, with tabular numerals for weights and nutrition.
- Cards should feel physical but not use heavy shadows or glassmorphism.
- Use generous spacing and large touch targets of at least 44 px.
- Support desktop widths up to 1440 px and mobile widths down to 360 px.
- Design a dark theme only as a secondary token set; the main mockup is light.

Avoid supermarket-style pricing, promotional badges, excessive gradients and
medical-looking glucose charts.

## 5. Screen: «Холодильник»

### 5.1 Header and controls

The top area contains:

- title `Холодильник`;
- number of available products;
- search field `Найти в холодильнике`;
- filter chips: `Все`, `Скоро испортится`, `Белковые`, `Овощи`, `Молочные`,
  `Без БЖУ`;
- sort control: `Сначала использовать`, `Недавно куплено`, `По названию`;
- primary button `Создать милпреп`, disabled until something is selected.

On mobile, the search and chips remain visible while scrolling. The title may
collapse into a compact sticky bar.

### 5.2 Product grid

Desktop: responsive grid of 4–6 cards.  
Tablet: 3 cards.  
Mobile: 2 compact cards, with an optional list-view toggle.

Each product card contains:

- product image with a tasteful placeholder if no photo exists;
- product/brand name, maximum two lines;
- remaining amount such as `2 × 200 г`, `430 г` or `6 шт.`;
- expiry status such as `использовать за 2 дня`;
- compact nutrition line, for example `105 ккал · Б 12 · Ж 5 · У 3`;
- data-quality badge: `Проверено`, `Оценка`, `Нужно уточнить`;
- selection control.

Selected cards receive a green outline and show the selected amount directly on
the card: `✓ 200 г` or `✓ 1 уп.`. Selection must not rely on colour alone.

### 5.3 Amount selection sheet

Clicking a card or its plus button opens a bottom sheet on mobile and a popover
or side sheet on desktop.

For a packaged product, offer:

```text
Сколько использовать?

[ 1 упаковку · 200 г ]
[ Все доступные · 400 г ]
[ Другое количество ]  [ 150 ] [г]
```

For weighed goods, default to grams. For countable goods, default to pieces.
When the user selects grams from a partly used package, show `останется 50 г`.

If several inventory lots exist, use the earliest-expiring lot automatically and
show a small note `Сначала упаковка до 21 августа`. Lot selection is available
under `Изменить`, but is not a mandatory question.

Prevent amounts above available stock. Show the correction inline rather than
through an alert dialog.

### 5.4 Sticky selection tray

Once at least one product is selected, show a sticky tray:

```text
Выбрано 4 продукта
1370 г · 1840 ккал · Б 148 · Ж 52 · У 176

[Очистить]                         [Готовить →]
```

On desktop this can be a persistent right sidebar with ingredient thumbnails.
On mobile it is a compact bottom panel above navigation, expandable by swipe.

## 6. Product detail

The product detail page/sheet shows:

- large image;
- canonical and receipt names;
- remaining packages/lots and purchase dates;
- expiry estimate;
- full nutrition per 100 g/ml;
- source link;
- confidence and status explanation;
- actions `Использовать`, `Исправить данные`, `Списать`.

Do not overload the main grid with source and confidence details; keep them here.

## 7. Screen: meal-prep composer

Route: `/meal-preps/new`.

Desktop is a single workspace with ingredients on the left and a sticky summary
on the right. Mobile presents the same state as a four-step flow, while keeping
the stepper compact:

```text
1 Состав  →  2 Блюдо  →  3 Порции  →  4 Готово
```

Moving backward must retain every entry, photo and selected amount.

### 7.1 Step 1 — «Состав»

Show editable ingredient rows:

```text
[photo] Индейка                         500 г   [Изменить]
[photo] Чечевица                        300 г   [Изменить]
[photo] Карибская смесь                 400 г   [Изменить]
[photo] Сливки                          170 мл  [Изменить]

[＋ Добавить из холодильника]
```

The summary card recalculates immediately:

```text
Ингредиенты: 1370 г
1840 ккал
Белки 148 г · Жиры 52 г · Углеводы 176 г
```

If one ingredient lacks nutrition, show the known subtotal and a warning:
`Итог неполный: у одного продукта нет БЖУ`. Allow the user to continue, but do
not present the result as exact.

### 7.2 Step 2 — «Блюдо»

Provide a normal text field labelled `Название блюда` and a prominent magic-wand
button beside it.

Magic-wand behaviour is one click, with no questions:

1. Immediately generate a deterministic local name from the primary ingredients,
   for example `Индейка с чечевицей и овощами`.
2. In the background ask Hermes for a more natural short name.
3. If Hermes returns successfully, show it as a non-blocking alternative chip,
   for example `Сливочная индейка с красной чечевицей`.
4. Never replace text that the user subsequently edited.

Use subtle microcopy: `Название не влияет на расчёт БЖУ`.

Photo controls:

- `Сфотографировать блюдо`;
- `Выбрать фото`;
- optional `Пропустить`.

One batch photo is enough for all its containers. Individual container photos
can be added later but must not be required.

### 7.3 Actual cooked yield

Ask for the **actual finished-food weight**, because evaporation changes weight
but not total nutrition:

```text
Вес продуктов до приготовления       1370 г
Фактический выход блюда              [ 1124 ] г

[Считать число с фото весов]
```

If no value is entered, default to the sum of future container net weights and
label the calculation as provisional. Explain in one sentence:
`Калории сохраняются, но итоговый вес меняет значения на 100 г.`

### 7.4 Step 3 — «Порции»

Offer three large segmented choices:

1. `Поровну` — choose a number of containers.
2. `Фиксированный вес` — enter grams per container.
3. `Разные веса` — edit each container independently.

#### Equal containers

Input: `Количество контейнеров`, default 4. The system divides the actual yield
equally and previews all rows.

#### Fixed weight

Input: `По 300 г`. Automatically create as many full containers as possible and
show the remainder as a final container:

```text
3 × 300 г
остаток 224 г → [Создать ещё один контейнер]
```

The remainder container is enabled by default.

#### Different weights

Display editable rows:

```text
Контейнер 1   [ 320 г ]  524 ккал   [📷]
Контейнер 2   [ 275 г ]  450 ккал   [📷]
Контейнер 3   [ 301 г ]  492 ккал   [📷]
Контейнер 4   [ 228 г ]  374 ккал   [📷]
```

Each row contains:

- gross or net weight;
- selected container type and tare;
- calculated net food weight;
- automatically calculated kcal/P/F/C;
- optional photo;
- remove action in an overflow menu.

Provide `＋ Добавить контейнер` and `Считать с фото весов`. When a known container
type is selected:

```text
Вес еды = показание весов − масса тары
```

Always show a distribution progress indicator:

```text
Распределено 1124 из 1124 г  ✓
```

Use an amber warning when weights do not equal the actual yield. Offer one-click
`Распределить разницу`, which adjusts the final container. Never change all rows
without showing what changed.

### 7.5 Container nutrition

Nutrition for every container is calculated proportionally by net cooked-food
weight:

```text
container nutrient =
batch nutrient × container net weight / total net weight of all containers
```

Show kcal as the primary number and P/F/C below it. Display raw precision only
internally; round the UI to whole kcal and one decimal gram.

### 7.6 Step 4 — review and save

The final review should feel like a finished set of physical meals:

```text
[large meal photo]
Сливочная индейка с чечевицей
4 контейнера · 1124 г · 1840 ккал

[container cards with weight and nutrition]

[Сохранить в холодильник]
[Сохранить и напечатать 4 этикетки]
```

Confirmation performs the inventory write-off and creates prepared containers.
If saving fails, keep the local draft and allow retry without duplicate batches.

## 8. Screen: «Милпрепы»

Use a photographic card grid distinct from raw products. Each batch card shows:

- batch image;
- meal name;
- preparation date;
- `3 из 4 контейнеров осталось`;
- total remaining weight;
- kcal and P/F/C per typical container;
- status: `Готово`, `Частично съедено`, `Закончился`.

Top filters: `Все`, `Готовые`, `Скоро использовать`, `Закончились`.

Selecting a batch opens a detail view containing ingredients, total nutrition,
container cards and actions `Добавить контейнер`, `Печать этикеток`, `Изменить`.

## 9. Individual container card/detail

Each container is a first-class fridge item. Show:

- inherited batch photo or its own photo;
- dish name and container number;
- net weight and remaining weight;
- kcal and P/F/C;
- prepared/expiry dates;
- short DataMatrix identifier;
- actions `Добавить в GlucoTracker`, `Напечатать этикетку`, `Списать`.

For a partially consumed container, render a visible remaining fraction and do
not imply that nutrition still refers to the original full portion.

## 10. Label preview

Design a monochrome 58 × 40 mm thermal-label preview containing:

- dish name, maximum two lines;
- preparation date;
- net weight;
- kcal and P/F/C;
- DataMatrix;
- short human-readable container code.

The preview must remain legible at 203 dpi. Avoid photographs, grey backgrounds
and fine lines on the printed label.

## 11. Required states

Claude Design must create component states for:

- loading skeletons for product and meal-prep cards;
- empty fridge after initial installation;
- no search results;
- product image missing;
- product nutrition pending;
- estimated nutrition;
- expired and depleted inventory;
- selected, reserved and partly used package;
- offline draft;
- failed save with retry;
- Hermes naming in progress and unavailable;
- photo upload/progress/error;
- container weights under, equal to and over the batch yield;
- successful save and label-print failure.

Background enrichment must never block the entire screen. A product with pending
data remains visible and selectable.

## 12. Accessibility and interaction requirements

- Meet WCAG AA contrast.
- All actions are keyboard accessible on desktop.
- Provide visible focus states.
- Every icon-only action has an accessible label and tooltip on desktop.
- Do not encode verified/estimated/error status using colour alone.
- Inputs use numeric keyboards on mobile and include visible units.
- Confirmation dialogs are reserved for destructive actions only.
- Respect reduced-motion preferences.
- Keep primary actions reachable by the thumb on mobile.

## 13. Russian UI copy

Use short, direct phrases. Preferred terms:

| Concept | UI text |
|---|---|
| Inventory | Холодильник |
| Meal prep batch | Милпреп |
| Prepared serving | Контейнер |
| Use ingredient | Использовать |
| Whole package | Вся упаковка |
| Actual cooked yield | Выход готового блюда |
| Nutrition | КБЖУ |
| Protein/fat/carbs | Белки / Жиры / Углеводы |
| Verified | Проверено |
| Estimated | Оценка |
| Pending enrichment | Данные уточняются |
| Generate name | Придумать название |

Avoid English words in visible UI except recognisable brand names and `DataMatrix`.

## 14. Representative mock data

Use realistic content rather than `Product 1` placeholders:

```text
Творог «Село Зелёное» 5%, 200 г
105 ккал · Б 12 · Ж 5 · У 3 · Проверено

Йогурт Epica с ананасом 4,8%, 130 г
120 ккал · Б 5,7 · Ж 4,8 · У 13,6 · Проверено

Сливки «Село Зелёное» 10%, 200 мл
118 ккал · Б 2,6 · Ж 10 · У 4,5 · Проверено

Азу из индейки, 500 г
Данные уточняются

Лук красный, 460 г
Оценка
```

Example composed meal:

```text
Сливочная индейка с красной чечевицей
4 ingredients · cooked yield 1124 g
1840 kcal · protein 148 g · fat 52 g · carbs 176 g
4 containers: 320 g, 275 g, 301 g, 228 g
```

## 15. Current backend contracts

The current backend base concepts and endpoints are:

```text
GET  /inventory
GET  /products
POST /meal-prep/batches
GET  /meal-prep/batches
GET  /meal-prep/batches/:batchId
POST /meal-prep/batches/:batchId/containers
POST /meal-prep/batches/:batchId/finalize
GET  /containers/by-code/:publicCode
POST /containers/:containerId/consume
```

All private requests currently require `X-User-Id`.

The design should anticipate these backend additions without blocking the UI
prototype:

- embedded product/image/nutrition data in inventory responses;
- reversible ingredient reservation/draft endpoints;
- cooked-yield update;
- equal/fixed/custom bulk container creation;
- image upload and OCR weight extraction;
- local/Hermes dish-name suggestion;
- label preview and print jobs;
- expiry estimates and inventory adjustment.

Use mock adapters for missing endpoints in the design prototype. Do not simplify
away the target workflow merely because an endpoint is not implemented yet.

## 16. Deliverables expected from Claude Design

Produce:

1. A responsive high-fidelity fridge storefront.
2. Product amount-selection sheet/popover.
3. Sticky multi-selection tray.
4. Complete meal-prep composer in desktop and mobile layouts.
5. All three container-distribution modes.
6. Batch and individual-container gallery/detail views.
7. Thermal-label preview.
8. Key loading, empty, pending, warning and error states.
9. Reusable component and design-token definitions.
10. A clickable happy-path prototype from product selection through saved
    containers.

Do not add onboarding questionnaires, chat-first navigation or mandatory recipe
generation. The core product is the visual fridge and fast meal-prep workflow.

## 17. Acceptance criteria

- The user can select multiple fridge items without leaving the grid.
- The user can choose whole packages, pieces or an exact gram/ml amount.
- The UI always shows selected quantities and remaining inventory.
- Total batch КБЖУ updates immediately when ingredients change.
- The user can enter a name or generate one with one click.
- The user can record actual cooked yield.
- The batch can be divided equally, by fixed weight or by arbitrary weights.
- Every container visibly receives automatically calculated КБЖУ.
- One batch photo can be reused by every container.
- The final action creates meal-prep containers and writes off ingredients only
  once.
- Uncertain nutrition is visible and is never represented as verified.
- The complete happy path works at 360 px mobile width without horizontal scroll.
