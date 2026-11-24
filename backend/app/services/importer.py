"""Validated CSV import for medicines, stock receipts and sales history.

Safety rules: size/row limits, text-only content, strict headers, per-row validation with row numbers, ownership checks,
duplicate detection, and ALL-OR-NOTHING commit (one bad row means nothing is imported). A dry run applies the file inside the
transaction and rolls it back, so what the check reports is exactly what the import would do.
Never import data that identifies patients: this tool needs only product, date and quantity."""
import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models import InventoryMovement, Medicine, MedicineCategory, Sale, Supplier
from app.services import movements as mv

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_ERRORS = 100
MAX_TEXT = 200

SPECS = {
    "medicines": {"required": ["name"], "optional": ["brand", "active_ingredient", "dosage", "formulation", "category", "purchase_price", "selling_price", "min_stock_threshold"]},
    "receipts": {"required": ["medicine", "batch_number", "expiration_date", "quantity", "unit_cost"], "optional": ["received_date", "supplier"]},
    "sales": {"required": ["date", "medicine", "quantity"], "optional": ["unit_price", "type"]},
}


class ImportRejected(Exception):
    """The whole file is unusable (wrong type, too big, bad header, ...)."""


@dataclass
class ImportResult:
    kind: str
    rows: int = 0
    errors: list = field(default_factory=list)
    error_count: int = 0
    warnings: list = field(default_factory=list)
    created: dict = field(default_factory=dict)
    preview: list = field(default_factory=list)

    def err(self, row: int, column: str | None, msg: str):
        self.error_count += 1
        if len(self.errors) < MAX_ERRORS:
            self.errors.append({"row": row, "column": column, "message": msg})


def parse_csv(raw: bytes, kind: str) -> tuple[list[tuple[int, dict]], list[str]]:
    if len(raw) > MAX_BYTES:
        raise ImportRejected(f"File is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if not raw.strip():
        raise ImportRejected("File is empty")
    if b"\x00" in raw:
        raise ImportRejected("File is not a text CSV file")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportRejected("File must be UTF-8 text (in Excel: Save As, CSV UTF-8)")
    first = text.splitlines()[0]
    delim = ";" if first.count(";") > first.count(",") else ","      # French/Tunisian Excel exports use semicolons
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = [h.strip().lower().replace(" ", "_") for h in next(reader)]
    except StopIteration:
        raise ImportRejected("File has no header row")
    spec = SPECS[kind]
    missing = [c for c in spec["required"] if c not in header]
    if missing:
        raise ImportRejected(f"Missing required column(s): {', '.join(missing)}. Expected: {', '.join(spec['required'] + spec['optional'])}")
    if len(set(header)) != len(header):
        raise ImportRejected("Duplicate column names in the header")
    ignored = [h for h in header if h and h not in spec["required"] + spec["optional"]]
    rows = []
    try:
        for i, rec in enumerate(reader, start=2):
            if not any(c.strip() for c in rec):
                continue
            if len(rows) >= MAX_ROWS:
                raise ImportRejected(f"More than {MAX_ROWS} rows: split the file")
            values = {h: (rec[j].strip() if j < len(rec) else "") for j, h in enumerate(header)}
            if any(c.strip() for c in rec[len(header):]):
                values["_extra_cells"] = True        # more cells than header columns: usually a decimal comma in a comma file
            rows.append((i, values))
    except csv.Error as e:
        raise ImportRejected(f"Malformed CSV: {e}")
    if not rows:
        raise ImportRejected("File has a header but no data rows")
    return rows, ([f"Ignored unknown column(s): {', '.join(ignored)}"] if ignored else [])


def _text(res, row, col, v, required=False):
    if not v:
        if required:
            res.err(row, col, "required")
        return None
    if len(v) > MAX_TEXT:
        res.err(row, col, f"longer than {MAX_TEXT} characters")
        return None
    return v


def _dec(res, row, col, v, default=None, maximum=Decimal("1000000")):
    if v == "":
        return default
    try:
        d = Decimal(v.replace(",", "."))            # accept 1,50 as well as 1.50
    except InvalidOperation:
        res.err(row, col, f"'{v}' is not a number")
        return None
    if d < 0 or d > maximum:
        res.err(row, col, f"must be between 0 and {maximum}")
        return None
    return d


def _int(res, row, col, v, minimum=0, maximum=10_000_000, default=None):
    if v == "":
        if default is None:
            res.err(row, col, "required")
        return default
    try:
        n = int(Decimal(v.replace(",", ".")))
        if Decimal(v.replace(",", ".")) != n:
            raise ValueError
    except (InvalidOperation, ValueError):
        res.err(row, col, f"'{v}' is not a whole number")
        return None
    if n < minimum or n > maximum:
        res.err(row, col, f"must be between {minimum} and {maximum}")
        return None
    return n


def _date(res, row, col, v, default=None, allow_future=False):
    if v == "":
        if default is None:
            res.err(row, col, "required (YYYY-MM-DD)")
        return default
    try:
        d = date.fromisoformat(v)
    except ValueError:
        res.err(row, col, f"'{v}' is not a date in YYYY-MM-DD format")
        return None
    if not allow_future and d > date.today():
        res.err(row, col, "date is in the future")
        return None
    return d


def _at(d: date, hour: int) -> datetime:
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


def _find_medicine(res, row, col, name, by_name):
    hits = by_name.get(name.lower(), [])
    if not hits:
        res.err(row, col, f"unknown medicine '{name}' (import the medicines file first; names must match exactly)")
        return None
    if len(hits) > 1:
        res.err(row, col, f"'{name}' matches {len(hits)} medicines; make names unique before importing")
        return None
    return hits[0]


def run_import(db: Session, pharmacy_id: int, user_id: int | None, kind: str, rows: list[tuple[int, dict]], warnings: list[str]) -> ImportResult:
    """Applies rows inside the caller's transaction. The caller commits only when error_count == 0 and not a dry run."""
    res = ImportResult(kind=kind, rows=len(rows), warnings=warnings, preview=[{k: v for k, v in r.items() if k != "_extra_cells"} for _, r in rows[:5]])
    for n, r in rows:
        if r.get("_extra_cells"):
            res.err(n, None, "row has more cells than the header has columns. If a number uses a decimal comma (0,06) in a comma-separated file, "
                             "save the file with semicolons as the separator or use a decimal point (0.06)")
    meds = list(db.scalars(select(Medicine).where(Medicine.pharmacy_id == pharmacy_id)))
    by_name: dict[str, list[Medicine]] = {}
    for m in meds:
        by_name.setdefault(m.name.lower(), []).append(m)
    if kind == "medicines":
        _import_medicines(db, pharmacy_id, rows, meds, res)
    elif kind == "receipts":
        _import_receipts(db, pharmacy_id, user_id, rows, by_name, res)
    else:
        _import_sales(db, pharmacy_id, user_id, rows, by_name, res)
    return res


def _import_medicines(db, pid, rows, existing, res):
    seen = {(m.name.lower(), (m.dosage or "").lower(), (m.formulation or "").lower()) for m in existing}
    cats = {c.name.lower(): c for c in db.scalars(select(MedicineCategory).where(MedicineCategory.pharmacy_id == pid))}
    made = made_cats = 0
    for n, r in rows:
        before = res.error_count
        name = _text(res, n, "name", r.get("name", ""), required=True)
        brand, ai = _text(res, n, "brand", r.get("brand", "")), _text(res, n, "active_ingredient", r.get("active_ingredient", ""))
        dosage, form = _text(res, n, "dosage", r.get("dosage", "")), _text(res, n, "formulation", r.get("formulation", ""))
        cat = _text(res, n, "category", r.get("category", ""))
        buy = _dec(res, n, "purchase_price", r.get("purchase_price", ""), Decimal("0"))
        sell = _dec(res, n, "selling_price", r.get("selling_price", ""), None)
        mn = _int(res, n, "min_stock_threshold", r.get("min_stock_threshold", ""), default=0)
        if name:
            key = (name.lower(), (dosage or "").lower(), (form or "").lower())
            if key in seen:
                res.err(n, "name", f"'{name}' with this dosage/formulation already exists (in the file or the catalogue)")
            seen.add(key)
        if res.error_count > before:
            continue
        c = None
        if cat:
            c = cats.get(cat.lower())
            if c is None:
                c = MedicineCategory(pharmacy_id=pid, name=cat); db.add(c); db.flush(); cats[cat.lower()] = c; made_cats += 1
        db.add(Medicine(pharmacy_id=pid, name=name, brand=brand, active_ingredient=ai, dosage=dosage, formulation=form,
                        category_id=c.id if c else None, purchase_price=buy, selling_price=sell, min_stock_threshold=mn))
        made += 1
    res.created = {"medicines": made, "categories": made_cats}


def _import_receipts(db, pid, user_id, rows, by_name, res):
    sups = {s.name.lower(): s for s in db.scalars(select(Supplier).where(Supplier.pharmacy_id == pid))}
    from app.models import Batch
    seen = {(b.medicine_id, b.batch_number.lower()) for b in db.scalars(select(Batch).where(Batch.pharmacy_id == pid))}
    made = 0
    for n, r in rows:
        before = res.error_count
        med = _find_medicine(res, n, "medicine", r.get("medicine", ""), by_name) if r.get("medicine") else (res.err(n, "medicine", "required") or None)
        number = _text(res, n, "batch_number", r.get("batch_number", ""), required=True)
        exp = _date(res, n, "expiration_date", r.get("expiration_date", ""), allow_future=True)
        qty = _int(res, n, "quantity", r.get("quantity", ""), minimum=1)
        cost = _dec(res, n, "unit_cost", r.get("unit_cost", ""), None)
        if r.get("unit_cost", "") == "":
            res.err(n, "unit_cost", "required")
        rec = _date(res, n, "received_date", r.get("received_date", ""), default=date.today())
        sup = None
        if r.get("supplier"):
            sup = sups.get(r["supplier"].lower())
            if sup is None:
                res.err(n, "supplier", f"unknown supplier '{r['supplier']}'")
        if med and number:
            if (med.id, number.lower()) in seen:
                res.err(n, "batch_number", f"batch '{number}' already exists for this medicine")
            seen.add((med.id, number.lower()))
        if res.error_count > before or not (med and number and exp and qty and cost is not None and rec):
            continue
        try:
            mv.receive_batch(db, pharmacy_id=pid, medicine_id=med.id, batch_number=number, expiration_date=exp, quantity=qty,
                             unit_cost=cost, supplier_id=sup.id if sup else None, received_date=rec, user_id=user_id,
                             ref_type="import", today=rec, occurred_at=_at(rec, 9))
            made += 1
        except mv.InventoryError as e:
            res.err(n, "expiration_date" if e.code == "expired_batch" else None, e.message)
    res.created = {"batches": made}


def _import_sales(db, pid, user_id, rows, by_name, res):
    last_live = {mid: d for mid, d in db.execute(
        select(InventoryMovement.medicine_id, func.max(InventoryMovement.occurred_at)).where(
            InventoryMovement.pharmacy_id == pid, InventoryMovement.movement_type.in_(("sale", "dispense"))).group_by(InventoryMovement.medicine_id))}
    parsed = []
    for n, r in rows:
        before = res.error_count
        d = _date(res, n, "date", r.get("date", ""))
        med = _find_medicine(res, n, "medicine", r.get("medicine", ""), by_name) if r.get("medicine") else (res.err(n, "medicine", "required") or None)
        qty = _int(res, n, "quantity", r.get("quantity", ""), minimum=1, maximum=1_000_000)
        price = _dec(res, n, "unit_price", r.get("unit_price", ""), None)
        kind = (r.get("type") or "sale").lower()
        if kind not in ("sale", "dispense"):
            res.err(n, "type", "must be 'sale' or 'dispense'")
        if med and d and med.id in last_live and last_live[med.id].date() >= d:
            res.err(n, "date", f"sales on or after {d} already exist for '{med.name}'; import history before recording live sales")
        if res.error_count == before and med and d and qty:
            parsed.append((d, n, med, qty, price, kind))
    made = 0
    for d, n, med, qty, price, kind in sorted(parsed, key=lambda x: (x[0], x[1])):     # chronological, so FEFO sees the stock of that day
        sale = Sale(pharmacy_id=pid, medicine_id=med.id, quantity=qty, unit_price=price, sold_at=_at(d, 12), user_id=user_id)
        db.add(sale); db.flush()
        try:
            mv.allocate_fefo(db, pharmacy_id=pid, medicine_id=med.id, quantity=qty, movement_type=kind, user_id=user_id,
                             ref_type="sale", ref_id=sale.id, today=d, occurred_at=_at(d, 12))
            made += 1
        except mv.InsufficientStock as e:
            res.err(n, "quantity", f"only {e.available} usable units of '{med.name}' on {d}; import stock receipts dated on or before that day first")
        except mv.InventoryError as e:
            res.err(n, None, e.message)
    res.created = {"sales": made}
