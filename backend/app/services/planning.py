"""Deterministic inventory mathematics. ML enters ONLY through the demand input (forecast or trailing mean);
everything below it -- FEFO simulation, safety stock, reorder point, order-up-to level -- is plain formulas, and every
result carries the inputs used so the UI can show the calculation.

Formulas (z = normal quantile of the configured service level, L = lead time days, R = review period days):
  safety_stock   SS  = z * sigma_d * sqrt(L)
  reorder_point  ROP = demand over L + SS
  order_up_to    S   = demand over (L+R) + z * sigma_d * sqrt(L+R)
  position           = usable stock + open orders - projected expiry waste within (L+R)
  order quantity     = ceil((S - position) / MOQ) * MOQ
"""
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import NormalDist, median
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.ml.demand import build_daily_series
from app.models import (Batch, Delivery, ExpirationAlert, Forecast, Medicine, ModelEvaluation, PurchaseOrder,
                        PurchaseOrderItem, ReorderRecommendation, ShortageAlert, Supplier, SupplierProduct)
from app.services.notifications import notify
from app.services.settings import get_settings_row, z_value

FAR_FUTURE = date(9999, 12, 31)


# ------------------------------------------------------------------ demand input
@dataclass
class DemandProfile:
    daily: list[float]
    sigma_daily: float
    source: str
    has_history: bool


def demand_profile(db: Session, pharmacy_id: int, medicine_id: int, today: date, n_days: int) -> DemandProfile:
    rows = list(db.scalars(select(Forecast).where(Forecast.pharmacy_id == pharmacy_id, Forecast.medicine_id == medicine_id,
                                                  Forecast.target_date > today).order_by(Forecast.target_date)))
    if rows and (today - rows[0].generated_at.date()).days <= 14 and rows[0].target_date <= today + timedelta(days=2):
        by_day = {r.target_date: r.yhat for r in rows}
        tail = float(np.mean([r.yhat for r in rows[-14:]]))
        daily = [by_day.get(today + timedelta(days=i + 1), tail) for i in range(n_days)]
        ev = db.scalar(select(ModelEvaluation).where(ModelEvaluation.pharmacy_id == pharmacy_id, ModelEvaluation.medicine_id == medicine_id,
                                                     ModelEvaluation.is_selected.is_(True)).order_by(ModelEvaluation.id.desc()))
        sigma = (ev.details or {}).get("residual_sigma") if ev else None
        if sigma is None:
            sigma = float(np.mean([(r.upper - r.lower) / 2.56 for r in rows]))
        return DemandProfile(daily, float(sigma), f"forecast:{rows[0].model_name}", True)
    df = build_daily_series(db, pharmacy_id, medicine_id, today)
    ok = df[~df["censored"]]["units"] if len(df) else df["units"]
    if len(ok) < 14 or float(df["units"].sum() if len(df) else 0) == 0:
        return DemandProfile([0.0] * n_days, 0.0, "no_history", False)
    recent = ok[-56:]
    return DemandProfile([float(recent.mean())] * n_days, float(recent.std(ddof=0)), "trailing_mean_56d(uncensored)", True)


def lead_time_for(db: Session, pharmacy_id: int, med: Medicine, cfg) -> tuple[int, str, int | None]:
    sid = med.preferred_supplier_id
    if sid:
        pairs = db.execute(select(PurchaseOrder.ordered_at, Delivery.received_at).join(Delivery, Delivery.purchase_order_id == PurchaseOrder.id)
                           .where(PurchaseOrder.pharmacy_id == pharmacy_id, PurchaseOrder.supplier_id == sid,
                                  PurchaseOrder.ordered_at.is_not(None))).all()
        days = [(r.date() - o.date()).days for o, r in pairs]
        if len(days) >= 3:
            return max(1, math.ceil(float(np.mean(days)))), f"measured mean of {len(days)} deliveries", sid
        sp = db.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == sid, SupplierProduct.medicine_id == med.id))
        if sp and sp.lead_time_days:
            return sp.lead_time_days, "supplier_product", sid
        sup = db.get(Supplier, sid)
        if sup and sup.default_lead_time_days:
            return sup.default_lead_time_days, "supplier_default", sid
    return cfg.default_lead_time_days, "pharmacy_default", sid


def open_incoming(db: Session, pharmacy_id: int, medicine_id: int, today: date, lead: int,
                  statuses=("ordered", "partially_received")) -> list[dict]:
    rows = db.execute(select(PurchaseOrder, PurchaseOrderItem).join(PurchaseOrderItem, PurchaseOrderItem.purchase_order_id == PurchaseOrder.id)
                      .where(PurchaseOrder.pharmacy_id == pharmacy_id, PurchaseOrder.status.in_(statuses),
                             PurchaseOrderItem.medicine_id == medicine_id)).all()
    out = []
    for po, it in rows:
        rem = it.quantity_ordered - it.quantity_received
        if rem <= 0:
            continue
        arr = po.expected_delivery_date or ((po.ordered_at.date() if po.ordered_at else today) + timedelta(days=lead))
        overdue = arr <= today
        if overdue:      # late and unreliable: assume a full lead time from now rather than optimistic immediate arrival
            arr = today + timedelta(days=lead)
        out.append({"po_id": po.id, "quantity": rem, "arrival": arr, "overdue": overdue, "status": po.status})
    return out


# ------------------------------------------------------------------ FEFO simulator (pure)
@dataclass
class SimResult:
    closing: list[float]
    unmet: list[float]
    expired: dict[int, float]
    first_stockout: int | None


def simulate_fefo(batches: list[tuple[int, date, float]], demand: list[float], arrivals: list[tuple[date, float]], start: date) -> SimResult:
    """Day-by-day: add arrivals, drop expired (record leftover), serve demand first-expired-first-out."""
    live = [[bid, exp, float(q)] for bid, exp, q in batches if q > 0]
    arr = sorted(arrivals)
    ai, expired = 0, {}
    closing, unmet, first = [], [], None
    for t, d_ in enumerate(demand):
        day = start + timedelta(days=t)
        while ai < len(arr) and arr[ai][0] <= day:
            live.append([-(ai + 1), FAR_FUTURE, float(arr[ai][1])]); ai += 1
        for b in [b for b in live if b[1] < day]:
            if b[0] >= 0:
                expired[b[0]] = expired.get(b[0], 0.0) + b[2]
            live.remove(b)
        need = float(d_)
        for b in sorted(live, key=lambda x: (x[1], x[0])):
            take = min(need, b[2]); b[2] -= take; need -= take
            if need <= 1e-9:
                break
        live = [b for b in live if b[2] > 1e-9]
        closing.append(sum(b[2] for b in live)); unmet.append(max(need, 0.0))
        if need > 1e-6 and first is None:
            first = t
    return SimResult(closing, unmet, expired, first)


def _batches(db: Session, pharmacy_id: int, medicine_id: int, today: date, usable_only=True):
    stmt = select(Batch).where(Batch.pharmacy_id == pharmacy_id, Batch.medicine_id == medicine_id, Batch.quantity_remaining > 0)
    if usable_only:
        stmt = stmt.where(Batch.expiration_date >= today)
    return list(db.scalars(stmt))


# ------------------------------------------------------------------ shortage risk
def assess_shortage(db: Session, pharmacy_id: int, med: Medicine, cfg, today: date, *, demand_multiplier: float = 1.0,
                    lead_override: int | None = None, extra_order: tuple[int, int] | None = None) -> dict:
    """Returns the full calculation. `extra_order=(qty, arrives_in_days)` and the overrides power the what-if simulator."""
    z = z_value(cfg.service_level)
    lead, lead_src, sid = lead_time_for(db, pharmacy_id, med, cfg)
    if lead_override is not None:
        lead, lead_src = lead_override, "simulation override"
    W = max(lead, 1)
    prof = demand_profile(db, pharmacy_id, med.id, today, W)
    mean_daily = [d * demand_multiplier for d in prof.daily]
    sigma = prof.sigma_daily * demand_multiplier
    start = today + timedelta(days=1)
    batches = [(b.id, b.expiration_date, b.quantity_remaining) for b in _batches(db, pharmacy_id, med.id, today)]
    inc = open_incoming(db, pharmacy_id, med.id, today, lead)
    arrivals = [(i["arrival"], i["quantity"]) for i in inc]
    if extra_order:
        arrivals.append((today + timedelta(days=extra_order[1]), extra_order[0]))
    point = simulate_fefo(batches, mean_daily, arrivals, start)
    stress_d = [mean_daily[t] + z * sigma * (math.sqrt(t + 1) - math.sqrt(t)) for t in range(W)]
    stress = simulate_fefo(batches, stress_d, arrivals, start)
    available = sum(q for _, _, q in batches)
    mu_L, ss = sum(mean_daily), z * sigma * math.sqrt(W)
    rop = mu_L + ss
    min_stock = min(point.closing) if point.closing else float(available)
    mean_rate = (mu_L / W) if W else 0.0
    if not prof.has_history and available >= med.min_stock_threshold:
        level = "low"
    elif point.first_stockout is not None:
        level = "high"
    elif stress.first_stockout is not None or min_stock < ss:
        level = "medium"
    else:
        level = "low"
    reasons = []
    if not prof.has_history:
        reasons.append("No usable sales history: demand is unknown, so risk is judged only against the minimum stock threshold.")
    if point.first_stockout is not None:
        reasons.append(f"Expected demand ({mu_L:.0f} units over {W} days) exceeds usable stock plus arriving orders; "
                       f"projected to run out around {start + timedelta(days=point.first_stockout)}.")
    elif stress.first_stockout is not None:
        reasons.append(f"Stock covers expected demand, but a higher-than-expected demand case (z={z:.2f}) would run out around "
                       f"{start + timedelta(days=stress.first_stockout)}.")
    elif min_stock < ss:
        reasons.append(f"Projected low point ({min_stock:.0f}) falls below safety stock ({ss:.0f}).")
    if available < med.min_stock_threshold:
        reasons.append(f"Usable stock ({available}) is below the minimum threshold ({med.min_stock_threshold}).")
        if level == "low":
            level = "medium"
    if any(i["overdue"] for i in inc):
        reasons.append("An open purchase order is past its expected date; arrival is assumed one full lead time from today.")
    days_cover = (available / mean_rate) if mean_rate > 0 else None
    calc = {
        "deterministic": {"usable_stock": available, "lead_time_days": lead, "lead_time_source": lead_src,
                          "open_orders": [{**i, "arrival": str(i["arrival"])} for i in inc], "window_days": W,
                          "safety_stock": round(ss, 1), "reorder_point": round(rop, 1), "z": round(z, 3),
                          "service_level": cfg.service_level, "min_threshold": med.min_stock_threshold,
                          "projected_min_stock": round(min_stock, 1), "days_of_cover": round(days_cover, 1) if days_cover is not None else None,
                          "first_projected_stockout": str(start + timedelta(days=point.first_stockout)) if point.first_stockout is not None else None,
                          "stress_stockout": str(start + timedelta(days=stress.first_stockout)) if stress.first_stockout is not None else None},
        "predicted_input": {"demand_source": prof.source, "mean_daily_demand": round(mean_rate, 3), "sigma_daily": round(sigma, 3),
                            "expected_demand_over_window": round(mu_L, 1)},
        "projection": [round(c, 1) for c in point.closing],
        "disclaimer": "Risk level is an estimate from a demand forecast plus inventory arithmetic. It is not a guarantee that stock will or will not run out.",
    }
    return {"risk_level": level, "reasons": reasons, "calculation": calc, "demand_source": prof.source}


def evaluate_shortages(db: Session, pharmacy_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    cfg = get_settings_row(db, pharmacy_id)
    existing = {a.medicine_id: a for a in db.scalars(select(ShortageAlert).where(
        ShortageAlert.pharmacy_id == pharmacy_id, ShortageAlert.status.in_(("open", "reviewed"))))}
    counts = {"high": 0, "medium": 0, "low": 0, "new_alerts": 0}
    for med in db.scalars(select(Medicine).where(Medicine.pharmacy_id == pharmacy_id, Medicine.is_active.is_(True))):
        r = assess_shortage(db, pharmacy_id, med, cfg, today)
        counts[r["risk_level"]] += 1
        old = existing.get(med.id)
        if r["risk_level"] == "low":
            if old:
                old.status = "superseded"
            continue
        if old and old.risk_level == r["risk_level"]:
            old.reasons, old.calculation, old.demand_source = r["reasons"], r["calculation"], r["demand_source"]
            continue
        if old:
            old.status = "superseded"
        alert = ShortageAlert(pharmacy_id=pharmacy_id, medicine_id=med.id, risk_level=r["risk_level"], status="open",
                              demand_source=r["demand_source"], reasons=r["reasons"], calculation=r["calculation"])
        db.add(alert); db.flush(); counts["new_alerts"] += 1
        notify(db, pharmacy_id=pharmacy_id, type_="shortage", severity="critical" if r["risk_level"] == "high" else "warning",
               title=f"{r['risk_level'].capitalize()} shortage risk: {med.name}", body=" ".join(r["reasons"][:2]),
               entity_type="shortage_alert", entity_id=alert.id)
    db.commit()
    return counts


# ------------------------------------------------------------------ expiration risk
def evaluate_expiry(db: Session, pharmacy_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    cfg = get_settings_row(db, pharmacy_id)
    windows = sorted(cfg.expiry_warning_days)
    horizon = max(windows) + 1
    existing = {(a.batch_id, a.alert_type): a for a in db.scalars(select(ExpirationAlert).where(
        ExpirationAlert.pharmacy_id == pharmacy_id, ExpirationAlert.status.in_(("open", "reviewed"))))}
    seen, created = set(), 0
    for med in db.scalars(select(Medicine).where(Medicine.pharmacy_id == pharmacy_id)):
        all_b = _batches(db, pharmacy_id, med.id, today, usable_only=False)
        if not all_b:
            continue
        prof = demand_profile(db, pharmacy_id, med.id, today, horizon)
        usable = [(b.id, b.expiration_date, b.quantity_remaining) for b in all_b if b.expiration_date >= today]
        sim = simulate_fefo(usable, prof.daily, [], today + timedelta(days=1))
        end_left = {bid: q for bid, q in ((x[0], x[2]) for x in usable)}
        for b in all_b:
            dte = (b.expiration_date - today).days
            if dte > horizon - 1:
                continue
            if dte < 0:
                atype, left = "expired", float(b.quantity_remaining)
            else:
                left = sim.expired.get(b.id, 0.0)
                atype = "projected_waste" if left >= 0.5 else ("approaching" if dte <= windows[0] else None)
            if atype is None:
                continue
            window = next((w for w in windows if dte <= w), windows[-1]) if dte >= 0 else 0
            value = left * float(b.unit_cost)
            calc = {"deterministic": {"days_to_expiry": dte, "quantity_remaining": b.quantity_remaining, "unit_cost": float(b.unit_cost),
                                      "method": "FEFO simulation: forecast demand is served first-expired-first-out; units still on hand when this batch expires are projected waste"},
                    "predicted_input": {"demand_source": prof.source, "mean_daily_demand": round(float(np.mean(prof.daily)), 3)},
                    "disclaimer": "Projected waste is an estimate. Expired or unsuitable stock must be quarantined/written off, never redistributed or sold."}
            key = (b.id, atype); seen.add(key)
            old = existing.get(key)
            if old:
                old.window_days, old.days_to_expiry, old.quantity_remaining = window, dte, b.quantity_remaining
                old.projected_leftover, old.at_risk_value, old.calculation, old.demand_source = left, value, calc, prof.source
                continue
            a = ExpirationAlert(pharmacy_id=pharmacy_id, batch_id=b.id, medicine_id=med.id, alert_type=atype, window_days=window,
                                days_to_expiry=dte, quantity_remaining=b.quantity_remaining, projected_leftover=left,
                                at_risk_value=value, status="open", demand_source=prof.source, calculation=calc)
            db.add(a); db.flush(); created += 1
            if atype in ("expired", "projected_waste"):
                notify(db, pharmacy_id=pharmacy_id, type_="expiration", severity="critical" if atype == "expired" else "warning",
                       title=("Expired stock on hand: " if atype == "expired" else "Projected waste: ") + f"{med.name} batch {b.batch_number}",
                       body=f"{b.quantity_remaining} units, expires {b.expiration_date}; estimated value at risk {value:.2f}.",
                       entity_type="expiration_alert", entity_id=a.id)
    for key, old in existing.items():
        if key not in seen:
            old.status = "superseded"
    db.commit()
    return {"alerts_created": created, "open_alerts": len(seen)}


# ------------------------------------------------------------------ reorder recommendations
def _phi(x: float) -> float:
    return NormalDist().cdf(x)


def build_recommendations(db: Session, pharmacy_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    cfg = get_settings_row(db, pharmacy_id)
    z = z_value(cfg.service_level)
    R = cfg.review_period_days
    for r in db.scalars(select(ReorderRecommendation).where(ReorderRecommendation.pharmacy_id == pharmacy_id, ReorderRecommendation.status == "pending")):
        r.status = "superseded"
    made = []
    for med in db.scalars(select(Medicine).where(Medicine.pharmacy_id == pharmacy_id, Medicine.is_active.is_(True))):
        lead, lead_src, sid = lead_time_for(db, pharmacy_id, med, cfg)
        H = lead + R
        prof = demand_profile(db, pharmacy_id, med.id, today, H)
        mu_L, mu_H = sum(prof.daily[:lead]), sum(prof.daily[:H])
        mean_d = mu_H / H if H else 0.0
        sigma = prof.sigma_daily
        batches = [(b.id, b.expiration_date, b.quantity_remaining) for b in _batches(db, pharmacy_id, med.id, today)]
        available = sum(q for _, _, q in batches)
        inc = open_incoming(db, pharmacy_id, med.id, today, lead, statuses=("approved", "ordered", "partially_received"))
        incoming_qty = sum(i["quantity"] for i in inc)
        waste = sum(simulate_fefo(batches, prof.daily, [], today + timedelta(days=1)).expired.values())
        position = available + incoming_qty - waste
        ss = z * sigma * math.sqrt(lead)
        rop = mu_L + ss
        S = max(mu_H + z * sigma * math.sqrt(H), float(med.min_stock_threshold))
        below_min = available < med.min_stock_threshold
        if not (prof.has_history or below_min):
            continue
        if not (position <= rop or below_min):
            continue
        # supplier terms
        sp = None
        if sid:
            sp = db.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == sid, SupplierProduct.medicine_id == med.id))
        if sp is None:
            sp = db.scalar(select(SupplierProduct).where(SupplierProduct.pharmacy_id == pharmacy_id, SupplierProduct.medicine_id == med.id).order_by(SupplierProduct.unit_price))
        moq = sp.min_order_quantity if sp else 1
        price = sp.unit_price if sp else float(med.purchase_price)
        supplier_id = sp.supplier_id if sp else sid
        recent = db.scalars(select(Batch).where(Batch.pharmacy_id == pharmacy_id, Batch.medicine_id == med.id).order_by(Batch.id.desc()).limit(5))
        shelves = [(b.expiration_date - b.received_date).days for b in recent]
        shelf = int(median(shelves)) if shelves else 365

        def qty_for(target: float) -> int:
            need = target - position
            return 0 if need <= 0 else int(math.ceil(need / moq) * moq)

        qty = qty_for(S)
        shelf_cap = int(math.ceil(mean_d * shelf * 0.8)) if mean_d > 0 else None
        capped = False
        if shelf_cap is not None and qty > shelf_cap and shelf_cap >= moq:
            qty, capped = int(math.ceil(shelf_cap / moq) * moq), True
        if qty <= 0:
            continue
        at_arrival = available + sum(i["quantity"] for i in inc if (i["arrival"] - today).days <= lead) - mu_L
        scen = []
        for label, tgt in (("Lean (lower service level, z=1.28)", mu_L + 1.28 * sigma * math.sqrt(lead)),
                           ("Recommended", S), ("Buffered (+30 days of demand)", S + 30 * mean_d)):
            q = qty if label == "Recommended" else qty_for(tgt)
            pos_after = position + q
            sd_H = sigma * math.sqrt(H)
            p_out = (1.0 if pos_after < mu_H else 0.0) if sd_H == 0 else 1 - _phi((pos_after - mu_H) / sd_H)
            cover = (pos_after / mean_d) if mean_d > 0 else None
            leftover = max(0.0, pos_after - mean_d * shelf) if mean_d > 0 else float(pos_after)
            hold = (pos_after / 2) * price * cfg.holding_cost_rate * ((cover or 0) / 365)
            scen.append({"label": label, "quantity": q, "purchase_cost": round(q * price, 2),
                         "position_after_order": round(pos_after, 1), "days_of_cover_after": round(cover, 1) if cover is not None else None,
                         "est_stockout_probability_next_cycle": round(p_out, 3),
                         "est_units_unsold_within_shelf_life": round(leftover, 1), "est_waste_cost": round(leftover * price, 2),
                         "est_holding_cost": round(hold, 2)})
        expl = {"inputs": {"usable_stock": available, "open_orders_qty": incoming_qty, "projected_expiry_waste_in_window": round(waste, 1),
                           "inventory_position": round(position, 1), "lead_time_days": lead, "lead_time_source": lead_src,
                           "review_period_days": R, "service_level": cfg.service_level, "z": round(z, 3),
                           "mean_daily_demand": round(mean_d, 3), "sigma_daily": round(sigma, 3), "demand_source": prof.source,
                           "min_order_quantity": moq, "unit_price": price, "min_threshold": med.min_stock_threshold},
                "formulas": {"safety_stock": f"z*sigma*sqrt(L) = {z:.2f}*{sigma:.2f}*sqrt({lead}) = {ss:.1f}",
                             "reorder_point": f"demand over L + SS = {mu_L:.1f} + {ss:.1f} = {rop:.1f}",
                             "order_up_to": f"demand over L+R + z*sigma*sqrt(L+R) = {S:.1f}",
                             "quantity": f"ceil(({S:.1f} - position {position:.1f}) / MOQ {moq}) * MOQ = {qty}"},
                "trigger": "inventory position at/below reorder point" if position <= rop else "usable stock below minimum threshold",
                "expected_position": {"projected_stock_when_order_arrives_before_this_order": round(at_arrival, 1),
                                      "after_replenishment": round(at_arrival + qty, 1)},
                "shelf_life_cap": {"assumed_shelf_days": shelf, "applied": capped},
                "disclaimer": "Recommendation only. Nothing is ordered until a user approves it and a purchase order is approved and placed."}
        rec = ReorderRecommendation(pharmacy_id=pharmacy_id, medicine_id=med.id, supplier_id=supplier_id, status="pending",
                                    recommended_qty=qty, unit_price=price, demand_source=prof.source, explanation=expl, scenarios=scen)
        db.add(rec); db.flush(); made.append(rec.id)
        notify(db, pharmacy_id=pharmacy_id, type_="reorder", severity="info", title=f"Reorder suggested: {med.name} ({qty} units)",
               body=expl["trigger"], entity_type="reorder_recommendation", entity_id=rec.id)
    db.commit()
    return {"recommendations_created": len(made), "ids": made}
