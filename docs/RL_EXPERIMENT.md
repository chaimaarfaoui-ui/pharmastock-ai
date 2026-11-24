# Reinforcement-learning extension (experimental, simulated environment only)

Reproduce: `cd backend && python -m app.ml.rl ../docs/rl_experiment.json` (about 10 s).
It is never connected to the purchasing workflow. Any real use would require validation on real data and explicit human approval.

## Setup
Simulated shelf: demand ~ Normal(10, 4) units/day, lead time ~ Normal(5, 1.5) days, 180-day shelf life, unit cost 2.0, holding 20%/year, lost-sale penalty 2× unit cost, 180-day horizon, FEFO with expiry write-off. Tabular Q-learning (state: on-hand cover × pipeline; actions: order 0–4 half-review-periods of demand), 1,500 training episodes. Evaluation: 100 held-out random seeds never used in training or tuning, identical demand and lead times for every policy.

## Results (mean total cost ± SD across runs; cost = holding + expiry waste + lost-sale penalty)
| Policy | Cost | Fill rate | Avg stock (units) |
|---|---|---|---|
| Reorder point, fixed quantity (95% service) | 240.8 ± 117.1 | 96.9% | 66 |
| Periodic order-up-to (95% service) | 138.6 ± 81.2 | 98.2% | 55 |
| Min-max (95% service) | 346.6 ± 164.1 | 95.4% | 48 |
| Periodic order-up-to, **cost-tuned** (service level 0.9995) | 26.5 ± 25.9 | 99.8% | 76 |
| Min-max, cost-tuned (0.9995) | 84.9 ± 75.2 | 99.0% | 65 |
| **RL (Q-learning)** | **22.1 ± 0.6** | 100.0% | 112 |

## Interpretation
* The first run compared RL against fixed-95%-service baselines and looked dramatically better (22 vs 139). That comparison was unfair: those baselines target a service level, not cost. With a cost-tuned baseline the gap nearly disappears (22.1 vs 26.5, well inside the baseline's run-to-run SD of 25.9).
* In this setup holding stock is cheap relative to stockouts, so the cost-minimising behaviour is to overstock. The tuned baseline hit the edge of its grid (0.9995). RL "wins" by holding about 50% more stock than the tuned baseline (112 vs 76 units).
* **Conclusion: no demonstrated advantage of RL over a properly tuned classical policy.** The experiment mainly shows the cost parameters favour high stock. A fair follow-up would vary the cost ratios and use demand and shelf-life distributions fitted from real data.
