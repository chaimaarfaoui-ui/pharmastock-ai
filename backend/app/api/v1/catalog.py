"""Categories, suppliers, medicines, batches (read)."""
from datetime import date, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.api.deps import require_permission
from app.api.helpers import check_fk_owned, get_owned
from app.core.db import get_db
from app.models import Batch, Medicine, MedicineCategory, Supplier, User
from app.schemas.common import Page
from app.schemas.inventory import (BatchOut, CategoryIn, CategoryOut, MedicineIn, MedicineOut, MedicinePatch,
                                   SupplierIn, SupplierOut, SupplierPatch)
from app.services.audit import log_action

router = APIRouter(tags=["catalog"])
READ = require_permission("inventory:read")
WRITE = require_permission("inventory:write")


def _conflict(msg: str):
    return HTTPException(status.HTTP_409_CONFLICT, msg)


# ---- categories
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(u: User = Depends(READ), db: Session = Depends(get_db)):
    return list(db.scalars(select(MedicineCategory).where(MedicineCategory.pharmacy_id == u.pharmacy_id)
                           .order_by(MedicineCategory.name)))


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, u: User = Depends(WRITE), db: Session = Depends(get_db)):
    c = MedicineCategory(pharmacy_id=u.pharmacy_id, name=body.name.strip())
    db.add(c)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflict("Category already exists")
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="category.created", entity_type="category", entity_id=c.id)
    db.commit()
    return c


# ---- suppliers
@router.get("/suppliers", response_model=Page[SupplierOut])
def list_suppliers(q: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   u: User = Depends(READ), db: Session = Depends(get_db)):
    stmt = select(Supplier).where(Supplier.pharmacy_id == u.pharmacy_id)
    if q:
        stmt = stmt.where(Supplier.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = list(db.scalars(stmt.order_by(Supplier.name).limit(limit).offset(offset)))
    return Page(items=rows, total=total, limit=limit, offset=offset)


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, u: User = Depends(WRITE), db: Session = Depends(get_db)):
    s = Supplier(pharmacy_id=u.pharmacy_id, **body.model_dump())
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflict("A supplier with this name already exists")
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="supplier.created", entity_type="supplier", entity_id=s.id)
    db.commit()
    return s


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, body: SupplierPatch, u: User = Depends(WRITE), db: Session = Depends(get_db)):
    s = get_owned(db, Supplier, supplier_id, u.pharmacy_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(s, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _conflict("A supplier with this name already exists")
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="supplier.updated", entity_type="supplier",
               entity_id=s.id, details={"fields": list(changes)})
    db.commit()
    return s


# ---- medicines
def _stock_subquery(pharmacy_id: int, today: date):
    return (select(Batch.medicine_id.label("mid"),
                   func.coalesce(func.sum(Batch.quantity_remaining), 0).label("total"),
                   func.coalesce(func.sum(case((Batch.expiration_date >= today, Batch.quantity_remaining), else_=0)), 0).label("available"))
            .where(Batch.pharmacy_id == pharmacy_id).group_by(Batch.medicine_id).subquery())


def _med_out(m: Medicine, total: int, available: int) -> MedicineOut:
    out = MedicineOut.model_validate(m)
    out.category_name = m.category.name if m.category else None
    out.total_stock, out.available_stock = int(total), int(available)
    out.below_threshold = int(available) < m.min_stock_threshold
    return out


@router.get("/medicines", response_model=Page[MedicineOut])
def list_medicines(q: str | None = None, category_id: int | None = None, low_stock: bool = False,
                   include_inactive: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                   u: User = Depends(READ), db: Session = Depends(get_db)):
    st = _stock_subquery(u.pharmacy_id, date.today())
    avail = func.coalesce(st.c.available, 0)
    stmt = (select(Medicine, func.coalesce(st.c.total, 0), avail)
            .outerjoin(st, st.c.mid == Medicine.id).where(Medicine.pharmacy_id == u.pharmacy_id))
    if not include_inactive:
        stmt = stmt.where(Medicine.is_active.is_(True))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Medicine.name.ilike(like), Medicine.brand.ilike(like), Medicine.active_ingredient.ilike(like)))
    if category_id:
        stmt = stmt.where(Medicine.category_id == category_id)
    if low_stock:
        stmt = stmt.where(avail < Medicine.min_stock_threshold)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Medicine.name, Medicine.id).limit(limit).offset(offset)).all()
    return Page(items=[_med_out(m, t, a) for m, t, a in rows], total=total, limit=limit, offset=offset)


def _validate_med_refs(db, u, category_id, supplier_id):
    check_fk_owned(db, MedicineCategory, category_id, u.pharmacy_id, "category")
    check_fk_owned(db, Supplier, supplier_id, u.pharmacy_id, "supplier")


@router.post("/medicines", response_model=MedicineOut, status_code=201)
def create_medicine(body: MedicineIn, u: User = Depends(WRITE), db: Session = Depends(get_db)):
    _validate_med_refs(db, u, body.category_id, body.preferred_supplier_id)
    m = Medicine(pharmacy_id=u.pharmacy_id, **body.model_dump())
    db.add(m)
    db.flush()
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="medicine.created", entity_type="medicine", entity_id=m.id)
    db.commit()
    db.refresh(m)
    return _med_out(m, 0, 0)


def _one_with_stock(db, u, medicine_id) -> MedicineOut:
    m = get_owned(db, Medicine, medicine_id, u.pharmacy_id)
    st = _stock_subquery(u.pharmacy_id, date.today())
    row = db.execute(select(func.coalesce(st.c.total, 0), func.coalesce(st.c.available, 0))
                     .select_from(Medicine).outerjoin(st, st.c.mid == Medicine.id).where(Medicine.id == m.id)).one()
    return _med_out(m, row[0], row[1])


@router.get("/medicines/{medicine_id}", response_model=MedicineOut)
def get_medicine(medicine_id: int, u: User = Depends(READ), db: Session = Depends(get_db)):
    return _one_with_stock(db, u, medicine_id)


@router.patch("/medicines/{medicine_id}", response_model=MedicineOut)
def update_medicine(medicine_id: int, body: MedicinePatch, u: User = Depends(WRITE), db: Session = Depends(get_db)):
    m = get_owned(db, Medicine, medicine_id, u.pharmacy_id)
    changes = body.model_dump(exclude_unset=True)
    _validate_med_refs(db, u, changes.get("category_id"), changes.get("preferred_supplier_id"))
    for k, v in changes.items():
        setattr(m, k, v)
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="medicine.updated", entity_type="medicine",
               entity_id=m.id, details={"fields": list(changes)})
    db.commit()
    return _one_with_stock(db, u, medicine_id)


# ---- batches (read-only; created via receipts / deliveries so the ledger stays consistent)
@router.get("/batches", response_model=Page[BatchOut])
def list_batches(medicine_id: int | None = None, expiring_within_days: int | None = Query(None, ge=0, le=3650),
                 include_empty: bool = False, include_expired: bool = True,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 u: User = Depends(READ), db: Session = Depends(get_db)):
    today = date.today()
    stmt = select(Batch, Medicine.name).join(Medicine, Medicine.id == Batch.medicine_id).where(Batch.pharmacy_id == u.pharmacy_id)
    if medicine_id:
        stmt = stmt.where(Batch.medicine_id == medicine_id)
    if not include_empty:
        stmt = stmt.where(Batch.quantity_remaining > 0)
    if not include_expired:
        stmt = stmt.where(Batch.expiration_date >= today)
    if expiring_within_days is not None:
        stmt = stmt.where(Batch.expiration_date <= today + timedelta(days=expiring_within_days))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(Batch.expiration_date, Batch.id).limit(limit).offset(offset)).all()
    items = []
    for b, name in rows:
        items.append(BatchOut(id=b.id, medicine_id=b.medicine_id, medicine_name=name, supplier_id=b.supplier_id,
                              batch_number=b.batch_number, expiration_date=b.expiration_date,
                              quantity_received=b.quantity_received, quantity_remaining=b.quantity_remaining,
                              unit_cost=b.unit_cost, received_date=b.received_date,
                              days_to_expiry=(b.expiration_date - today).days, is_expired=b.expiration_date < today,
                              remaining_value=(Decimal(b.quantity_remaining) * b.unit_cost).quantize(Decimal("0.01"))))
    return Page(items=items, total=total, limit=limit, offset=offset)


# ---- supplier terms per medicine (price, minimum order quantity, lead time) used by reorder recommendations
from pydantic import BaseModel as _BM, Field as _F
from app.models import SupplierProduct


class SupplierProductIn(_BM):
    supplier_id: int
    medicine_id: int
    unit_price: float = _F(ge=0, le=1_000_000)
    min_order_quantity: int = _F(default=1, ge=1, le=1_000_000)
    lead_time_days: int | None = _F(default=None, ge=1, le=365)


@router.get("/supplier-products")
def list_supplier_products(medicine_id: int | None = None, supplier_id: int | None = None, u: User = Depends(READ), db: Session = Depends(get_db)):
    stmt = select(SupplierProduct).where(SupplierProduct.pharmacy_id == u.pharmacy_id)
    if medicine_id:
        stmt = stmt.where(SupplierProduct.medicine_id == medicine_id)
    if supplier_id:
        stmt = stmt.where(SupplierProduct.supplier_id == supplier_id)
    return {"items": [{"id": s.id, "supplier_id": s.supplier_id, "medicine_id": s.medicine_id, "unit_price": s.unit_price,
                       "min_order_quantity": s.min_order_quantity, "lead_time_days": s.lead_time_days} for s in db.scalars(stmt)]}


@router.put("/supplier-products")
def upsert_supplier_product(body: SupplierProductIn, u: User = Depends(WRITE), db: Session = Depends(get_db)):
    check_fk_owned(db, Supplier, body.supplier_id, u.pharmacy_id, "supplier")
    check_fk_owned(db, Medicine, body.medicine_id, u.pharmacy_id, "medicine")
    sp = db.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == body.supplier_id, SupplierProduct.medicine_id == body.medicine_id))
    if sp is None:
        sp = SupplierProduct(pharmacy_id=u.pharmacy_id, supplier_id=body.supplier_id, medicine_id=body.medicine_id,
                             unit_price=body.unit_price, min_order_quantity=body.min_order_quantity, lead_time_days=body.lead_time_days)
        db.add(sp)
    else:
        sp.unit_price, sp.min_order_quantity, sp.lead_time_days = body.unit_price, body.min_order_quantity, body.lead_time_days
    log_action(db, pharmacy_id=u.pharmacy_id, user_id=u.id, action="supplier_product.upserted", details=body.model_dump())
    db.commit()
    return {"id": sp.id}
