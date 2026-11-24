from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
from app.models.mixins import TenantMixin, utcnow


class AuditLog(Base, TenantMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_pharmacy_time", "pharmacy_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column()
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
