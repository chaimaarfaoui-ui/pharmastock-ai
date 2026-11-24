from datetime import datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.models.mixins import TenantMixin, utcnow


class Sale(Base, TenantMixin):
    """One dispensing/sale record per medicine. Batch-level detail lives in inventory_movements."""
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sale_qty_positive"),
        Index("ix_sale_pharmacy_med_time", "pharmacy_id", "medicine_id", "sold_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    medicine_id: Mapped[int] = mapped_column(ForeignKey("medicines.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sold_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
