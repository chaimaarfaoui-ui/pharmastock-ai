"""Synthetic demonstration data. NOT real pharmacy data.

A seeded day-by-day simulation of a pharmacy: stochastic demand (weekly + yearly seasonality, overdispersion,
slow movers), supplier lead-time variability, an imperfect reorder policy (so stockouts and expiry waste
occur), FEFO dispensing and write-off of expired stock. Everything is written through the same tables the real
application uses, and the pharmacy is flagged data_source='synthetic' so the UI and reports label it.
"""
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import numpy as np
from sqlalchemy import insert
from sqlalchemy.orm import Session
from app.models import (Batch, Delivery, DeliveryItem, InventoryMovement, Medicine, MedicineCategory, Pharmacy,
                        PurchaseOrder, PurchaseOrderItem, Sale, Supplier, SupplierProduct)
from app.services.settings import get_settings_row

# (name, active ingredient, dosage, formulation, category, unit cost)  -- catalogue entries only
CATALOG = [
    ("Paracetamol 500mg", "paracetamol", "500mg", "tablet", "Analgesics", 0.04),
    ("Ibuprofen 400mg", "ibuprofen", "400mg", "tablet", "Analgesics", 0.07),
    ("Aspirin 100mg", "acetylsalicylic acid", "100mg", "tablet", "Analgesics", 0.03),
    ("Amoxicillin 500mg", "amoxicillin", "500mg", "capsule", "Antibiotics", 0.18),
    ("Azithromycin 250mg", "azithromycin", "250mg", "tablet", "Antibiotics", 0.55),
    ("Ciprofloxacin 500mg", "ciprofloxacin", "500mg", "tablet", "Antibiotics", 0.30),
    ("Amlodipine 5mg", "amlodipine", "5mg", "tablet", "Cardiovascular", 0.06),
    ("Lisinopril 10mg", "lisinopril", "10mg", "tablet", "Cardiovascular", 0.08),
    ("Atorvastatin 20mg", "atorvastatin", "20mg", "tablet", "Cardiovascular", 0.12),
    ("Metformin 850mg", "metformin", "850mg", "tablet", "Antidiabetics", 0.05),
    ("Gliclazide 60mg", "gliclazide", "60mg", "tablet", "Antidiabetics", 0.10),
    ("Salbutamol inhaler", "salbutamol", "100mcg", "inhaler", "Respiratory", 2.10),
    ("Cetirizine 10mg", "cetirizine", "10mg", "tablet", "Respiratory", 0.05),
    ("Cough syrup 125ml", "dextromethorphan", "125ml", "syrup", "Respiratory", 1.40),
    ("Omeprazole 20mg", "omeprazole", "20mg", "capsule", "Gastrointestinal", 0.09),
    ("Oral rehydration salts", "electrolytes", "sachet", "powder", "Gastrointestinal", 0.35),
    ("Vitamin D3 1000IU", "cholecalciferol", "1000IU", "tablet", "Supplements", 0.06),
    ("Iron 65mg", "ferrous sulfate", "65mg", "tablet", "Supplements", 0.07),
    ("Hydrocortisone cream 1%", "hydrocortisone", "1%", "cream", "Dermatology", 1.20),
    ("Povidone iodine 10%", "povidone iodine", "10%", "solution", "Dermatology", 0.95),
    ("Loratadine 10mg", "loratadine", "10mg", "tablet", "Respiratory", 0.06),
    ("Levothyroxine 50mcg", "levothyroxine", "50mcg", "tablet", "Endocrine", 0.07),
    ("Diclofenac gel 1%", "diclofenac", "1%", "gel", "Analgesics", 1.60),
    ("Insulin pen", "insulin", "100IU/ml", "pen", "Antidiabetics", 6.50),
]
SEASON = {"Respiratory": (0.55, 20), "Antibiotics": (0.30, 25), "Dermatology": (0.25, 200), "Gastrointestinal": (0.20, 210)}
DOW = np.array([1.05, 1.10, 1.08, 1.05, 1.00, 0.80, 0.45])
DOW = DOW / DOW.mean()
SUPPLIERS = [  # name, quoted lead days, actual lead mean, sd, P(extra delay)
    ("Nordic Pharma Wholesale", 3, 3.2, 0.8, 0.05),
    ("MediDistrib", 5, 6.0, 1.5, 0.20),
    ("Sahara Health Supply", 7, 9.0, 2.5, 0.35),
    ("QuickMeds Distribution", 2, 2.3, 0.6, 0.08),
]


@dataclass
class _Batch:
    local_id: int
    med: int
    number: str
    expiry: date
    received: int
    remaining: int
    cost: float
    supplier: int
    received_day: date
    po_local: int | None = None
    db_id: int | None = None


@dataclass
class _Sim:
    batches: list = field(default_factory=list)
    movements: list = field(default_factory=list)   # (batch_local, med, type, qty, day, hour, reason, ref_type, ref_local)
    sales: list = field(default_factory=list)       # (med, day, units, price)
    pos: dict = field(default_factory=dict)         # local id -> dict
    truth_stockout_days: dict = field(default_factory=dict)


def _dt(d: date, hour: int) -> datetime:
    return datetime.combine(d, time(hour, 0), tzinfo=timezone.utc)


def generate_demo_pharmacy(db: Session, pharmacy_id: int, *, seed: int = 42, days: int = 540, n_medicines: int = 20,
                           today: date | None = None) -> dict:
    today = today or date.today()
    rng = np.random.default_rng(seed)
    pharmacy = db.get(Pharmacy, pharmacy_id)
    pharmacy.data_source = "synthetic"
    get_settings_row(db, pharmacy_id)
    start = today - timedelta(days=days - 1)

    # ---- master data
    cats: dict[str, MedicineCategory] = {}
    for name in sorted({c[4] for c in CATALOG[:n_medicines]}):
        cats[name] = MedicineCategory(pharmacy_id=pharmacy_id, name=name)
        db.add(cats[name])
    sups = []
    for name, quoted, *_ in SUPPLIERS:
        s = Supplier(pharmacy_id=pharmacy_id, name=name, default_lead_time_days=quoted,
                     email=name.split()[0].lower() + "@example.invalid")
        db.add(s); sups.append(s)
    db.flush()

    specs = []
    for i, (name, ai, dose, form, cat, cost) in enumerate(CATALOG[:n_medicines]):
        slow = rng.random() < 0.2
        base = float(rng.uniform(0.5, 2.0)) if slow else float(np.clip(rng.lognormal(math.log(7), 0.8), 2.5, 60))
        aggr = float(rng.uniform(0.8, 1.35))
        shelf = int(rng.integers(100, 170)) if (slow and rng.random() < 0.6) or rng.random() < 0.08 else int(rng.integers(300, 720))
        moq = int(rng.choice([1, 10, 12, 20, 24]))
        sell = round(cost * 1.35 + 0.01, 2)
        med = Medicine(pharmacy_id=pharmacy_id, name=name, active_ingredient=ai, dosage=dose, formulation=form,
                       category_id=cats[cat].id, preferred_supplier_id=sups[i % len(sups)].id,
                       purchase_price=Decimal(str(cost)), selling_price=Decimal(str(sell)), min_stock_threshold=int(base * 5))
        db.add(med)
        specs.append(dict(med=med, base=base, aggr=aggr, shelf=shelf, moq=moq, cat=cat, cost=cost, sell=sell,
                          sup=i % len(sups), trend=float(rng.normal(0, 0.0004))))
    db.flush()
    for sp in specs:
        db.add(SupplierProduct(pharmacy_id=pharmacy_id, supplier_id=sups[sp["sup"]].id, medicine_id=sp["med"].id,
                               unit_price=sp["cost"], min_order_quantity=sp["moq"], lead_time_days=SUPPLIERS[sp["sup"]][1]))

    # ---- simulation
    sim = _Sim()
    next_batch, next_po = [1], [1]
    stock: dict[int, list[_Batch]] = {i: [] for i in range(len(specs))}
    sold_hist: dict[int, list[int]] = {i: [] for i in range(len(specs))}
    incoming: dict[int, list] = {i: [] for i in range(len(specs))}   # (arrive_day_index, qty, po_local)
    pending_po: dict[int, dict] = {}

    def new_batch(mi, qty, day, po_local, supplier):
        sp = specs[mi]
        shelf = int(sp["shelf"] * rng.uniform(0.85, 1.15))
        b = _Batch(next_batch[0], mi, f"{sp['med'].name[:3].upper()}-{day:%y%m}-{next_batch[0]}", day + timedelta(days=shelf),
                   qty, qty, sp["cost"] * float(rng.uniform(0.97, 1.03)), supplier, day, po_local)
        next_batch[0] += 1
        sim.batches.append(b); stock[mi].append(b)
        sim.movements.append((b.local_id, mi, "receipt", qty, day, 9, None, "delivery" if po_local else "manual", po_local))
        return b

    for mi, sp in enumerate(specs):  # opening stock
        new_batch(mi, int(math.ceil(sp["base"] * 30)), start, None, sp["sup"])
        sim.truth_stockout_days[mi] = set()

    for t in range(days):
        day = start + timedelta(days=t)
        # arrivals
        for po_local, po in list(pending_po.items()):
            if po["arrive_idx"] == t:
                for mi, qty in po["lines"]:
                    b = new_batch(mi, qty, day, po_local, po["sup"])
                    po.setdefault("batch_of", {})[mi] = b.local_id
                po["status"] = "completed"
                del pending_po[po_local]
        for mi, sp in enumerate(specs):
            incoming[mi] = [x for x in incoming[mi] if x[0] > t]
            # expire-on-shelf write-offs
            for b in stock[mi]:
                if b.expiry < day and b.remaining > 0:
                    sim.movements.append((b.local_id, mi, "write_off", -b.remaining, day, 8, "expired on shelf (synthetic)", "manual", None))
                    b.remaining = 0
            stock[mi] = [b for b in stock[mi] if b.remaining > 0]
            # demand
            season = 1.0
            if sp["cat"] in SEASON:
                amp, peak = SEASON[sp["cat"]]
                season = 1 + amp * math.cos(2 * math.pi * (day.timetuple().tm_yday - peak) / 365)
            lam = sp["base"] * (1 + sp["trend"] * t) * DOW[day.weekday()] * season
            demand = int(rng.poisson(rng.gamma(8, max(lam, 1e-6) / 8)))
            sold = 0
            for b in sorted(stock[mi], key=lambda x: (x.expiry, x.local_id)):
                if demand == 0:
                    break
                if b.expiry < day:
                    continue
                take = min(demand, b.remaining)
                b.remaining -= take; demand -= take; sold += take
                sim.movements.append((b.local_id, mi, "sale", -take, day, 12, None, "sale", None))
            if demand > 0:
                sim.truth_stockout_days[mi].add(day)
            if sold > 0:
                sim.sales.append((mi, day, sold, sp["sell"]))
            sold_hist[mi].append(sold)
        # weekly review (staggered) -> one PO per supplier
        if t % 7 == 3:
            orders: dict[int, list] = {}
            for mi, sp in enumerate(specs):
                avg = float(np.mean(sold_hist[mi][-28:])) if sold_hist[mi] else sp["base"]
                quoted = SUPPLIERS[sp["sup"]][1]
                usable = sum(b.remaining for b in stock[mi] if b.expiry >= day)
                position = usable + sum(q for _, q, _ in incoming[mi])
                rop = sp["aggr"] * avg * (quoted + 8)
                if position < rop:
                    target = sp["aggr"] * avg * (quoted + 14 + 10)
                    qty = max(sp["moq"], int(math.ceil((target - position) / sp["moq"]) * sp["moq"]))
                    orders.setdefault(sp["sup"], []).append((mi, qty))
            for si, lines in orders.items():
                _, quoted, mean, sd, p_delay = SUPPLIERS[si]
                actual = max(1, int(round(rng.normal(mean, sd)))) + (int(rng.integers(2, 6)) if rng.random() < p_delay else 0)
                pid = next_po[0]; next_po[0] += 1
                po = dict(sup=si, lines=lines, order_day=day, expected=day + timedelta(days=quoted), arrive_idx=t + actual,
                          arrive_day=day + timedelta(days=actual), status="ordered")
                sim.pos[pid] = po
                if po["arrive_idx"] < days:
                    pending_po[pid] = po
                else:
                    pending_po[pid] = po  # still in transit at the end of the simulated window
                for mi, qty in lines:
                    incoming[mi].append((t + actual, qty, pid))

    # ---- persist
    po_db: dict[int, PurchaseOrder] = {}
    for pid, po in sim.pos.items():
        order = PurchaseOrder(pharmacy_id=pharmacy_id, supplier_id=sups[po["sup"]].id,
                              status="completed" if po["status"] == "completed" else "ordered",
                              expected_delivery_date=po["expected"], ordered_at=_dt(po["order_day"], 10), notes="synthetic")
        for mi, qty in po["lines"]:
            order.items.append(PurchaseOrderItem(medicine_id=specs[mi]["med"].id, quantity_ordered=qty,
                                                 quantity_received=qty if po["status"] == "completed" else 0,
                                                 unit_price=Decimal(str(specs[mi]["cost"]))))
        db.add(order); po_db[pid] = order
    db.flush()
    for b in sim.batches:
        row = Batch(pharmacy_id=pharmacy_id, medicine_id=specs[b.med]["med"].id, supplier_id=sups[b.supplier].id,
                    batch_number=b.number, expiration_date=b.expiry, quantity_received=b.received,
                    quantity_remaining=b.remaining, unit_cost=Decimal(str(round(b.cost, 2))), received_date=b.received_day)
        db.add(row); b.db_id = row  # temp: holds ORM object until flushed
    db.flush()
    for b in sim.batches:
        b.db_id = b.db_id.id
    deliveries: dict[int, Delivery] = {}
    for pid, po in sim.pos.items():
        if po["status"] == "completed":
            d = Delivery(pharmacy_id=pharmacy_id, purchase_order_id=po_db[pid].id, received_at=_dt(po["arrive_day"], 9), notes="synthetic")
            db.add(d); deliveries[pid] = d
    db.flush()
    batch_by_local = {b.local_id: b for b in sim.batches}
    item_by = {(pid, it.medicine_id): it for pid, o in po_db.items() for it in o.items}
    for pid, po in sim.pos.items():
        if po["status"] == "completed":
            for mi, qty in po["lines"]:
                b = batch_by_local[po["batch_of"][mi]]
                db.add(DeliveryItem(delivery_id=deliveries[pid].id, po_item_id=item_by[(pid, specs[mi]["med"].id)].id,
                                    batch_id=b.db_id, quantity=qty))
    db.flush()
    db.execute(insert(InventoryMovement), [
        dict(pharmacy_id=pharmacy_id, batch_id=batch_by_local[bl].db_id, medicine_id=specs[mi]["med"].id, movement_type=mt,
             quantity=q, reason=reason, reference_type=rt,
             reference_id=(deliveries[rl].id if rt == "delivery" and rl in deliveries else None), occurred_at=_dt(d, h))
        for bl, mi, mt, q, d, h, reason, rt, rl in sim.movements])
    db.execute(insert(Sale), [
        dict(pharmacy_id=pharmacy_id, medicine_id=specs[mi]["med"].id, quantity=u, unit_price=Decimal(str(p)), sold_at=_dt(d, 12))
        for mi, d, u, p in sim.sales])
    db.flush()
    return {"medicines": len(specs), "suppliers": len(sups), "batches": len(sim.batches), "movements": len(sim.movements),
            "sales_rows": len(sim.sales), "purchase_orders": len(sim.pos), "start": str(start), "end": str(today), "seed": seed,
            "truth_stockout_days": {specs[mi]["med"].id: sorted(ds) for mi, ds in sim.truth_stockout_days.items()}}
