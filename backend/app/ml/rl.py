"""EXPERIMENTAL reinforcement-learning research extension (tabular Q-learning) in a SIMULATED environment.

It is never connected to the purchasing workflow. Run:  python -m app.ml.rl   -> writes docs/rl_experiment.json
The agent is evaluated on held-out random seeds against the classical policies using the same cost function."""
import json
import sys
from pathlib import Path
import numpy as np
from dataclasses import replace
from app.ml.simulation import InventorySim, POLICIES, SimParams, draw, run_policy, tune_service_level

ACTIONS = [0, 1, 2, 3, 4]    # order k * (mean_daily * review_days / 2) units


def _state(s: InventorySim) -> tuple[int, int]:
    p = s.p
    cover = s.on_hand / max(p.mean_daily, 1e-9)
    pipe = sum(q for _, q in s.pipeline) / max(p.mean_daily * p.review_days, 1e-9)
    return min(int(cover // 2), 9), min(int(pipe // 1), 3)


def _qty(p: SimParams, a: int) -> float:
    return a * p.mean_daily * p.review_days / 2


def train(p: SimParams, episodes=1500, seed=0, alpha=0.1, gamma=0.97) -> np.ndarray:
    rng = np.random.default_rng(seed)
    Q = np.zeros((10, 4, len(ACTIONS)))
    scale = p.mean_daily * p.unit_cost + 1e-9
    for ep in range(episodes):
        eps = max(0.05, 1.0 - ep / (0.7 * episodes))
        d, l = draw(p, 1, seed=10_000 + ep)
        s = InventorySim(p, d[0], l[0])
        st = _state(s)
        while not s.done:
            a = int(rng.integers(len(ACTIONS))) if rng.random() < eps else int(np.argmax(Q[st]))
            cost = s.step(_qty(p, ACTIONS[a]))
            nxt = _state(s)
            Q[st][a] += alpha * (-cost / scale + gamma * (0 if s.done else Q[nxt].max()) - Q[st][a])
            st = nxt
    return Q


def evaluate_agent(p: SimParams, Q: np.ndarray, demands, leads) -> dict:
    costs, fills, stock = [], [], []
    for r in range(demands.shape[0]):
        s = InventorySim(p, demands[r], leads[r])
        while not s.done:
            s.step(_qty(p, int(np.argmax(Q[_state(s)]))))
        m = s.summary(); costs.append(m["total_cost"]); fills.append(m["fill_rate"]); stock.append(m["avg_on_hand_units"])
    return {"total_cost": float(np.mean(costs)), "total_cost_sd": float(np.std(costs)), "fill_rate": float(np.mean(fills)), "avg_on_hand_units": float(np.mean(stock))}


def main(out: str = "../docs/rl_experiment.json") -> dict:
    p = SimParams(mean_daily=10, sigma_daily=4, lead_mean=5, lead_sd=1.5, shelf_days=180, unit_cost=2.0, horizon_days=180)
    Q = train(p, episodes=1500)
    tune_d, tune_l = draw(p, 100, seed=777)           # tuning seeds for baselines (separate from evaluation seeds)
    demands, leads = draw(p, 100, seed=999_001)       # held-out seeds, never used in training or tuning
    baselines, tuned = {}, {}
    for n, fn in POLICIES.items():
        baselines[n] = run_policy(p, fn(p), demands, leads)                       # fixed 95% service level
    for n in ("periodic_order_up_to", "min_max"):
        sl, _ = tune_service_level(p, n, tune_d, tune_l)
        q = replace(p, service_level=sl)
        tuned[n + "_cost_tuned"] = run_policy(q, POLICIES[n](q), demands, leads) | {"tuned_service_level": sl}
    result = {"experimental": True, "note": "Simulated environment only. Not validated on real data and never used for real purchasing.",
              "params": {k: getattr(p, k) for k in ("mean_daily", "sigma_daily", "lead_mean", "lead_sd", "shelf_days", "unit_cost", "holding_rate", "stockout_penalty_mult", "horizon_days")},
              "training_episodes": 1500, "eval_runs": 100,
              "baselines_fixed_95pct_service": baselines, "baselines_cost_tuned": tuned,
              "rl_q_learning": evaluate_agent(p, Q, demands, leads)}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    r = main(*(sys.argv[1:2]))
    for grp in ("baselines_fixed_95pct_service", "baselines_cost_tuned"):
        for k, v in r[grp].items():
            print(f"{k:34s} cost {v['total_cost']:7.1f} fill {v['fill_rate']:.3f} avg_stock {v['avg_on_hand_units']:.0f}")
    v = r["rl_q_learning"]
    print(f"{'rl_q_learning':34s} cost {v['total_cost']:7.1f} fill {v['fill_rate']:.3f} avg_stock {v['avg_on_hand_units']:.0f}")
