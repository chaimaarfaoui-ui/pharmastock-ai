"""Monte Carlo inventory simulation used to COMPARE replenishment policies under stated assumptions.
This is a what-if tool, not a forecast. All policies face identical demand and lead-time draws (common random numbers)."""
import math
from dataclasses import dataclass, field
from statistics import NormalDist
import numpy as np


@dataclass
class SimParams:
    mean_daily: float
    sigma_daily: float
    lead_mean: float = 5.0
    lead_sd: float = 1.0
    shelf_days: int = 365
    unit_cost: float = 1.0
    holding_rate: float = 0.20
    stockout_penalty_mult: float = 2.0     # lost-sale penalty per unit = unit_cost * this (user assumption)
    service_level: float = 0.95
    review_days: int = 7
    budget_per_30d: float | None = None
    horizon_days: int = 365

    @property
    def z(self): return NormalDist().inv_cdf(self.service_level)
    @property
    def reorder_point(self): return self.mean_daily * self.lead_mean + self.z * self.sigma_daily * math.sqrt(self.lead_mean)
    @property
    def order_up_to(self):
        h = self.lead_mean + self.review_days
        return self.mean_daily * h + self.z * self.sigma_daily * math.sqrt(h)


def draw(p: SimParams, runs: int, seed: int):
    rng = np.random.default_rng(seed)
    d = np.clip(np.round(rng.normal(p.mean_daily, p.sigma_daily, (runs, p.horizon_days))), 0, None)
    l = np.clip(np.round(rng.normal(p.lead_mean, p.lead_sd, (runs, p.horizon_days))), 1, None).astype(int)
    return d, l


class InventorySim:
    """One simulated pharmacy shelf. step(order_qty) advances one day; FEFO cohorts, expiry write-off, lead-time pipeline."""
    def __init__(self, p: SimParams, demand: np.ndarray, leads: np.ndarray):
        self.p, self.demand, self.leads, self.t = p, demand, leads, 0
        self.cohorts = [[p.shelf_days, p.mean_daily * (p.lead_mean + p.review_days)]]   # [expiry_day, qty]
        self.pipeline: list[list[float]] = []                                            # [arrival_day, qty]
        self.spend_log: list[tuple[int, float]] = []
        self.tot = dict(demand=0.0, unmet=0.0, holding=0.0, waste_units=0.0, spend=0.0, stockout_days=0, onhand=0.0)

    on_hand = property(lambda s: sum(c[1] for c in s.cohorts))
    position = property(lambda s: s.on_hand + sum(q for _, q in s.pipeline))
    done = property(lambda s: s.t >= s.p.horizon_days)

    def step(self, order_qty: float) -> float:
        p, t = self.p, self.t
        q = max(0.0, math.floor(order_qty))
        if q > 0 and p.budget_per_30d is not None:
            spent = sum(s for d, s in self.spend_log if t - d < 30)
            q = max(0.0, min(q, math.floor((p.budget_per_30d - spent) / p.unit_cost)))
        if q > 0:
            self.pipeline.append([t + int(self.leads[t]), q]); self.spend_log.append((t, q * p.unit_cost)); self.tot["spend"] += q * p.unit_cost
        for a in [a for a in self.pipeline if a[0] <= t]:
            self.cohorts.append([t + p.shelf_days, a[1]]); self.pipeline.remove(a)
        waste = sum(c[1] for c in self.cohorts if c[0] < t)
        self.cohorts = [c for c in self.cohorts if c[0] >= t]
        need = float(self.demand[t])
        for c in sorted(self.cohorts):
            take = min(need, c[1]); c[1] -= take; need -= take
        self.cohorts = [c for c in self.cohorts if c[1] > 1e-9]
        holding = self.on_hand * p.unit_cost * p.holding_rate / 365
        cost = holding + waste * p.unit_cost + need * p.unit_cost * p.stockout_penalty_mult
        self.tot["demand"] += float(self.demand[t]); self.tot["unmet"] += need; self.tot["holding"] += holding
        self.tot["onhand"] += self.on_hand; self.tot["waste_units"] += waste; self.tot["stockout_days"] += need > 1e-9
        self.t += 1
        return cost

    def summary(self) -> dict:
        p, T = self.p, self.tot
        waste_cost, pen = T["waste_units"] * p.unit_cost, T["unmet"] * p.unit_cost * p.stockout_penalty_mult
        return {"fill_rate": 1 - T["unmet"] / T["demand"] if T["demand"] else 1.0, "stockout_day_rate": T["stockout_days"] / p.horizon_days,
                "holding_cost": T["holding"], "waste_cost": waste_cost, "stockout_penalty": pen, "purchase_spend": T["spend"],
                "avg_on_hand_units": T["onhand"] / p.horizon_days, "total_cost": T["holding"] + waste_cost + pen}


def policy_reorder_point(p: SimParams):
    q = max(1.0, p.mean_daily * (p.lead_mean + p.review_days))
    return lambda s: q if s.position <= p.reorder_point else 0.0


def policy_order_up_to(p: SimParams):
    return lambda s: max(0.0, p.order_up_to - s.position) if s.t % p.review_days == 0 else 0.0


def policy_min_max(p: SimParams):
    return lambda s: max(0.0, p.order_up_to - s.position) if s.position <= p.reorder_point else 0.0


POLICIES = {"reorder_point_fixed_qty": policy_reorder_point, "periodic_order_up_to": policy_order_up_to, "min_max": policy_min_max}


def run_policy(p: SimParams, policy_fn, demands, leads) -> dict:
    res = []
    for r in range(demands.shape[0]):
        s = InventorySim(p, demands[r], leads[r])
        while not s.done:
            s.step(policy_fn(s))
        res.append(s.summary())
    keys = res[0].keys()
    return {k: float(np.mean([x[k] for x in res])) for k in keys} | {"total_cost_sd": float(np.std([x["total_cost"] for x in res]))}


def compare_policies(p: SimParams, runs: int = 100, seed: int = 123) -> dict:
    d, l = draw(p, runs, seed)
    return {name: run_policy(p, fn(p), d, l) for name, fn in POLICIES.items()}


def tune_service_level(p: SimParams, policy_name: str, demands, leads, grid=(0.5, 0.8, 0.9, 0.95, 0.98, 0.99, 0.995, 0.999, 0.9995)) -> tuple[float, dict]:
    """Fair baseline: pick the service level (z) that minimises total cost on TUNING seeds."""
    from dataclasses import replace
    best = None
    for sl in grid:
        q = replace(p, service_level=sl)
        m = run_policy(q, POLICIES[policy_name](q), demands, leads)
        if best is None or m["total_cost"] < best[1]["total_cost"]:
            best = (sl, m)
    return best
