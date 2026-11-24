"""Inventory movement engine: the only code allowed to change batch quantities.

Invariants (also enforced by DB CHECK constraints):
  * 0 <= quantity_remaining <= quantity_received
  * every change is recorded as a signed row in the append-only inventory_movements ledger,
    written in the same transaction as the quantity change
  * FEFO: stock is issued from the batch expiring first; expired batches are never issued
Callers own the transaction (commit/rollback).
"""
from dataclasses import dataclass
from datetime import date, datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Batch, InventoryMovement, Medicine


class InventoryError(Exception):
    """Business-rule violation (mapped to HTTP 409/422 by the API layer)."""
    def __init__(self, message: str, code: str = "inventory_error"):
        super().__init__(message)
        self.message, self.code = message, code


class InsufficientStock(InventoryError):
    def __init__(self, requested: int, available: int):
        super().__init__(f"Insufficient non-expired stock: requested {requested}, available {available}",
                         "insufficient_stock")
        self.requested, self.available = requested, available


@dataclass
class Allocation:
    batch: Batch
    quantity: int


def _record(db: Session, batch: Batch, delta: int, mtype: str, user_id: int | None, reason: str | None,
            ref_type: str | None, ref_id: int | None, occurred_at: datetime | None = None) -> InventoryMovement:
    new_qty = batch.quantity_remaining + delta
    if new_qty < 0:
        raise InsufficientStock(-delta, batch.quantity_remaining)
    if new_qty > batch.quantity_received:
        raise InventoryError("Quantity would exceed the amount originally received for this batch", "exceeds_received")
    batch.quantity_remaining = new_qty
    extra = {"occurred_at": occurred_at} if occurred_at is not None else {}   # default (now) when not importing history
    mv = InventoryMovement(pharmacy_id=batch.pharmacy_id, batch_id=batch.id, medicine_id=batch.medicine_id,
                           movement_type=mtype, quantity=delta, reason=reason, user_id=user_id,
                           reference_type=ref_type, reference_id=ref_id, **extra)
    db.add(mv)
    return mv


def _get_medicine(db: Session, pharmacy_id: int, medicine_id: int) -> Medicine:
    med = db.scalar(select(Medicine).where(Medicine.id == medicine_id, Medicine.pharmacy_id == pharmacy_id))
    if not med:
        raise InventoryError("Medicine not found", "not_found")
    return med


def _get_batch_locked(db: Session, pharmacy_id: int, batch_id: int) -> Batch:
    b = db.scalar(select(Batch).where(Batch.id == batch_id, Batch.pharmacy_id == pharmacy_id).with_for_update())
    if not b:
        raise InventoryError("Batch not found", "not_found")
    return b


def receive_batch(db: Session, *, pharmacy_id: int, medicine_id: int, batch_number: str, expiration_date: date,
                  quantity: int, unit_cost, supplier_id: int | None, received_date: date, user_id: int | None,
                  ref_type: str = "manual", ref_id: int | None = None, today: date | None = None,
                  occurred_at: datetime | None = None) -> Batch:
    today = today or date.today()
    _get_medicine(db, pharmacy_id, medicine_id)
    if quantity <= 0:
        raise InventoryError("Quantity must be positive", "invalid_quantity")
    if expiration_date < today:
        raise InventoryError("Cannot receive an already-expired batch", "expired_batch")
    batch = Batch(pharmacy_id=pharmacy_id, medicine_id=medicine_id, supplier_id=supplier_id,
                  batch_number=batch_number.strip(), expiration_date=expiration_date, quantity_received=quantity,
                  quantity_remaining=0, unit_cost=unit_cost, received_date=received_date)
    db.add(batch)
    db.flush()
    _record(db, batch, quantity, "receipt", user_id, None, ref_type, ref_id, occurred_at)
    return batch


def allocate_fefo(db: Session, *, pharmacy_id: int, medicine_id: int, quantity: int, movement_type: str,
                  user_id: int | None, reason: str | None = None, ref_type: str | None = None,
                  ref_id: int | None = None, today: date | None = None,
                  occurred_at: datetime | None = None) -> list[Allocation]:
    """Issue `quantity` units first-expired-first-out across non-expired batches (all-or-nothing)."""
    if movement_type not in ("sale", "dispense"):
        raise InventoryError("FEFO allocation is only for sales and dispensing", "invalid_type")
    if quantity <= 0:
        raise InventoryError("Quantity must be positive", "invalid_quantity")
    today = today or date.today()
    _get_medicine(db, pharmacy_id, medicine_id)
    batches = list(db.scalars(
        select(Batch).where(Batch.pharmacy_id == pharmacy_id, Batch.medicine_id == medicine_id,
                            Batch.quantity_remaining > 0, Batch.expiration_date >= today,
                            Batch.received_date <= today)      # stock not yet received cannot be sold
        .order_by(Batch.expiration_date, Batch.id).with_for_update()))
    available = sum(b.quantity_remaining for b in batches)
    if available < quantity:
        raise InsufficientStock(quantity, available)
    left, out = quantity, []
    for b in batches:
        if left == 0:
            break
        take = min(left, b.quantity_remaining)
        _record(db, b, -take, movement_type, user_id, reason, ref_type, ref_id, occurred_at)
        out.append(Allocation(b, take))
        left -= take
    return out


def write_off(db: Session, *, pharmacy_id: int, batch_id: int, quantity: int, reason: str, user_id: int | None):
    """Remove stock that is expired, damaged or recalled. Works on any batch, including expired ones."""
    if quantity <= 0:
        raise InventoryError("Quantity must be positive", "invalid_quantity")
    if not reason.strip():
        raise InventoryError("A reason is required for write-offs", "reason_required")
    b = _get_batch_locked(db, pharmacy_id, batch_id)
    return _record(db, b, -quantity, "write_off", user_id, reason, "manual", None)


def adjust(db: Session, *, pharmacy_id: int, batch_id: int, new_quantity: int, reason: str, user_id: int | None):
    """Stock-count correction: sets remaining to a counted value, recording the signed difference."""
    if not reason.strip():
        raise InventoryError("A reason is required for adjustments", "reason_required")
    b = _get_batch_locked(db, pharmacy_id, batch_id)
    delta = new_quantity - b.quantity_remaining
    if delta == 0:
        raise InventoryError("Counted quantity equals current quantity; nothing to adjust", "no_change")
    return _record(db, b, delta, "adjustment", user_id, reason, "manual", None)


def customer_return(db: Session, *, pharmacy_id: int, batch_id: int, quantity: int, reason: str | None,
                    user_id: int | None, today: date | None = None):
    """Customer returns restock the original batch only if it is still within date."""
    today = today or date.today()
    if quantity <= 0:
        raise InventoryError("Quantity must be positive", "invalid_quantity")
    b = _get_batch_locked(db, pharmacy_id, batch_id)
    if b.expiration_date < today:
        raise InventoryError("Returned stock from an expired batch cannot be restocked; use a write-off", "expired_batch")
    return _record(db, b, quantity, "return_in", user_id, reason, "manual", None)


def return_to_supplier(db: Session, *, pharmacy_id: int, batch_id: int, quantity: int, reason: str,
                       user_id: int | None):
    if quantity <= 0:
        raise InventoryError("Quantity must be positive", "invalid_quantity")
    if not reason.strip():
        raise InventoryError("A reason is required for supplier returns", "reason_required")
    b = _get_batch_locked(db, pharmacy_id, batch_id)
    return _record(db, b, -quantity, "return_out", user_id, reason, "manual", None)
