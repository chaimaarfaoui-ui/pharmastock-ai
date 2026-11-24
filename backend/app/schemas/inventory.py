from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, EmailStr

Money = Field(ge=0, max_digits=12, decimal_places=2)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class CategoryOut(CategoryIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class SupplierIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    default_lead_time_days: int | None = Field(default=None, ge=0, le=365)


class SupplierPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    default_lead_time_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool | None = None


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    default_lead_time_days: int | None
    is_active: bool


class MedicineIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=200)
    active_ingredient: str | None = Field(default=None, max_length=200)
    dosage: str | None = Field(default=None, max_length=80)
    formulation: str | None = Field(default=None, max_length=80)
    category_id: int | None = None
    preferred_supplier_id: int | None = None
    purchase_price: Decimal = Field(default=Decimal("0"), ge=0, max_digits=12, decimal_places=2)
    selling_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    min_stock_threshold: int = Field(default=0, ge=0, le=10_000_000)


class MedicinePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    brand: str | None = None
    active_ingredient: str | None = None
    dosage: str | None = None
    formulation: str | None = None
    category_id: int | None = None
    preferred_supplier_id: int | None = None
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    selling_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    min_stock_threshold: int | None = Field(default=None, ge=0, le=10_000_000)
    is_active: bool | None = None


class MedicineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    brand: str | None
    active_ingredient: str | None
    dosage: str | None
    formulation: str | None
    category_id: int | None
    category_name: str | None = None
    preferred_supplier_id: int | None
    purchase_price: Decimal
    selling_price: Decimal | None
    min_stock_threshold: int
    is_active: bool
    total_stock: int = 0        # all remaining units, including expired batches
    available_stock: int = 0    # non-expired units only: what can actually be dispensed
    below_threshold: bool = False


class BatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_id: int
    medicine_name: str | None = None
    supplier_id: int | None
    batch_number: str
    expiration_date: date
    quantity_received: int
    quantity_remaining: int
    unit_cost: Decimal
    received_date: date
    days_to_expiry: int
    is_expired: bool
    remaining_value: Decimal


class ReceiptIn(BaseModel):
    medicine_id: int
    batch_number: str = Field(min_length=1, max_length=80)
    expiration_date: date
    quantity: int = Field(gt=0, le=10_000_000)
    unit_cost: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    supplier_id: int | None = None
    received_date: date | None = None


class SaleIn(BaseModel):
    medicine_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    movement_type: str = Field(default="sale", pattern="^(sale|dispense)$")


class AllocationOut(BaseModel):
    batch_id: int
    batch_number: str
    expiration_date: date
    quantity: int


class SaleOut(BaseModel):
    id: int
    medicine_id: int
    quantity: int
    unit_price: Decimal | None
    sold_at: datetime
    allocations: list[AllocationOut]


class BatchQtyIn(BaseModel):
    batch_id: int
    quantity: int = Field(gt=0, le=10_000_000)
    reason: str | None = Field(default=None, max_length=500)


class WriteOffIn(BatchQtyIn):
    reason: str = Field(min_length=3, max_length=500)


class SupplierReturnIn(BatchQtyIn):
    reason: str = Field(min_length=3, max_length=500)


class AdjustIn(BaseModel):
    batch_id: int
    new_quantity: int = Field(ge=0, le=10_000_000)
    reason: str = Field(min_length=3, max_length=500)


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    batch_id: int
    medicine_id: int
    movement_type: str
    quantity: int
    reason: str | None
    reference_type: str | None
    reference_id: int | None
    user_id: int | None
    occurred_at: datetime
