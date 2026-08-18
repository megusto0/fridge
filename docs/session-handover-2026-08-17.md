# Session handover — Fridge backend and meal-prep mockup

Date: 2026-08-17  
Timezone: Europe/Samara  
Repository: `/media/megusto/storage/fridge`  
Real owner ID: `f51669a5-b262-475b-979c-4da82b072266`

## User intent and working preferences

The user is building a separate «Холодильник» application connected to Hermes
and GlucoTracker. Purchases arrive from fiscal receipts, become inventory, are
used to create meal-prep batches, are divided into weighed containers and later
registered in GlucoTracker through a DataMatrix label.

The current explicit request was to build the **backend for the supplied Claude
Design handoff**, not to redesign or recreate the handoff itself.

Important user preference: do not ask additional questions. Make reasonable,
reversible assumptions and continue. The system must not recommend insulin doses.

## Repository state

The Fridge repository was initialized during this session but has no commits.
Everything currently appears as untracked in `git status`. Do not reset or remove
files; they are the implementation produced during the session.

Main directories:

```text
src/fridge_api/       FastAPI application
migrations/           Alembic migrations
tests/                API and service tests
deploy/               systemd units
design_mockup/         active Claude Design handoff
docs/                 product/UI specifications and this handover
data/fridge.db         real SQLite database
```

There are also two duplicate handoff artifacts at repository root:

```text
fridge_mockup_bundle/
Холодильник_плотная_компоновка_handoff.zip
```

The authoritative source supplied by the user is:

```text
/home/megusto/Downloads/Холодильник_плотная_компоновка_handoff.zip
```

`design_mockup/index.html` and `design_mockup/support.js` are byte-identical to
the corresponding files in that archive.

## Running services

Both services are enabled and active:

```text
fridge-api.service
fridge-enrichment-worker.service
```

Fridge API:

```text
http://127.0.0.1:8011
http://127.0.0.1:8011/health
http://127.0.0.1:8011/docs
http://127.0.0.1:8011/mockup/
```

The production service unit is installed at:

```text
/etc/systemd/system/fridge-api.service
```

Source-controlled copies of units:

```text
deploy/fridge-api.service
deploy/fridge-enrichment-worker.service
```

Useful checks:

```bash
systemctl status fridge-api.service fridge-enrichment-worker.service
journalctl -u fridge-api.service --no-pager -n 100
curl -fsS http://127.0.0.1:8011/health
```

## Database and migrations

The real database is migrated to Alembic head:

```text
d72a5eb480fa (head)
```

Migration chain:

```text
5c3d32b0126d  initial schema
9b206caa3fb0  receipt inventory classification and package fields
c41f32b8e7a1  durable enrichment worker state
d72a5eb480fa  backend contracts required by the meal-prep mockup
```

Safety backups created before material migrations:

```text
data/fridge.db.pre-enrichment-worker-20260817
data/fridge.db.pre-mockup-backend-20260817
```

Current real data summary at handover time:

```text
21 inventory lots with remaining quantity
8 enriched products with complete nutrition and images
8 enrichment jobs completed
13 enrichment jobs failed because no sufficiently confident match was found
0 real meal-prep batches
```

No test batch was created in the real owner's database.

## Existing receipt and enrichment work

Implemented before the mockup backend:

- Gmail access through Himalaya and a Hermes receipt-import skill;
- Magnit MIME receipt parser;
- idempotent receipt import;
- extraction of GTIN and package size;
- classification of products versus delivery/bag/service lines;
- inventory lot creation;
- durable nutrition/image enrichment worker;
- exact GTIN lookup through Open Food Facts;
- cautious Hermes grounded-research fallback;
- product aliases so future identical receipt lines resolve automatically.

The worker links enriched products to receipt lines and inventory lots. It only
saves complete kcal/protein/fat/carbohydrate data with a direct source URL.

Important enrichment files:

```text
src/fridge_api/services/enrichment/worker.py
src/fridge_api/services/enrichment/open_food_facts.py
src/fridge_api/services/enrichment/hermes.py
src/fridge_api/cli/enrichment_worker.py
```

## Backend implemented for the supplied mockup

### Enriched fridge storefront

`GET /inventory` remains backward compatible but now embeds the matched product:

- canonical name and brand;
- GTIN;
- package size;
- kcal and P/F/C per 100 g/ml;
- verified/estimated/pending status and confidence;
- image and nutrition source URL;
- computed `days_to_expiry` when an expiry date is available.

Relevant files:

```text
src/fridge_api/services/inventory.py
src/fridge_api/schemas.py
src/fridge_api/routers/inventory.py
```

### Reversible meal-prep creation

`POST /meal-prep/batches` is owner-scoped and idempotent. It calculates total
nutrition from selected inventory lots and reserves the requested quantities.

Current reservation semantics preserve compatibility with the original backend:

- creation subtracts the reserved amount from `remaining_quantity`;
- an `InventoryTransaction(kind=RESERVE, delta=-quantity)` is written;
- finalization records `CONSUME` with a zero delta because the available amount
  was already reduced during reservation;
- cancellation restores `remaining_quantity` and records `RELEASE` with a
  positive delta;
- repeating the same `idempotency_key` does not reserve twice.

### Batch editing and name generation

```text
PATCH /meal-prep/batches/{batch_id}
POST  /meal-prep/batches/{batch_id}/suggest-name
```

Patchable fields:

- name;
- name source (`manual`, `fast`, `hermes`);
- batch image URL;
- actual cooked yield in grams.

Name suggestions support:

- `mode=fast`: deterministic local Russian name;
- `mode=hermes`: Hermes one-shot naming with a 90-second timeout;
- automatic fast fallback if Hermes is unavailable.

Relevant file:

```text
src/fridge_api/services/naming.py
```

### Portioning

```text
PUT /meal-prep/batches/{batch_id}/portions
```

Supported modes:

- `equal`: split exact cooked yield across N containers;
- `fixed`: create fixed-weight containers and, by default, one remainder
  container;
- `custom`: arbitrary explicit net weights and optional per-container image URLs.

The endpoint atomically replaces the current portion plan, resolves tare from an
explicit value or saved container type, validates total weight and calculates
container kcal/P/F/C proportionally.

Custom weights that do not equal cooked yield return HTTP 409 with:

```json
{
  "message": "Portion weights must equal cooked yield",
  "cooked_yield_g": "500",
  "portioned_weight_g": "450",
  "difference_g": "50"
}
```

Existing one-by-one container creation is still supported:

```text
POST /meal-prep/batches/{batch_id}/containers
```

### Finalization and cancellation

```text
POST /meal-prep/batches/{batch_id}/finalize
POST /meal-prep/batches/{batch_id}/cancel
```

Finalization requires at least one container and matching cooked/portioned weight.
Cancellation is idempotent while the batch is still portioning and releases all
reserved ingredients. A ready batch cannot be cancelled through this endpoint.

### Container types, labels and consumption

```text
GET  /container-types
POST /container-types
GET  /containers/{container_id}
GET  /containers/by-code/{public_code}
GET  /containers/{container_id}/label
POST /containers/{container_id}/consume
```

The label endpoint returns dish name, prepared time, net weight, kcal/P/F/C and
the short `GT:C:...` value to encode as DataMatrix.

It does **not** currently send a job to the physical XP-365B printer. It provides
all backend data needed for client-side Bluetooth or a future print worker.

### Image uploads

```text
POST /media/images
```

- accepts JPEG, PNG and WebP;
- 10 MB maximum;
- checks magic bytes rather than trusting the filename/content-type;
- stores content-addressed files under `data/uploads/{owner_id}`;
- returns a URL under `/uploaded-media/...`;
- duplicate image bytes are not written twice.

`python-multipart` was added to project dependencies.

### Mockup hosting and CORS

The API serves the supplied handoff at `/mockup/` and redirects `GET /` there.
CORS allows `Origin: null` for `file://` use and localhost/127.0.0.1 port 8011.

The mockup itself still uses its internal demo data. It has **not yet been wired
to fetch `/inventory` or submit meal-prep API calls**. The user asked for the
backend in the last turn, so backend contracts were implemented first.

## Main files changed for the mockup backend

```text
src/fridge_api/config.py
src/fridge_api/main.py
src/fridge_api/models.py
src/fridge_api/schemas.py
src/fridge_api/routers/inventory.py
src/fridge_api/routers/meal_prep.py
src/fridge_api/routers/media.py
src/fridge_api/services/inventory.py
src/fridge_api/services/meal_prep.py
src/fridge_api/services/naming.py
migrations/versions/d72a5eb480fa_mockup_backend_contracts.py
tests/test_meal_prep.py
pyproject.toml
uv.lock
README.md
deploy/fridge-api.service
```

## Verification completed

Commands run successfully:

```bash
UV_CACHE_DIR=/media/megusto/storage/fridge/.uv-cache uv run ruff check .
UV_CACHE_DIR=/media/megusto/storage/fridge/.uv-cache uv run pytest -q
UV_CACHE_DIR=/media/megusto/storage/fridge/.uv-cache uv run alembic check
```

Result:

```text
Ruff: clean
Tests: 11 passed
Alembic: no new upgrade operations detected
```

The new tests cover:

- inventory response with embedded product image and nutrition;
- owner isolation;
- fast name suggestion;
- batch patching;
- equal portioning and nutrition conservation;
- fixed portioning with remainder;
- rejection of mismatching custom weights;
- cancellation restoring inventory;
- DataMatrix label payload;
- image upload and invalid-file rejection;
- original idempotency and partial-container consumption flow.

Real service checks completed:

```text
GET /health                 200
GET /mockup/                200, 91165 bytes
GET /inventory              200, 21 lots
GET /openapi.json           200
GET / → /mockup/            200 after redirect
```

The original handoff was also opened with headless Chrome from `file://`, rendered
successfully at 1440 × 1100 and passed an interaction smoke test:

```text
select product → apply amount → selected tray → open meal-prep composer
```

## Interrupted verification

The last action before this handover request was about to perform the final
browser/CDP verification against the served URL:

```text
http://127.0.0.1:8011/mockup/
```

The `agent-browser` CLI required by the installed skill is not present in `PATH`,
so the established fallback is headless Google Chrome plus the Chrome DevTools
Protocol. The final served-page screenshot/console-error check was not executed
because the turn was interrupted by this handover request.

## Known limitations and follow-up work

Recommended next steps, in order:

1. Complete the served-page Chrome/CDP verification: meaningful content, no
   runtime exceptions, no error overlay, navigation to composer works.
2. Wire the handoff UI to the backend:
   - load `/inventory` using the owner header;
   - replace its hardcoded `cat` array;
   - call batch create/patch/suggest-name/portions/finalize/cancel;
   - upload batch/container photos through `/media/images`;
   - render label payload from `/containers/{id}/label`.
3. Add actual printer dispatch only when the XP-365B transport is chosen and
   available. The current endpoint supplies label data but does not print.
4. Add OCR/Bluetooth scale ingestion if automatic reading of scale displays is
   required. Current backend accepts weights but does not OCR them.
5. The supplied dense handoff has horizontal overflow at a 390 px screenshot.
   Treat that as a frontend issue; do not change the user's supplied design
   without preserving the desktop layout.
6. Commit and push only when explicitly requested. At handover time no Fridge
   repository commit exists.

## Safe restart and recovery

Normal restart:

```bash
sudo systemctl restart fridge-api.service fridge-enrichment-worker.service
systemctl --no-pager --full status fridge-api.service fridge-enrichment-worker.service
```

Reinstall units after editing:

```bash
sudo install -o root -g root -m 0644 deploy/fridge-api.service /etc/systemd/system/fridge-api.service
sudo install -o root -g root -m 0644 deploy/fridge-enrichment-worker.service /etc/systemd/system/fridge-enrichment-worker.service
sudo systemctl daemon-reload
sudo systemctl restart fridge-api.service fridge-enrichment-worker.service
```

Run migrations and checks:

```bash
UV_CACHE_DIR=/media/megusto/storage/fridge/.uv-cache uv sync --extra dev
UV_CACHE_DIR=/media/megusto/storage/fridge/.uv-cache uv run alembic upgrade head
UV_CACHE_DIR=/media/megusto/storage/fridge/.uv-cache uv run ruff check .
UV_CACHE_DIR=/media/megusto/storage/fridge/.uv-cache uv run pytest -q
```

Do not restore a backup unless a verified migration failure requires it. The
current real database is healthy and both services are active.
