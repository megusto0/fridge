from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, joinedload, sessionmaker

from fridge_api.config import Settings
from fridge_api.models import (
    EnrichmentJob,
    EnrichmentJobStatus,
    EnrichmentStatus,
    InventoryLot,
    Product,
    ProductAlias,
    ReceiptLine,
)
from fridge_api.services.enrichment.hermes import HermesResearchProvider
from fridge_api.services.enrichment.open_food_facts import (
    OpenFoodFactsProvider,
    normalize_gtin,
)
from fridge_api.services.enrichment.reference_food import ReferenceFoodProvider
from fridge_api.services.enrichment.types import (
    EnrichmentQuery,
    EnrichmentResult,
    TemporaryEnrichmentError,
    is_placeholder_nutrition,
)
from fridge_api.services.enrichment.yandex_eda import YandexCard, YandexEdaProvider

#: Everything the enrichment does to a shopping list, in one place. Until now
#: the worker was silent: a receipt went in, products came out enriched or not,
#: and the only way to tell which provider answered — or why nothing did — was
#: to read the rows afterwards and guess.
logger = logging.getLogger("fridge.enrichment")


def _now() -> datetime:
    return datetime.now(UTC)


def _unit(value: str | None) -> str | None:
    if not value:
        return None
    return {
        "г": "g",
        "гр": "g",
        "мл": "ml",
        "л": "l",
        "кг": "kg",
        "шт": "pcs",
    }.get(value.casefold().strip(), value.casefold().strip())


class EnrichmentWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        open_food_facts: OpenFoodFactsProvider | None = None,
        reference_food: ReferenceFoodProvider | None = None,
        yandex_eda: YandexEdaProvider | None = None,
        hermes: HermesResearchProvider | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.open_food_facts = open_food_facts or OpenFoodFactsProvider(
            base_url=settings.open_food_facts_base_url,
            user_agent=settings.open_food_facts_user_agent,
            timeout_seconds=settings.enrichment_http_timeout_seconds,
        )
        self.reference_food = reference_food
        if self.reference_food is None and settings.enrichment_reference_food_fallback:
            self.reference_food = ReferenceFoodProvider()
        self.yandex_eda = yandex_eda
        if self.yandex_eda is None and settings.enrichment_yandex_eda_fallback:
            self.yandex_eda = YandexEdaProvider()
        self.hermes = hermes
        if self.hermes is None and settings.enrichment_hermes_fallback:
            self.hermes = HermesResearchProvider(
                executable=settings.resolve_hermes_bin(),
                timeout_seconds=settings.enrichment_hermes_timeout_seconds,
            )

    def close(self) -> None:
        self.open_food_facts.close()
        if self.yandex_eda is not None:
            self.yandex_eda.close()

    def recover_stale_jobs(self) -> int:
        stale_before = _now() - timedelta(minutes=15)
        with self.session_factory() as session:
            result = session.execute(
                update(EnrichmentJob)
                .where(
                    EnrichmentJob.status == EnrichmentJobStatus.RUNNING,
                    EnrichmentJob.locked_at < stale_before,
                )
                .values(
                    status=EnrichmentJobStatus.RETRY,
                    next_attempt_at=_now(),
                    locked_at=None,
                    last_error="Recovered stale worker lock",
                )
            )
            session.commit()
            if result.rowcount:
                logger.warning(
                    "%d job(s) were left locked by a worker that died; retrying",
                    result.rowcount,
                )
            return result.rowcount

    def _claim(self) -> uuid.UUID | None:
        now = _now()
        with self.session_factory() as session:
            job = session.scalar(
                select(EnrichmentJob)
                .where(
                    EnrichmentJob.status.in_(
                        (EnrichmentJobStatus.PENDING, EnrichmentJobStatus.RETRY)
                    ),
                    or_(
                        EnrichmentJob.next_attempt_at.is_(None),
                        EnrichmentJob.next_attempt_at <= now,
                    ),
                )
                .order_by(EnrichmentJob.created_at, EnrichmentJob.id)
                .limit(1)
            )
            if job is None:
                return None
            job.status = EnrichmentJobStatus.RUNNING
            job.attempts += 1
            job.locked_at = now
            job.next_attempt_at = None
            job.last_error = None
            session.commit()
            return job.id

    def process_next(self) -> bool:
        job_id = self._claim()
        if job_id is None:
            return False
        try:
            self._process(job_id)
        except TemporaryEnrichmentError as exc:
            self._retry(job_id, str(exc))
        except Exception as exc:  # keep one malformed item from stopping the worker
            self._retry(job_id, f"Unexpected enrichment error: {exc}")
        return True

    def _process(self, job_id: uuid.UUID) -> None:
        started = time.monotonic()
        with self.session_factory() as session:
            job = session.scalar(
                select(EnrichmentJob)
                .where(EnrichmentJob.id == job_id)
                .options(
                    joinedload(EnrichmentJob.receipt_line).joinedload(ReceiptLine.receipt)
                )
            )
            if job is None:
                return
            line = job.receipt_line
            existing = self._find_existing(session, line)
            if existing is not None and not self._is_placeholder(existing):
                logger.info(
                    "%s: already known as %r, nothing to look up",
                    line.raw_name,
                    existing.canonical_name,
                )
                self._link(session, job, line, existing, provider="existing_product")
                session.commit()
                return
            query = self._query_from_line(line)
            existing_id = existing.id if existing is not None else None
            session.expunge_all()

        logger.info("%s: looking up", query.raw_name)
        result = self.resolve(query)
        elapsed = time.monotonic() - started

        with self.session_factory() as session:
            job = session.get(EnrichmentJob, job_id)
            if job is None:
                return
            line = session.get(ReceiptLine, job.receipt_line_id)
            if line is None:
                return
            if result is None:
                logger.warning(
                    "%s: no provider could answer, %.1fs", line.raw_name, elapsed
                )
                line.enrichment_status = EnrichmentStatus.AMBIGUOUS
                job.status = EnrichmentJobStatus.FAILED
                job.locked_at = None
                job.completed_at = _now()
                job.last_error = "No sufficiently confident product match"
                session.commit()
                return
            product = None
            if existing_id is not None:
                product = session.get(Product, existing_id)
            if product is None:
                product = self._upsert_product(session, line, result)
            else:
                self._apply_result(product, line, result)
                self._ensure_alias(session, line, product)
            logger.info(
                "%s: %s answered in %.1fs — %s, %s kcal/100",
                line.raw_name,
                result.provider,
                elapsed,
                product.canonical_name,
                result.kcal_per_100,
            )
            self._link(session, job, line, product, provider=result.provider, result=result)
            session.commit()

    def _query_from_line(self, line: ReceiptLine) -> EnrichmentQuery:
        return EnrichmentQuery(
            raw_name=line.raw_name,
            gtin=line.gtin,
            package_quantity=line.package_quantity,
            package_unit=line.package_unit,
        )

    def _is_placeholder(self, product: Product) -> bool:
        return is_placeholder_nutrition(
            product.kcal_per_100,
            product.protein_per_100,
            product.fat_per_100,
            product.carbs_per_100,
        )

    def resolve(self, query: EnrichmentQuery) -> EnrichmentResult | None:
        card: YandexCard | None = None
        if self.yandex_eda is not None:
            card = self.yandex_eda.lookup_card(query)
            if card is not None and card.nutrients is not None:
                return self.yandex_eda._to_result(query, card)
        result = self.open_food_facts.lookup(query.gtin)
        if result is None and self.reference_food is not None:
            result = self.reference_food.lookup(query.raw_name, query.gtin)
        if result is None and self.hermes is not None:
            result = self.hermes.lookup(query)
        if result is None:
            return None
        if card is not None and card.image_url and not result.image_url:
            result = replace(
                result,
                image_url=card.image_url,
                image_source_url=card.image_url,
            )
        return result

    def reprocess_placeholders(self, *, limit: int = 100) -> list[dict[str, object]]:
        with self.session_factory() as session:
            products = list(session.scalars(select(Product).order_by(Product.canonical_name)))
            targets: dict[str, list[uuid.UUID]] = {}
            names: dict[str, Product] = {}
            for product in products:
                if not self._is_placeholder(product):
                    continue
                targets.setdefault(product.canonical_name, []).append(product.id)
                names.setdefault(product.canonical_name, product)

        report: list[dict[str, object]] = []
        for name, product_ids in list(targets.items())[:limit]:
            sample = names[name]
            query = EnrichmentQuery(
                raw_name=sample.canonical_name,
                gtin=sample.gtin,
                package_quantity=sample.net_quantity,
                package_unit=sample.net_unit,
            )
            try:
                result = self.resolve(query)
                error = None
            except TemporaryEnrichmentError as exc:
                result = None
                error = str(exc)
            updated = 0
            if result is not None:
                with self.session_factory() as session:
                    for product_id in product_ids:
                        product = session.get(Product, product_id)
                        if product is None:
                            continue
                        self._apply_result(product, None, result)
                        updated += 1
                        for line in session.scalars(
                            select(ReceiptLine).where(ReceiptLine.product_id == product_id)
                        ):
                            line.enrichment_status = product.nutrition_status
                    session.commit()
            row = {
                "name": name,
                "ids": len(product_ids),
                "updated": updated,
                "provider": result.provider if result else None,
                "kcal_per_100": str(result.kcal_per_100) if result else None,
                "error": error,
            }
            print(json.dumps(row, ensure_ascii=False), flush=True)
            report.append(row)
        return report

    def _find_existing(self, session: Session, line: ReceiptLine) -> Product | None:
        if line.product_id:
            return session.get(Product, line.product_id)
        if line.gtin:
            code = normalize_gtin(line.gtin)
            product = session.scalar(
                select(Product).where(Product.owner_id == line.owner_id, Product.gtin == code)
            )
            if product is not None:
                return product
        alias = session.scalar(
            select(ProductAlias).where(
                ProductAlias.owner_id == line.owner_id,
                ProductAlias.merchant_inn == line.receipt.merchant_inn,
                ProductAlias.normalized_name == line.normalized_name,
            )
        )
        if alias is not None and alias.product is not None:
            if (
                line.package_quantity is not None
                and alias.product.net_quantity is not None
                and abs(alias.product.net_quantity - line.package_quantity)
                > line.package_quantity * Decimal("0.2")
            ):
                return None
            return alias.product
        return None

    def _upsert_product(
        self, session: Session, line: ReceiptLine, result: EnrichmentResult
    ) -> Product:
        gtin = normalize_gtin(result.gtin or line.gtin or "") or None
        product = None
        if gtin:
            product = session.scalar(
                select(Product).where(Product.owner_id == line.owner_id, Product.gtin == gtin)
            )
        if product is None:
            product = Product(
                owner_id=line.owner_id,
                canonical_name=result.canonical_name,
                gtin=gtin,
            )
            session.add(product)
            session.flush()
        should_apply = (
            product.nutrition_status != EnrichmentStatus.VERIFIED
            or result.verified
            or self._is_placeholder(product)
        )
        if should_apply:
            self._apply_result(product, line, result)
        self._ensure_alias(session, line, product)
        return product

    def _apply_result(
        self, product: Product, line: ReceiptLine | None, result: EnrichmentResult
    ) -> None:
        status = EnrichmentStatus.VERIFIED if result.verified else EnrichmentStatus.ESTIMATED
        final_net_qty = result.net_quantity
        line_unit = None
        if line is not None:
            final_net_qty = result.net_quantity or line.package_quantity
            line_unit = line.package_unit
            if (
                line.package_quantity is not None
                and result.net_quantity is not None
                and abs(result.net_quantity - line.package_quantity)
                > line.package_quantity * Decimal("0.2")
            ):
                final_net_qty = line.package_quantity
        product.canonical_name = result.canonical_name
        product.brand = result.brand or product.brand
        product.net_quantity = final_net_qty or product.net_quantity
        product.net_unit = _unit(result.net_unit) or _unit(line_unit) or product.net_unit
        product.piece_weight_g = result.piece_weight_g or product.piece_weight_g
        product.kcal_per_100 = result.kcal_per_100
        product.protein_per_100 = result.protein_per_100
        product.fat_per_100 = result.fat_per_100
        product.carbs_per_100 = result.carbs_per_100
        product.nutrition_status = status
        product.confidence = result.confidence
        incoming_image = result.image_url or ""
        current_image = product.image_url or ""
        if "get-eda" in incoming_image and "get-eda" not in current_image:
            product.image_url = result.image_url
            product.image_source_url = result.image_source_url or result.image_url
        elif not current_image:
            product.image_url = result.image_url
            product.image_source_url = result.image_source_url
        product.nutrition_source_url = result.nutrition_source_url
        if not product.image_source_url:
            product.image_source_url = result.image_source_url

    def _ensure_alias(self, session: Session, line: ReceiptLine, product: Product) -> None:
        alias = session.scalar(
            select(ProductAlias).where(
                ProductAlias.owner_id == line.owner_id,
                ProductAlias.merchant_inn == line.receipt.merchant_inn,
                ProductAlias.normalized_name == line.normalized_name,
            )
        )
        if alias is None:
            session.add(
                ProductAlias(
                    owner_id=line.owner_id,
                    product_id=product.id,
                    merchant_inn=line.receipt.merchant_inn,
                    raw_name=line.raw_name,
                    normalized_name=line.normalized_name,
                )
            )

    def _link(
        self,
        session: Session,
        job: EnrichmentJob,
        line: ReceiptLine,
        product: Product,
        *,
        provider: str,
        result: EnrichmentResult | None = None,
    ) -> None:
        line.product_id = product.id
        line.enrichment_status = product.nutrition_status
        lot = session.scalar(
            select(InventoryLot).where(
                InventoryLot.owner_id == line.owner_id,
                InventoryLot.receipt_line_id == line.id,
            )
        )
        if lot is not None:
            lot.product_id = product.id
            lot.display_name = product.canonical_name
        job.status = EnrichmentJobStatus.COMPLETED
        job.locked_at = None
        job.completed_at = _now()
        job.last_error = None
        job.result = {
            "product_id": str(product.id),
            "provider": provider,
            "enrichment": result.as_json() if result else None,
        }

    def _retry(self, job_id: uuid.UUID, error: str) -> None:
        with self.session_factory() as session:
            job = session.get(EnrichmentJob, job_id)
            if job is None:
                return
            job.locked_at = None
            job.last_error = error[-4000:]
            line = session.get(ReceiptLine, job.receipt_line_id)
            name = line.raw_name if line is not None else str(job_id)
            if job.attempts >= self.settings.enrichment_max_attempts:
                logger.error(
                    "%s: giving up after %d attempts — %s",
                    name,
                    job.attempts,
                    error,
                )
                job.status = EnrichmentJobStatus.FAILED
                job.completed_at = _now()
                if line is not None:
                    line.enrichment_status = EnrichmentStatus.FAILED
            else:
                job.status = EnrichmentJobStatus.RETRY
                minutes = min(60, 2 ** max(0, job.attempts - 1))
                job.next_attempt_at = _now() + timedelta(minutes=minutes)
                logger.warning(
                    "%s: attempt %d failed, retrying in %dm — %s",
                    name,
                    job.attempts,
                    minutes,
                    error,
                )
            session.commit()
