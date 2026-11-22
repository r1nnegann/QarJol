# QarJol — Winter Campus Courier Robot

**Student:** Madaminov Salmankhoja · **Course:** AIF1303 AI Fundamentals, QAIRU  
**Lecturer:** Aizhan Sydykova · **Project:** individual; topic 02, Mini Campus Delivery Robot.

## Problem and solution

A winter courier must deliver a parcel from a dormitory to the AI Lab. Snow may block the short courtyard route, and the sensor is noisy. The decision is whether to **Move** now or **Wait** for the snowplow. AI connects route costs, uncertain evidence and the future consequences of waiting.

This console simulation uses a **hypothetical map and assumed probabilities, rewards and times**, not real campus measurements.

```text
A* route lengths → MDP rewards → value iteration → Q(state, action)
                                                        ↓
forecast + sensor → Bayes → belief P(Blocked) → weighted action choice
                                                        ↓
                             Move: deliver       Wait: predict next belief
                                                        ↓
                                             next sensor → Bayes again
```

The algorithms serve one goal: A* changes the MDP's travel rewards, Bayes changes the belief used for action selection, and Wait feeds the next Bayesian update. UCS is a search baseline and BFS a test oracle, not additional agent stages.

## Web interface

**Online:** <https://aif.s-madaminov.tech/> · **Local:** `python app.py` opens the same page at `http://127.0.0.1:8765/` (no internet needed).

The page is an interactive view of the same agent. It shows the campus map with the planned shortcut and fallback, an A* expansion player (g, h and f in every expanded cell), the Bayes update for each minute, the value-iteration curve, the belief-weighted Move/Wait scores with the crossover b*, a minute-by-minute recommendation and the 10,000-morning policy comparison. Presets reproduce the console scenarios; sliders change the forecast prior and snowplow speed; SNOW/CLEAR buttons (keys `S`, `C`, `Backspace`) add readings. "Play a random morning" hides the true courtyard state, samples readings from it and reveals it when the robot leaves.

The page does not re-implement the algorithms. `qarjol/web_api.py` returns the agent's results as JSON. Locally, `app.py` (standard-library `http.server`) calls it; online, the page loads Python in the browser with [Pyodide](https://pyodide.org/) and imports the same `qarjol` files. Both paths print the same numbers as `main.py`.

## Run

**Python 3.9+; standard library only.** Local verification: Windows, Python 3.14.0. Extract the ZIP and open a terminal **inside `QarJol`**.

```powershell
python app.py
python main.py
python -m unittest discover -s tests -v
python main.py --evaluate
```

Windows alternative: replace `python` with `py -3`. Linux/macOS: use `python3` (instructions supplied; local verification was on Windows).

| Scenario | Command | Actual saved output |
|---|---|---|
| SNOW, then CLEAR | `python main.py` | [default.txt](samples/default.txt) |
| CLEAR immediately | `python main.py --readings CLEAR` | [clear.txt](samples/clear.txt) |
| Clear forecast, SNOW alert | `python main.py --prior 0.05 --readings SNOW` | [clear_forecast.txt](samples/clear_forecast.txt) |
| Slow snowplow | `python main.py --plow 0.1 --readings SNOW` | [blizzard.txt](samples/blizzard.txt) |
| Policy comparison | `python main.py --evaluate` | [evaluation.txt](samples/evaluation.txt) |

`--readings` supplies one or more SNOW/CLEAR observations until Move; `--prior` and `--plow` must be probabilities. `--mornings` must be a positive integer. Evaluation always uses its three fixed scenarios: `--prior`/`--plow` change the preceding demo, not the comparison scenarios.

## A* — route planning

**How it works:** expand the smallest `f=g+h`, record parents, and reconstruct the route at the goal. `g` counts steps taken; `h` is Manhattan distance. Ties use smaller `h`, then insertion order. Manhattan is admissible and consistent for four-direction unit-cost moves: each move reduces the distance by at most its cost; walls can only add detours.

**Why chosen:** a small known grid and fixed destination allow an inexpensive heuristic.  
**Contribution:** route lengths become the MDP's Move rewards.

| Stage | Project example |
|---|---|
| Input | Grid below; start `(5,4)`, goal `(0,3)`, courtyard `P=(2,5)`; four directions, cost 1 |
| Steps | Start: `g=0`, `h=abs(5-0)+abs(4-3)=6`, `f=6`. Next chosen cell `(4,4)`: `g=1`, `h=5`, `f=6`. Continue expanding minimum f. |
| Output | Shortcut 8 steps. If P is blocked: 3 steps to `(3,5)`, then an 11-step replan; total 14. |
| One sentence | A* supplies the route and travel cost used by the decision model. |

```text
. . . G . .
. C . . . .
. M M M M P
. . . . . .
. L L . . .
. . . . S .
```

`S`: dormitory; `G`: AI Lab; `P`: courtyard; `L/M/C`: impassable library/main building/canteen. Coordinates are zero-based `(row,column)`. The 14-step fallback includes discovering the blockage along the way; it is not the shortest path from the start with the blockage already known.

## Bayes — interpreting the sensor

**How it works:** `P(Blocked|e)=P(e|Blocked)P(Blocked)/P(e)`, with evidence `P(e)=P(e|Blocked)P(Blocked)+P(e|Clear)P(Clear)`.

**Why chosen:** a binary condition and one noisy observation need a transparent update, without training.  
**Contribution:** the posterior becomes the action selector's belief `b`.

| Stage | Project example |
|---|---|
| Input | Prior 0.30; P(SNOW\|Blocked)=0.85; P(SNOW\|Clear)=0.15; observed SNOW |
| Steps | Joint Blocked: `0.85×0.30=0.255`; joint Clear: `0.15×0.70=0.105`; evidence: `0.36` |
| Output | Posterior: `0.255/0.36=0.7083` |
| One sentence | Bayes combines the forecast and sensor error rates into a blockage probability. |

With CLEAR and the same initial prior, the posterior is `0.045/(0.045+0.595)=0.0703`. After Wait, prediction happens before the next observation: `b_next=b×P(Blocked→Blocked)+(1-b)×P(Clear→Blocked)`.

## MDP — Move or Wait

**How it works:** Clear/Blocked are decision states; Move/Wait are actions. Move ends in implicit terminal Delivered (future value zero). Value iteration starts from zero, computes `Q(s,a)=R(s,a)+gamma×Σ T(s,a,s')V(s')`, then sets `V_new(s)=max_a Q(s,a)`. For Move, only the immediate aggregated delivery reward remains.

**Why chosen:** waiting can change snow conditions, so future consequences matter.  
**Contribution:** choose the action with the larger belief-weighted score, `Q_b(a)=(1-b)Q(Clear,a)+bQ(Blocked,a)`.

| Stage | Project example |
|---|---|
| Input | A* costs 8/14; delivery +20, step −1, blockage penalty −3, Wait −1; gamma 0.95; transitions below |
| Steps | Move rewards `20−8=12`, `20−14−3=3`; value sweeps `(0,0)`, `(12,3)`, `(12,6.1250)`, `(12,7.6094)` |
| Output | Converges in 32 sweeps. Q(Clear): Move 12, Wait 10.1105; Q(Blocked): Move 3, Wait 8.9524. |
| One sentence | The MDP weighs current travel costs against what may happen while waiting. |

### Hand check

```text
V(Clear)=12
V(Blocked)=−1+0.95×(0.50×12+0.50×V(Blocked))
V(Blocked)=4.7/0.525=8.9524
Q(Clear,Wait)=−1+0.95×(0.90×12+0.10×8.9523809524)=10.1105
b* = 1.8895238095 / 7.8419047619 ≈ 0.2409521496
```

The crossing `b*` equates the two weighted scores. Below it, Move wins; above it, Wait wins. The code compares full-precision scores and chooses Move for an exact score tie; displayed `0.2410` is rounded. In the blizzard, `Q(Blocked,Wait)=−1+0.95×(0.10×12+0.90×3)=2.705<3`, so Move wins at every belief.

## Sample input/output

Input: `python main.py`, with prior 0.30 and readings SNOW, CLEAR. Unchanged excerpt from [the actual run](samples/default.txt):

```text
minute 0: prior 0.3000, reading SNOW  -> P(Blocked) 0.7083
          Q_b: Move 5.625, Wait 9.290  => Wait
          waits 1 minute; P(Blocked) before the next reading 0.3833
minute 1: prior 0.3833, reading CLEAR -> P(Blocked) 0.0989
          Q_b: Move 11.110, Wait 9.996  => Move
RESULT  recommended Move after waiting 1 min; planned shortcut if P is clear (8 steps): (5,4) -> (4,4) -> (3,4) -> (3,5) -> (2,5) -> (1,5) -> (0,5) -> (0,4) -> (0,3)
        if P is blocked on arrival: fallback route (14 steps)
. . . G * *
. C . . . *
. M M M M P
. . . . * *
. L L . * .
. . . . S .
```

After SNOW the belief is 0.7083 and the choice is Wait. Prediction gives the next prior 0.3833; CLEAR lowers the belief to 0.0989 and the choice becomes Move. This is a route recommendation, not an observed delivery. If supplied readings end after Wait, the demo reports “still waiting”.

## Tests

`python -m unittest discover -s tests -v`: **33/33 passed locally** (the original 21, four regression tests added after review and eight tests for the web layer).

- A* against independent BFS; valid walks, obstacles, unreachable goal and UCS comparison.
- Bayesian arithmetic, uninformative sensor, belief prediction and invalid inputs.
- Route-derived rewards, closed-form Bellman solution, normal/blizzard policies and threshold.
- Four demo decisions, seeded reproducibility and comparison against fixed rules.
- Review regressions: invalid sensor probabilities, invalid simulation counts, exact-score ties and invalid CLI arguments.
- Web layer (`tests/test_web.py`): the JSON views reproduce the console numbers (0.7083, 0.0989, b* 0.2410, 13 vs 24 expansions, evaluation rewards), invalid inputs are rejected, random mornings are reproducible, and the local server answers the page, the API and HTTP 400 for bad input.

`test_agent_never_worse_than_fixed_rules` checks only its seeded scenarios; its name is not a universal optimality guarantee.

## Evaluation

**10,000 mornings per policy per scenario, seed 2026.** The simulator samples the hidden initial condition, sensor readings and Wait transitions. It forces Move after 10 waits. `always_move` leaves immediately; `trust_sensor` waits on SNOW and moves on CLEAR; `agent` uses Bayes and the MDP. Each policy starts from the same seed, but different numbers of random draws mean trajectories need not match morning by morning.

| Scenario | Policy | Average minutes | Average reward | Blockage encounter rate |
|---|---|---:|---:|---:|
| normal day | agent | 9.131 | 10.624 | 0.082 |
| normal day | always_move | 9.811 | 9.283 | 0.302 |
| normal day | trust_sensor | 9.131 | 10.624 | 0.082 |
| clear forecast | agent | 8.298 | 11.553 | 0.050 |
| clear forecast | always_move | 8.298 | 11.553 | 0.050 |
| clear forecast | trust_sensor | 8.392 | 11.552 | 0.019 |
| blizzard | agent | 9.811 | 9.283 | 0.302 |
| blizzard | always_move | 9.811 | 9.283 | 0.302 |
| blizzard | trust_sensor | 10.474 | 8.903 | 0.208 |

Values are exactly the rounded saved output. The output's `stuck rate` means encountering a blocked courtyard and taking the fallback, not failed delivery. Evaluation rewards are **undiscounted**, unlike the MDP's planning values.

The agent matches `trust_sensor` on a normal day and `always_move` in the other scenarios. In the clear forecast, 11.553 versus 11.552 is a negligible reward difference, and `trust_sensor` encounters fewer blockages. No compared fixed rule wins in every scenario. The simulator shares the agent's assumed model: this checks decision logic, not real-world accuracy or statistical superiority.

**Search comparison:** A* and UCS both return cost 8; A* removes 13 nodes versus UCS's 24, counting the goal. This is a map-specific expansion count, not a runtime benchmark.

## Assumptions

| Item | Assumption |
|---|---|
| Map/motion | Hypothetical 6×6 grid; four directions; cost 1 per step, roughly 1 minute |
| Uncertainty | Only P can be blocked; buildings are fixed |
| Forecast | P(Blocked)=0.30 normally; 0.05 for clear forecast |
| Sensor | Blocked: SNOW 0.85/CLEAR 0.15; Clear: SNOW 0.15/CLEAR 0.85 |
| Wait transitions | Clear→Clear 0.90/Blocked 0.10; Blocked→Clear 0.50/Blocked 0.50 |
| Slow plow | Blocked→Clear 0.10/Blocked 0.90 |
| Reward | Delivery +20; step −1; blockage encounter −3; Wait −1 |
| Planning | Gamma 0.95; synchronous updates from zero; tolerance 1e-9 |
| Movement | One terminal action with aggregated travel cost; snow is fixed during delivery |
| Sensing | Each reading follows the fixed model for the current state |
| Evaluation | 10,000 mornings, seed 2026, at most 10 waits |

## Limitations, improvements and future development

- Assumed probabilities need real sensor and snow-clearing measurements.
- One risky passage and a fixed map could later become several uncertain cells with expected travel costs.
- Weighting a fully observed MDP's Q values by belief is an approximation; a full POMDP could plan the information gained from future readings.
- The simulation wait cap is absent from infinite-horizon value iteration; movement duration is simplified into a terminal reward.
- Synthetic results do not validate real robot hardware or campus travel.

The scenario extends the delivery-robot idea from Week 1 practice. Future coursework could introduce several parcels/robots, actual snowplow records or a ROS robot. Those extensions are outside this console project.

## Code map

`main.py`: console; `app.py`: local web server; `web/`: page, styles and drawing code; `web_api.py`: JSON views for the page; `campus.py`: grid; `search.py`: routes; `bayes.py`: inference; `mdp.py`: decision model; `agent.py`: integration and simulation. Modules are in `qarjol/`; tests in `tests/`; complete command outputs in `samples/`.

## References

- QAIRU AIF1303, Week 2, *Uninformed Search, A* Search & Heuristics*, `Lecture_2.pdf`.
- QAIRU AIF1303, Week 5, *Markov Decision Processes + Reinforcement Learning*, `MDP_Reinforcement_Learning.pptx`.
- QAIRU AIF1303, Week 6, *Probability & Bayesian Networks*, `Lecture 6 Probability and Bayesian Networks.pdf`.
- QAIRU AIF1303, `Final Project.docx` and `MiniAI_FPTopics.docx` (topic 02; similarly sized toy inputs are allowed).
- Stuart Russell and Peter Norvig, *Artificial Intelligence: A Modern Approach*, fourth US edition, [official website](https://aima.cs.berkeley.edu/). General theory reference; no page-specific claim or copied implementation is attributed here.
