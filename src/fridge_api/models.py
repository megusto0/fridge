from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fridge_api.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class ReceiptOperation(StrEnum):
    SALE = "sale"
    RETURN = "return"


class EnrichmentStatus(StrEnum):
    PENDING = "pending"
    MATCHED = "matched"
    VERIFIED = "verified"
    ESTIMATED = "estimated"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class ServingUnit(StrEnum):
    """How a product is eaten, once someone has said.

    Nothing about a product settles this on its own. An apple and a jar of
    sweetener both weigh 180 g a piece; a yoghurt and a tub of ice cream are
    both one package. The first is taken whole and the second by the spoonful,
    and only the person eating it knows which.
    """

    #: Taken whole: an apple, a yoghurt, an egg, one ice lolly.
    PIECES = "pcs"
    #: A package you take part of: a tub, a bag of grain, cake layers.
    GRAMS = "g"


class EnrichmentJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"


class InventoryStatus(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    DEPLETED = "depleted"
    DISCARDED = "discarded"
    RETURNED = "returned"


class InventoryTransactionKind(StrEnum):
    PURCHASE = "purchase"
    RESERVE = "reserve"
    RELEASE = "release"
    CONSUME = "consume"
    RETURN = "return"
    ADJUST = "adjust"


class BatchStatus(StrEnum):
    PORTIONING = "portioning"
    READY = "ready"
    CANCELLED = "cancelled"


class ContainerStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    CONSUMED = "consumed"
    DISCARDED = "discarded"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("owner_id", "gtin", name="uq_products_owner_gtin"),
        Index("ix_products_owner_name", "owner_id", "canonical_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(160))
    variant: Mapped[str | None] = mapped_column(String(200))
    gtin: Mapped[str | None] = mapped_column(String(32))
    net_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    net_unit: Mapped[str | None] = mapped_column(String(16))
    kcal_per_100: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    protein_per_100: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    fat_per_100: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    carbs_per_100: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    nutrition_status: Mapped[EnrichmentStatus] = mapped_column(
        Enum(EnrichmentStatus, native_enum=False), default=EnrichmentStatus.PENDING
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    image_url: Mapped[str | None] = mapped_column(Text)
    piece_weight_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    # Null until someone says. Enrichment can guess a piece's weight from a
    # label, but not whether a piece is what you eat, so this is left empty
    # rather than defaulted — an unanswered question, not a wrong answer.
    serving_unit: Mapped[ServingUnit | None] = mapped_column(
        Enum(ServingUnit, native_enum=False), nullable=True
    )
    nutrition_source_url: Mapped[str | None] = mapped_column(Text)
    image_source_url: Mapped[str | None] = mapped_column(Text)


class ProductAlias(Base, TimestampMixin):
    __tablename__ = "product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "merchant_inn", "normalized_name", name="uq_product_alias_lookup"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    merchant_inn: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    product: Mapped[Product] = relationship()


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "fiscal_fn", "fiscal_fd", "fiscal_fp", name="uq_receipt_fiscal"
        ),
        Index("ix_receipts_owner_purchased", "owner_id", "purchased_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    fiscal_fn: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_fd: Mapped[str] = mapped_column(String(32), nullable=False)
    fiscal_fp: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[ReceiptOperation] = mapped_column(
        Enum(ReceiptOperation, native_enum=False), nullable=False
    )
    merchant_name: Mapped[str] = mapped_column(String(300), nullable=False)
    merchant_inn: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(255))
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    lines: Mapped[list[ReceiptLine]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="ReceiptLine.position"
    )


class ReceiptLine(Base, TimestampMixin):
    __tablename__ = "receipt_lines"
    __table_args__ = (
        UniqueConstraint("receipt_id", "position", name="uq_receipt_line_position"),
        Index("ix_receipt_lines_owner_status", "owner_id", "enrichment_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    total_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    gtin: Mapped[str | None] = mapped_column(String(32))
    package_quantity: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    package_unit: Mapped[str | None] = mapped_column(String(16))
    inventory_effect: Mapped[bool] = mapped_column(
        default=True, server_default=true(), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    enrichment_status: Mapped[EnrichmentStatus] = mapped_column(
        Enum(EnrichmentStatus, native_enum=False), default=EnrichmentStatus.PENDING
    )
    receipt: Mapped[Receipt] = relationship(back_populates="lines")
    product: Mapped[Product | None] = relationship()


class InventoryLot(Base, TimestampMixin):
    __tablename__ = "inventory_lots"
    __table_args__ = (Index("ix_inventory_owner_status", "owner_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    receipt_line_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("receipt_lines.id", ondelete="SET NULL"), unique=True
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    original_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[InventoryStatus] = mapped_column(
        Enum(InventoryStatus, native_enum=False), default=InventoryStatus.AVAILABLE
    )
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    product: Mapped[Product | None] = relationship()
    receipt_line: Mapped[ReceiptLine | None] = relationship()


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    __table_args__ = (Index("ix_inventory_tx_owner_created", "owner_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[InventoryTransactionKind] = mapped_column(
        Enum(InventoryTransactionKind, native_enum=False), nullable=False
    )
    delta_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    lot: Mapped[InventoryLot] = relationship()


class EnrichmentJob(Base, TimestampMixin):
    __tablename__ = "enrichment_jobs"
    __table_args__ = (
        UniqueConstraint("owner_id", "receipt_line_id", name="uq_enrichment_receipt_line"),
        Index("ix_enrichment_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    receipt_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("receipt_lines.id", ondelete="CASCADE"), nullable=False
    )
    receipt_line: Mapped[ReceiptLine] = relationship()
    status: Mapped[EnrichmentJobStatus] = mapped_column(
        Enum(EnrichmentJobStatus, native_enum=False), default=EnrichmentJobStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MealPrepBatch(Base, TimestampMixin):
    __tablename__ = "meal_prep_batches"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_batch_idempotency"),
        Index("ix_batches_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    name_source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        Enum(BatchStatus, native_enum=False), default=BatchStatus.PORTIONING
    )
    image_url: Mapped[str | None] = mapped_column(Text)
    identification_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    kcal_total: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    protein_total: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    fat_total: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    carbs_total: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    cooked_yield_g: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    total_net_weight_g: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingredients: Mapped[list[BatchIngredient]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    containers: Mapped[list[MealPrepContainer]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class BatchIngredient(Base):
    __tablename__ = "batch_ingredients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_prep_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_lots.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    kcal: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    protein: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    fat: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    carbs: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    nutrition_estimated: Mapped[bool] = mapped_column(default=False, nullable=False)
    batch: Mapped[MealPrepBatch] = relationship(back_populates="ingredients")
    lot: Mapped[InventoryLot] = relationship()
    product: Mapped[Product | None] = relationship()


class ContainerType(Base, TimestampMixin):
    __tablename__ = "container_types"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_container_type_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tare_weight_g: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)


class MealPrepContainer(Base, TimestampMixin):
    __tablename__ = "meal_prep_containers"
    __table_args__ = (
        UniqueConstraint("public_code", name="uq_container_public_code"),
        Index("ix_containers_owner_status", "owner_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_prep_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    container_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("container_types.id", ondelete="SET NULL")
    )
    public_code: Mapped[str] = mapped_column(String(24), nullable=False)
    gross_weight_g: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    tare_weight_g: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    net_weight_g: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    remaining_weight_g: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    image_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ContainerStatus] = mapped_column(
        Enum(ContainerStatus, native_enum=False), default=ContainerStatus.READY
    )
    kcal: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    protein: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    fat: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    carbs: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=Decimal("0"))
    batch: Mapped[MealPrepBatch] = relationship(back_populates="containers")
    container_type: Mapped[ContainerType | None] = relationship()


class Consumption(Base):
    __tablename__ = "consumptions"
    __table_args__ = (Index("ix_consumptions_owner_consumed", "owner_id", "consumed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    container_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meal_prep_containers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    consumed_weight_g: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    kcal: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    protein: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    fat: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    carbs: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    glucotracker_meal_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    container: Mapped[MealPrepContainer] = relationship()
