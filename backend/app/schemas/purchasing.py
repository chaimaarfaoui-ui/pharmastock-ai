from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class POItemIn(BaseModel):
    medicine_id: int
    quantity_ordered: int = Field(gt=0, le=10_000_000)
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class POCreate(BaseModel):
    supplier_id: int
    expected_delivery_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    items: list[POItemIn] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def no_duplicate_medicines(self):
        ids = [i.medicine_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each medicine may appear only once per purchase order")
        return self


class POItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    medicine_id: int
    quantity_ordered: int
    quantity_received: int
    unit_price: Decimal


class POOut(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str | None = None
    status: str
    expected_delivery_date: date | None
    ordered_at: datetime | None
    notes: str | None
    created_at: datetime
    total_value: Decimal
    items: list[POItemOut]


class ReceiveLine(BaseModel):
    po_item_id: int
    batch_number: str = Field(min_length=1, max_length=80)
    expiration_date: date
    quantity: int = Field(gt=0, le=10_000_000)
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class ReceiveIn(BaseModel):
    lines: list[ReceiveLine] = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
