"""Stock operations. All quantity changes go through services.movements."""
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.api.helpers import check_fk_owned
from app.core.db import get_db
from app.models import InventoryMovement, Sale, Supplier, User
from app.schemas.common import Page
from app.schemas.inventory import (AdjustIn, AllocationOut, BatchQtyIn, MovementOut, ReceiptIn, SaleIn, SaleOut,
                                   SupplierReturnIn, WriteOffIn)
from app.services import movements as mv
from app.services.audit import log_action

router = APIRouter(tags=["inventory"])
OPERATE = require_permission("movements:write")   # admin, manager, employee
MANAGE = require_permission("inventory:write")    # admin, manager only (corrections that change value/records)


@router.post("/inventory/receipts", status_code=201)
def manual_receipt(body: ReceiptIn, u: User = Depends(OPERATE), db: Session = Depends(get_db)):
    check_fk_owned(db, Supplier, body.supplier_id, u.pharmacy_id, "supplier")
    b = mv.receive_batch(db, pharmacy_id=u.pharmacy_id, medicine_id=body.medicine_id, batch_number=body.batch_number,
                         expiration_date=body.expiration_date, quantity=body.quantity, unit_cost=body.unit_cost,
                         supplier_id=body.supplier_id, received_date=body.received_date or date.today(), user_id=u.id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="inventory.receipt", entity_type="batch",
               entity_id=b.id, details={"quantity": body.quantity})
    db.commit()
    return {"batch_id": b.id, "quantity_remaining": b.quantity_remaining}


@router.post("/sales", response_model=SaleOut, status_code=201)
def create_sale(body: SaleIn, u: User = Depends(OPERATE), db: Session = Depends(get_db)):
    sale = Sale(pharmacy_id=u.pharmacy_id, medicine_id=body.medicine_id, quantity=body.quantity,
                unit_price=body.unit_price, user_id=u.id)
    db.add(sale)
    db.flush()
    allocs = mv.allocate_fefo(db, pharmacy_id=u.pharmacy_id, medicine_id=body.medicine_id, quantity=body.quantity,
                              movement_type=body.movement_type, user_id=u.id, ref_type="sale", ref_id=sale.id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="inventory.sale", entity_type="sale",
               entity_id=sale.id, details={"quantity": body.quantity, "batches": [a.batch.id for a in allocs]})
    db.commit()
    return SaleOut(id=sale.id, medicine_id=sale.medicine_id, quantity=sale.quantity, unit_price=sale.unit_price,
                   sold_at=sale.sold_at,
                   allocations=[AllocationOut(batch_id=a.batch.id, batch_number=a.batch.batch_number,
                                              expiration_date=a.batch.expiration_date, quantity=a.quantity) for a in allocs])


@router.post("/inventory/returns/customer", status_code=201)
def customer_return(body: BatchQtyIn, u: User = Depends(OPERATE), db: Session = Depends(get_db)):
    m = mv.customer_return(db, pharmacy_id=u.pharmacy_id, batch_id=body.batch_id, quantity=body.quantity,
                           reason=body.reason, user_id=u.id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="inventory.customer_return", entity_type="batch", entity_id=body.batch_id)
    db.commit()
    return {"movement_id": m.id}


@router.post("/inventory/returns/supplier", status_code=201)
def supplier_return(body: SupplierReturnIn, u: User = Depends(MANAGE), db: Session = Depends(get_db)):
    m = mv.return_to_supplier(db, pharmacy_id=u.pharmacy_id, batch_id=body.batch_id, quantity=body.quantity,
                              reason=body.reason, user_id=u.id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="inventory.supplier_return", entity_type="batch",
               entity_id=body.batch_id, details={"quantity": body.quantity, "reason": body.reason})
    db.commit()
    return {"movement_id": m.id}


@router.post("/inventory/write-offs", status_code=201)
def write_off(body: WriteOffIn, u: User = Depends(MANAGE), db: Session = Depends(get_db)):
    m = mv.write_off(db, pharmacy_id=u.pharmacy_id, batch_id=body.batch_id, quantity=body.quantity,
                     reason=body.reason, user_id=u.id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="inventory.write_off", entity_type="batch",
               entity_id=body.batch_id, details={"quantity": body.quantity, "reason": body.reason})
    db.commit()
    return {"movement_id": m.id}


@router.post("/inventory/adjustments", status_code=201)
def adjustment(body: AdjustIn, u: User = Depends(MANAGE), db: Session = Depends(get_db)):
    m = mv.adjust(db, pharmacy_id=u.pharmacy_id, batch_id=body.batch_id, new_quantity=body.new_quantity,
                  reason=body.reason, user_id=u.id)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="inventory.adjustment", entity_type="batch",
               entity_id=body.batch_id, details={"delta": m.quantity, "reason": body.reason})
    db.commit()
    return {"movement_id": m.id, "delta": m.quantity}


@router.get("/inventory/movements", response_model=Page[MovementOut])
def list_movements(medicine_id: int | None = None, batch_id: int | None = None, movement_type: str | None = None,
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   u: User = Depends(require_permission("inventory:read")), db: Session = Depends(get_db)):
    stmt = select(InventoryMovement).where(InventoryMovement.pharmacy_id == u.pharmacy_id)
    if medicine_id:
        stmt = stmt.where(InventoryMovement.medicine_id == medicine_id)
    if batch_id:
        stmt = stmt.where(InventoryMovement.batch_id == batch_id)
    if movement_type:
        stmt = stmt.where(InventoryMovement.movement_type == movement_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(db.scalars(stmt.order_by(InventoryMovement.id.desc()).limit(limit).offset(offset)))
    return Page(items=rows, total=total, limit=limit, offset=offset)
