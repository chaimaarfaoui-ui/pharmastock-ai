from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.db import Base
from app.models.mixins import TenantMixin, TimestampMixin, utcnow

PO_STATUSES = ("draft", "approved", "ordered", "partially_received", "completed", "canceled")


class PurchaseOrder(Base, TenantMixin, TimestampMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (Index("ix_po_pharmacy_status", "pharmacy_id", "status"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # starts the lead-time clock
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    items: Mapped[list["PurchaseOrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_poi_ordered_positive"),
        CheckConstraint("quantity_received >= 0 AND quantity_received <= quantity_ordered", name="ck_poi_received_bounds"),
        UniqueConstraint("purchase_order_id", "medicine_id", name="uq_poi_order_medicine"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="RESTRICT"), nullable=False)
    quantity_ordered: Mapped[int] = mapped_column(nullable=False)
    quantity_received: Mapped[int] = mapped_column(default=0, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")


class Delivery(Base, TenantMixin):
    """A physical receipt event against a purchase order. Actual dates/quantities feed lead-time analysis."""
    __tablename__ = "deliveries"
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class DeliveryItem(Base):
    __tablename__ = "delivery_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_delivery_item_qty_positive"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), index=True)
    po_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_items.id", ondelete="RESTRICT"))
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(nullable=False)
