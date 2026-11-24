from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import (CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String,
                        Text, UniqueConstraint, Boolean)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.models.mixins import TenantMixin, TimestampMixin, utcnow

MOVEMENT_TYPES = ("receipt", "sale", "dispense", "return_in", "return_out", "adjustment", "transfer_out", "transfer_in", "write_off")


class MedicineCategory(Base, TenantMixin):
    __tablename__ = "medicine_categories"
    __table_args__ = (UniqueConstraint("pharmacy_id", "name", name="uq_category_pharmacy_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Supplier(Base, TenantMixin, TimestampMixin):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("pharmacy_id", "name", name="uq_supplier_pharmacy_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(50))
    default_lead_time_days: Mapped[int | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Medicine(Base, TenantMixin, TimestampMixin):
    __tablename__ = "medicines"
    __table_args__ = (
        CheckConstraint("min_stock_threshold >= 0", name="ck_medicine_min_stock_nonneg"),
        CheckConstraint("purchase_price >= 0", name="ck_medicine_purchase_price_nonneg"),
        Index("ix_medicine_pharmacy_name", "pharmacy_id", "name"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("medicine_categories.id"))
    preferred_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200))
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    dosage: Mapped[str | None] = mapped_column(String(80))
    formulation: Mapped[str | None] = mapped_column(String(80))
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    min_stock_threshold: Mapped[int] = mapped_column(default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category: Mapped[MedicineCategory | None] = relationship()
    batches: Mapped[list["Batch"]] = relationship(back_populates="medicine")


class Batch(Base, TenantMixin, TimestampMixin):
    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint("pharmacy_id", "medicine_id", "batch_number", name="uq_batch_number_per_medicine"),
        CheckConstraint("quantity_remaining >= 0", name="ck_batch_remaining_nonneg"),
        CheckConstraint("quantity_received > 0", name="ck_batch_received_positive"),
        CheckConstraint("quantity_remaining <= quantity_received", name="ck_batch_remaining_le_received"),
        Index("ix_batch_fefo", "pharmacy_id", "medicine_id", "expiration_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="RESTRICT"), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    batch_number: Mapped[str] = mapped_column(String(80), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity_received: Mapped[int] = mapped_column(nullable=False)
    quantity_remaining: Mapped[int] = mapped_column(nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    received_date: Mapped[date] = mapped_column(Date, nullable=False)

    medicine: Mapped[Medicine] = relationship(back_populates="batches")


class InventoryMovement(Base, TenantMixin):
    """Append-only ledger. Rows are never updated or deleted; corrections are new movements."""
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity <> 0", name="ck_movement_qty_nonzero"),
        Index("ix_movement_batch_time", "batch_id", "occurred_at"),
        Index("ix_movement_pharmacy_time", "pharmacy_id", "occurred_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="RESTRICT"), nullable=False)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="RESTRICT"), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)  # signed: + adds stock, - removes stock
    reason: Mapped[str | None] = mapped_column(Text)
    reference_type: Mapped[str | None] = mapped_column(String(30))  # sale | delivery | manual
    reference_id: Mapped[int | None] = mapped_column()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
