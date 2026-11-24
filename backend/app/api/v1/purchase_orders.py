"""Purchase orders: draft -> approved -> ordered -> partially_received -> completed (or canceled).
Nothing is ever ordered automatically; every transition is an explicit, audited user action."""
from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.api.helpers import check_fk_owned, get_owned
from app.core.db import get_db
from app.models import Delivery, DeliveryItem, Medicine, PurchaseOrder, PurchaseOrderItem, Supplier, User
from app.schemas.common import Page
from app.schemas.purchasing import POCreate, POOut, ReceiveIn
from app.services import movements as mv
from app.services.audit import log_action

router = APIRouter(prefix="/purchase-orders", tags=["purchasing"])
BUY = require_permission("purchasing:write")      # admin, manager
RECEIVE = require_permission("movements:write")   # employees may receive deliveries
READ = require_permission("inventory:read")

TRANSITIONS = {"approve": ("draft", "approved"), "order": ("approved", "ordered")}
CANCELABLE = ("draft", "approved", "ordered")


def _out(po: PurchaseOrder, supplier_name: str | None) -> POOut:
    total = sum((Decimal(i.quantity_ordered) * i.unit_price for i in po.items), Decimal("0"))
    return POOut(id=po.id, supplier_id=po.supplier_id, supplier_name=supplier_name, status=po.status,
                 expected_delivery_date=po.expected_delivery_date, ordered_at=po.ordered_at, notes=po.notes,
                 created_at=po.created_at, total_value=total.quantize(Decimal("0.01")), items=po.items)


def _load(db, u, po_id, lock=False) -> PurchaseOrder:
    stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id, PurchaseOrder.pharmacy_id == u.pharmacy_id)
    po = db.scalar(stmt.with_for_update() if lock else stmt)
    if not po:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PurchaseOrder not found")
    return po


def _supplier_name(db, po) -> str | None:
    return db.scalar(select(Supplier.name).where(Supplier.id == po.supplier_id))


@router.post("", response_model=POOut, status_code=201)
def create_po(body: POCreate, u: User = Depends(BUY), db: Session = Depends(get_db)):
    check_fk_owned(db, Supplier, body.supplier_id, u.pharmacy_id, "supplier")
    for it in body.items:
        check_fk_owned(db, Medicine, it.medicine_id, u.pharmacy_id, "medicine")
    po = PurchaseOrder(pharmacy_id=u.pharmacy_id, supplier_id=body.supplier_id, status="draft",
                       expected_delivery_date=body.expected_delivery_date, notes=body.notes, created_by=u.id,
                       items=[PurchaseOrderItem(**i.model_dump()) for i in body.items])
    db.add(po)
    db.flush()
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="po.created", entity_type="purchase_order", entity_id=po.id)
    db.commit()
    return _out(po, _supplier_name(db, po))


@router.get("", response_model=Page[POOut])
def list_pos(status_: str | None = Query(None, alias="status"), supplier_id: int | None = None,
             limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
             u: User = Depends(READ), db: Session = Depends(get_db)):
    stmt = select(PurchaseOrder).where(PurchaseOrder.pharmacy_id == u.pharmacy_id)
    if status_:
        stmt = stmt.where(PurchaseOrder.status == status_)
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(db.scalars(stmt.order_by(PurchaseOrder.id.desc()).limit(limit).offset(offset)))
    return Page(items=[_out(p, _supplier_name(db, p)) for p in rows], total=total, limit=limit, offset=offset)


@router.get("/{po_id}", response_model=POOut)
def get_po(po_id: int, u: User = Depends(READ), db: Session = Depends(get_db)):
    po = _load(db, u, po_id)
    return _out(po, _supplier_name(db, po))


def _transition(action: str, po_id: int, u: User, db: Session) -> POOut:
    frm, to = TRANSITIONS[action]
    po = _load(db, u, po_id, lock=True)
    if po.status != frm:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot {action}: order is '{po.status}', expected '{frm}'")
    po.status = to
    if action == "approve":
        po.approved_by = u.id
    if action == "order":
        po.ordered_at = datetime.now(timezone.utc)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action=f"po.{action}", entity_type="purchase_order", entity_id=po.id)
    db.commit()
    return _out(po, _supplier_name(db, po))


@router.post("/{po_id}/approve", response_model=POOut)
def approve(po_id: int, u: User = Depends(BUY), db: Session = Depends(get_db)):
    return _transition("approve", po_id, u, db)


@router.post("/{po_id}/order", response_model=POOut)
def mark_ordered(po_id: int, u: User = Depends(BUY), db: Session = Depends(get_db)):
    return _transition("order", po_id, u, db)


@router.post("/{po_id}/cancel", response_model=POOut)
def cancel(po_id: int, u: User = Depends(BUY), db: Session = Depends(get_db)):
    po = _load(db, u, po_id, lock=True)
    if po.status not in CANCELABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot cancel an order that is '{po.status}'")
    po.status = "canceled"
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="po.canceled", entity_type="purchase_order", entity_id=po.id)
    db.commit()
    return _out(po, _supplier_name(db, po))


@router.post("/{po_id}/receive", response_model=POOut)
def receive(po_id: int, body: ReceiveIn, u: User = Depends(RECEIVE), db: Session = Depends(get_db)):
    po = _load(db, u, po_id, lock=True)
    if po.status not in ("ordered", "partially_received"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot receive goods for an order that is '{po.status}'")
    items = {i.id: i for i in po.items}
    incoming: dict[int, int] = {}
    for line in body.lines:
        if line.po_item_id not in items:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Item {line.po_item_id} is not on this order")
        incoming[line.po_item_id] = incoming.get(line.po_item_id, 0) + line.quantity
    for item_id, qty in incoming.items():
        it = items[item_id]
        if it.quantity_received + qty > it.quantity_ordered:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Item {item_id}: receiving {qty} would exceed the ordered quantity "
                                f"({it.quantity_received} of {it.quantity_ordered} already received)")
    delivery = Delivery(pharmacy_id=u.pharmacy_id, purchase_order_id=po.id, received_by=u.id, notes=body.notes)
    db.add(delivery)
    db.flush()
    for line in body.lines:
        it = items[line.po_item_id]
        batch = mv.receive_batch(db, pharmacy_id=u.pharmacy_id, medicine_id=it.medicine_id,
                                 batch_number=line.batch_number, expiration_date=line.expiration_date,
                                 quantity=line.quantity, unit_cost=line.unit_cost if line.unit_cost is not None else it.unit_price,
                                 supplier_id=po.supplier_id, received_date=date.today(), user_id=u.id,
                                 ref_type="delivery", ref_id=delivery.id)
        it.quantity_received += line.quantity
        db.add(DeliveryItem(delivery_id=delivery.id, po_item_id=it.id, batch_id=batch.id, quantity=line.quantity))
    po.status = "completed" if all(i.quantity_received == i.quantity_ordered for i in po.items) else "partially_received"
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="po.received", entity_type="purchase_order",
               entity_id=po.id, details={"delivery_id": delivery.id, "status": po.status})
    db.commit()
    return _out(po, _supplier_name(db, po))
