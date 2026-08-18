from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fridge_api.models import (
    BatchStatus,
    ContainerStatus,
    EnrichmentStatus,
    InventoryStatus,
    ReceiptOperation,
)


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=300)
    brand: str | None = Field(default=None, max_length=160)
    variant: str | None = Field(default=None, max_length=200)
    gtin: str | None = Field(default=None, max_length=32)
    net_quantity: Decimal | None = Field(default=None, gt=0)
    net_unit: str | None = Field(default=None, max_length=16)
    piece_weight_g: Decimal | None = Field(default=None, gt=0)
    kcal_per_100: Decimal | None = Field(default=None, ge=0)
    protein_per_100: Decimal | None = Field(default=None, ge=0)
    fat_per_100: Decimal | None = Field(default=None, ge=0)
    carbs_per_100: Decimal | None = Field(default=None, ge=0)
    nutrition_status: EnrichmentStatus = EnrichmentStatus.PENDING
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    image_url: str | None = None
    nutrition_source_url: str | None = None
    image_source_url: str | None = None

    @model_validator(mode="after")
    def validate_net_quantity(self) -> ProductCreate:
        if (self.net_quantity is None) != (self.net_unit is None):
            raise ValueError("net_quantity and net_unit must be set together")
        return self


class ProductResponse(OrmModel):
    id: uuid.UUID
    owner_id: uuid.UUID | None
    canonical_name: str
    brand: str | None
    variant: str | None
    gtin: str | None
    net_quantity: Decimal | None
    net_unit: str | None
    piece_weight_g: Decimal | None
    kcal_per_100: Decimal | None
    protein_per_100: Decimal | None
    fat_per_100: Decimal | None
    carbs_per_100: Decimal | None
    nutrition_status: EnrichmentStatus
    confidence: Decimal | None
    image_url: str | None
    nutrition_source_url: str | None
    image_source_url: str | None


class ProductAliasCreate(BaseModel):
    merchant_inn: str = Field(default="", max_length=20)
    raw_name: str = Field(min_length=1, max_length=500)


class ReceiptItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=16)
    unit_price_minor: int = Field(ge=0)
    total_minor: int = Field(ge=0)
    gtin: str | None = Field(default=None, max_length=32)
    package_quantity: Decimal | None = Field(default=None, gt=0)
    package_unit: str | None = Field(default=None, max_length=16)
    inventory_effect: bool = True

    @model_validator(mode="after")
    def validate_package_quantity(self) -> ReceiptItemInput:
        if (self.package_quantity is None) != (self.package_unit is None):
            raise ValueError("package_quantity and package_unit must be set together")
        return self

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str) -> str:
        aliases = {
            "шт": "pcs",
            "шт.": "pcs",
            "piece": "pcs",
            "pieces": "pcs",
            "кг": "kg",
            "г": "g",
            "л": "l",
            "мл": "ml",
        }
        normalized = value.strip().lower()
        return aliases.get(normalized, normalized)


class ReceiptImportRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    fiscal_fn: str = Field(min_length=1, max_length=32)
    fiscal_fd: str = Field(min_length=1, max_length=32)
    fiscal_fp: str = Field(min_length=1, max_length=32)
    operation: ReceiptOperation = ReceiptOperation.SALE
    merchant_name: str = Field(min_length=1, max_length=300)
    merchant_inn: str = Field(default="", max_length=20)
    purchased_at: datetime
    total_minor: int = Field(ge=0)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    source_message_id: str | None = Field(default=None, max_length=255)
    items: list[ReceiptItemInput] = Field(min_length=1)
    raw_payload: dict = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("purchased_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("purchased_at must include a timezone offset")
        return value


class ReceiptLineResponse(OrmModel):
    id: uuid.UUID
    position: int
    raw_name: str
    quantity: Decimal
    unit: str
    unit_price_minor: int
    total_minor: int
    gtin: str | None
    package_quantity: Decimal | None
    package_unit: str | None
    inventory_effect: bool
    product_id: uuid.UUID | None
    enrichment_status: EnrichmentStatus


class ReceiptResponse(OrmModel):
    id: uuid.UUID
    provider: str
    fiscal_fn: str
    fiscal_fd: str
    fiscal_fp: str
    operation: ReceiptOperation
    merchant_name: str
    merchant_inn: str
    purchased_at: datetime
    total_minor: int
    currency: str
    source_message_id: str | None
    lines: list[ReceiptLineResponse]


class ReceiptImportResponse(BaseModel):
    created: bool
    inventory_lots_created: int
    enrichment_jobs_created: int
    receipt: ReceiptResponse


class ResolveReceiptLineRequest(BaseModel):
    product_id: uuid.UUID
    save_alias: bool = True


class InventoryLotResponse(OrmModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    receipt_line_id: uuid.UUID | None
    display_name: str
    original_quantity: Decimal
    remaining_quantity: Decimal
    unit: str
    status: InventoryStatus
    purchased_at: datetime
    expires_at: datetime | None
    days_to_expiry: int | None = None
    weight_grams: Decimal | None = None
    estimated_pieces: int | None = None
    product: InventoryProductSummary | None = None


class InventoryProductSummary(OrmModel):
    id: uuid.UUID
    canonical_name: str
    brand: str | None
    gtin: str | None
    net_quantity: Decimal | None
    net_unit: str | None
    piece_weight_g: Decimal | None = None
    kcal_per_100: Decimal | None
    protein_per_100: Decimal | None
    fat_per_100: Decimal | None
    carbs_per_100: Decimal | None
    nutrition_status: EnrichmentStatus
    confidence: Decimal | None
    image_url: str | None
    nutrition_source_url: str | None


class BatchIngredientInput(BaseModel):
    lot_id: uuid.UUID
    quantity: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=16)

    @field_validator("unit")
    @classmethod
    def normalize_unit(cls, value: str) -> str:
        return ReceiptItemInput.normalize_unit(value)


class MealPrepBatchCreate(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=300)
    image_url: str | None = None
    identification_confidence: Decimal | None = Field(default=None, ge=0, le=1)
    ingredients: list[BatchIngredientInput] = Field(min_length=1)


class MealPrepBatchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    name_source: str | None = Field(default=None, max_length=32)
    image_url: str | None = None
    cooked_yield_g: Decimal | None = Field(default=None, gt=0)


class NameSuggestionMode(StrEnum):
    FAST = "fast"
    HERMES = "hermes"


class NameSuggestionRequest(BaseModel):
    mode: NameSuggestionMode = NameSuggestionMode.FAST


class NameSuggestionResponse(BaseModel):
    name: str
    source: str
    fallback_used: bool = False


class PortionMode(StrEnum):
    EQUAL = "equal"
    FIXED = "fixed"
    CUSTOM = "custom"


class CustomPortionInput(BaseModel):
    net_weight_g: Decimal = Field(gt=0)
    image_url: str | None = None


class PortionPlanRequest(BaseModel):
    mode: PortionMode
    cooked_yield_g: Decimal = Field(gt=0)
    container_count: int | None = Field(default=None, ge=1, le=100)
    fixed_net_weight_g: Decimal | None = Field(default=None, gt=0)
    include_remainder: bool = True
    portions: list[CustomPortionInput] = Field(default_factory=list, max_length=100)
    container_type_id: uuid.UUID | None = None
    tare_weight_g: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_mode_fields(self) -> PortionPlanRequest:
        if self.mode == PortionMode.EQUAL and self.container_count is None:
            raise ValueError("container_count is required for equal portions")
        if self.mode == PortionMode.FIXED and self.fixed_net_weight_g is None:
            raise ValueError("fixed_net_weight_g is required for fixed portions")
        if self.mode == PortionMode.CUSTOM and not self.portions:
            raise ValueError("portions are required for custom mode")
        if self.tare_weight_g is None and self.container_type_id is None:
            raise ValueError("tare_weight_g or container_type_id is required")
        return self


class BatchIngredientResponse(OrmModel):
    id: uuid.UUID
    lot_id: uuid.UUID
    product_id: uuid.UUID | None
    display_name: str
    quantity: Decimal
    unit: str
    kcal: Decimal
    protein: Decimal
    fat: Decimal
    carbs: Decimal
    nutrition_estimated: bool


class ContainerResponse(OrmModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    container_type_id: uuid.UUID | None
    public_code: str
    gross_weight_g: Decimal
    tare_weight_g: Decimal
    net_weight_g: Decimal
    remaining_weight_g: Decimal
    image_url: str | None
    status: ContainerStatus
    kcal: Decimal
    protein: Decimal
    fat: Decimal
    carbs: Decimal


class MealPrepBatchResponse(OrmModel):
    id: uuid.UUID
    idempotency_key: str
    name: str
    name_source: str
    status: BatchStatus
    image_url: str | None
    identification_confidence: Decimal | None
    kcal_total: Decimal
    protein_total: Decimal
    fat_total: Decimal
    carbs_total: Decimal
    cooked_yield_g: Decimal | None
    total_net_weight_g: Decimal
    finalized_at: datetime | None
    cancelled_at: datetime | None
    ingredients: list[BatchIngredientResponse]
    containers: list[ContainerResponse]


class ContainerTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    tare_weight_g: Decimal = Field(ge=0)


class ContainerTypeResponse(OrmModel):
    id: uuid.UUID
    name: str
    tare_weight_g: Decimal


class ContainerCreate(BaseModel):
    gross_weight_g: Decimal = Field(gt=0)
    tare_weight_g: Decimal | None = Field(default=None, ge=0)
    container_type_id: uuid.UUID | None = None
    image_url: str | None = None

    @model_validator(mode="after")
    def require_tare_source(self) -> ContainerCreate:
        if self.tare_weight_g is None and self.container_type_id is None:
            raise ValueError("tare_weight_g or container_type_id is required")
        return self


class ConsumeItem(BaseModel):
    lot_id: uuid.UUID
    quantity: Decimal | None = None
    unit: str | None = None


class BatchConsumeRequest(BaseModel):
    items: list[ConsumeItem]
    reason: str = "consumed"
    # Which GlucoTracker entry caused this. Without it a consumption cannot be
    # undone when that entry is deleted: the transaction referenced the lot it
    # came out of, which says what changed but not why.
    glucotracker_meal_id: uuid.UUID | None = None


class ConsumeRevertRequest(BaseModel):
    glucotracker_meal_id: uuid.UUID


class ConsumeRevertResponse(BaseModel):
    reverted_lots: int
    reverted_containers: int


class ConsumptionCreate(BaseModel):
    consumed_weight_g: Decimal | None = Field(default=None, gt=0)
    glucotracker_meal_id: uuid.UUID | None = None


class ConsumptionResponse(OrmModel):
    id: uuid.UUID
    container_id: uuid.UUID
    consumed_weight_g: Decimal
    kcal: Decimal
    protein: Decimal
    fat: Decimal
    carbs: Decimal
    glucotracker_meal_id: uuid.UUID | None
    consumed_at: datetime


class ContainerLabelResponse(BaseModel):
    container_id: uuid.UUID
    public_code: str
    data_matrix_value: str
    dish_name: str
    prepared_at: datetime
    net_weight_g: Decimal
    kcal: Decimal
    protein: Decimal
    fat: Decimal
    carbs: Decimal


class ImageUploadResponse(BaseModel):
    url: str
    content_type: str
    size: int
