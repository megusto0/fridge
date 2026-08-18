from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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
from fridge_api.services.enrichment.types import EnrichmentResult, TemporaryEnrichmentError
from fridge_api.services.enrichment.yandex_eda import YandexEdaProvider, YandexEdaMagnitProvider


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
                executable=settings.enrichment_hermes_bin,
                timeout_seconds=settings.enrichment_hermes_timeout_seconds,
            )

    def close(self) -> None:
        self.open_food_facts.close()

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
            if existing is not None:
                self._link(session, job, line, existing, provider="existing_product")
                session.commit()
                return

            result = None
            if self.yandex_eda is not None:
                result = self.yandex_eda.lookup(line)
            if result is None:
                result = self.open_food_facts.lookup(line.gtin)
            if result is None and self.reference_food is not None:
                result = self.reference_food.lookup(line.raw_name, line.gtin)
            if result is None and self.hermes is not None:
                result = self.hermes.lookup(line)
            if result is None:
                line.enrichment_status = EnrichmentStatus.AMBIGUOUS
                job.status = EnrichmentJobStatus.FAILED
                job.locked_at = None
                job.completed_at = _now()
                job.last_error = "No sufficiently confident product match"
                session.commit()
                return

            product = self._upsert_product(session, line, result)
            self._link(session, job, line, product, provider=result.provider, result=result)
            session.commit()

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
        return alias.product if alias is not None else None

    def _upsert_product(
        self, session: Session, line: ReceiptLine, result: EnrichmentResult
    ) -> Product:
        gtin = normalize_gtin(result.gtin or line.gtin or "") or None
        product = None
        if gtin:
            product = session.scalar(
                select(Product).where(Product.owner_id == line.owner_id, Product.gtin == gtin)
            )
        status = EnrichmentStatus.VERIFIED if result.verified else EnrichmentStatus.ESTIMATED
        if product is None:
            product = Product(
                owner_id=line.owner_id,
                canonical_name=result.canonical_name,
                brand=result.brand,
                gtin=gtin,
                net_quantity=result.net_quantity or line.package_quantity,
                net_unit=_unit(result.net_unit or line.package_unit),
                kcal_per_100=result.kcal_per_100,
                protein_per_100=result.protein_per_100,
                fat_per_100=result.fat_per_100,
                carbs_per_100=result.carbs_per_100,
                nutrition_status=status,
                confidence=result.confidence,
                image_url=result.image_url,
                piece_weight_g=result.piece_weight_g,
                nutrition_source_url=result.nutrition_source_url,
                image_source_url=result.image_source_url,
            )
            session.add(product)
            session.flush()
        elif product.nutrition_status != EnrichmentStatus.VERIFIED or result.verified:
            product.canonical_name = result.canonical_name
            product.brand = result.brand or product.brand
            product.net_quantity = result.net_quantity or product.net_quantity
            product.net_unit = _unit(result.net_unit) or product.net_unit
            product.piece_weight_g = result.piece_weight_g or product.piece_weight_g
            product.kcal_per_100 = result.kcal_per_100
            product.protein_per_100 = result.protein_per_100
            product.fat_per_100 = result.fat_per_100
            product.carbs_per_100 = result.carbs_per_100
            product.nutrition_status = status
            product.confidence = result.confidence
            product.image_url = result.image_url or product.image_url
            product.nutrition_source_url = result.nutrition_source_url
            product.image_source_url = result.image_source_url or product.image_source_url

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
        return product

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
            if job.attempts >= self.settings.enrichment_max_attempts:
                job.status = EnrichmentJobStatus.FAILED
                job.completed_at = _now()
                line = session.get(ReceiptLine, job.receipt_line_id)
                if line is not None:
                    line.enrichment_status = EnrichmentStatus.FAILED
            else:
                job.status = EnrichmentJobStatus.RETRY
                minutes = min(60, 2 ** max(0, job.attempts - 1))
                job.next_attempt_at = _now() + timedelta(minutes=minutes)
            session.commit()
