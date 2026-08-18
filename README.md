# Fridge backend

Backend виртуального холодильника и милпрепов. Это отдельный сервис, который
будет использоваться приложением «Холодильник», Hermes и GlucoTracker.

UI/UX specification for Claude Design: [docs/claude-design-web-ui-spec.md](docs/claude-design-web-ui-spec.md).

Сейчас реализована первая вертикаль:

- обязательная owner-scoping через `X-User-Id`;
- общая/личная база продуктов и кассовых алиасов;
- идемпотентный импорт структурированного фискального чека;
- прямой импорт MIME-писем с чеками `ofd-magnit.ru`;
- объединение одинаковых маркированных товаров по GTIN;
- извлечение массы/объёма упаковки из товарного наименования;
- сохранение услуг и пакетов в чеке без добавления их в остатки;
- автоматическое создание складских партий и журнала операций;
- очередь фонового обогащения неизвестных продуктов;
- durable worker, находящий точные БЖУ и фото сначала по GTIN через Open Food Facts,
  затем через grounded web research Hermes;
- создание милпрепа с транзакционным списанием ингредиентов;
- фасовка в контейнеры разного веса;
- пропорциональное распределение БЖУ и калорий;
- короткий код контейнера для будущего DataMatrix;
- регистрация полного или частичного употребления контейнера.

## Запуск

```bash
uv sync --extra dev
uv run uvicorn fridge_api.main:app --reload
```

Systemd-сервис production API слушает `127.0.0.1:8011`. Интерактивный handoff
доступен через `http://127.0.0.1:8011/mockup/`, OpenAPI — через
`http://127.0.0.1:8011/docs`.

По умолчанию используется `sqlite:///./data/fridge.db`. Для PostgreSQL:

```bash
export FRIDGE_DATABASE_URL='postgresql+psycopg://user:password@localhost/fridge'
```

Локальная разработка автоматически создаёт таблицы. Production должен запускать
миграции Alembic и устанавливать `FRIDGE_AUTO_CREATE_SCHEMA=false`.

## Импорт чека Магнита из Gmail

Endpoint принимает исходное MIME-письмо без преобразования:

```bash
curl -X POST http://127.0.0.1:8000/receipts/import-email \
  -H 'Content-Type: message/rfc822' \
  -H 'X-User-Id: <UUID>' \
  --data-binary @receipt.eml
```

Для Hermes с настроенной Himalaya письмо можно взять непосредственно из Gmail.
Команда читает сообщение без изменения флага `Seen`:

```bash
# Только проверить распознавание
fridge-import-gmail 46440 --dry-run

# Импортировать в API
export FRIDGE_OWNER_ID='<UUID пользователя>'
export FRIDGE_API_URL='http://127.0.0.1:8000'
fridge-import-gmail 46440

# Или напрямую в настроенную БД, без запущенного HTTP-сервиса
fridge-import-gmail 46440 --direct --owner-id '<UUID пользователя>'
```

Парсер проверяет отправителя `ofd-magnit.ru`, ограничивает письмо размером 5 МБ
и не сохраняет полный MIME, адрес покупателя или рекламные вложения. В
`raw_payload` остаются только технические сведения о разборе.

## Авторизация

До общей JWT-интеграции с GlucoTracker сервис требует доверенный заголовок:

```text
X-User-Id: <UUID пользователя GlucoTracker>
```

Анонимного/default пользователя нет. Все личные запросы фильтруются по owner ID.

## Проверка

```bash
uv run ruff check .
uv run pytest -q
```

## Worker БЖУ и фотографий

```bash
# Обработать доступную очередь и выйти
fridge-enrichment-worker --once

# Постоянно следить за новыми строками чеков
fridge-enrichment-worker --poll-interval 60
```

Точное совпадение Open Food Facts по GTIN получает статус `verified`. Результат
по названию из Hermes сохраняется как `estimated`, только если есть прямой URL
источника, полный набор ккал/БЖУ на 100 г/мл и confidence не ниже 0.75.
Неуверенные результаты не записываются в карточку товара.

## Backend-контракты интерфейса

- `GET /inventory` возвращает складские партии вместе с карточкой товара,
  изображением, КБЖУ, источником и статусом качества данных.
- `POST /meal-prep/batches` идемпотентно создаёт черновик и резервирует выбранные
  количества продуктов.
- `PATCH /meal-prep/batches/{id}` сохраняет имя, его источник, фотографию и
  фактический выход готового блюда.
- `POST /meal-prep/batches/{id}/suggest-name` поддерживает быстрый локальный и
  Hermes-вариант названия без дополнительных вопросов.
- `PUT /meal-prep/batches/{id}/portions` атомарно создаёт равные, фиксированные
  либо произвольные порции и сразу рассчитывает КБЖУ контейнеров.
- `POST /meal-prep/batches/{id}/finalize` подтверждает списание, а
  `POST /meal-prep/batches/{id}/cancel` возвращает зарезервированные продукты.
- `POST /media/images` принимает JPEG, PNG или WebP до 10 МБ для блюда или
  отдельного контейнера.
- `GET /containers/{id}/label` возвращает данные этикетки и короткий DataMatrix ID.

Все изменяющие запросы owner-scoped. Повторное создание партии с тем же
`idempotency_key` не списывает продукты повторно.

## Следующие интеграции

1. Автоматический Gmail watcher Hermes, передающий новые чеки в import API.
2. Провайдер получения фискального чека по QR (ФНС/ОФД) для других магазинов.
3. Android-клиент и Bluetooth-печать Xprinter XP-365B.
4. JWT service-to-service интеграция с GlucoTracker.
