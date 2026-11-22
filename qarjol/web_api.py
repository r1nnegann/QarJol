"""JSON-ready views of the QarJol agent for the web interface.

The web page never re-implements the algorithms. It calls these functions,
either through the local server in ``app.py`` or through Pyodide (Python
running inside the browser) on the online version. Both paths run the same
code as ``main.py``: A* from search.py, Bayes from bayes.py, the MDP from
mdp.py and the minute-by-minute loop from agent.py.

Every function returns plain dicts, lists, numbers and strings, so the result
can be passed to ``json.dumps`` directly.
"""

import random

from . import bayes, mdp
from .agent import POLICIES, QarJolAgent, compare_policies
from .campus import BUILDING_NAMES
from .search import uniform_cost

MAX_READINGS = 20
MAX_MORNINGS = 50_000

EVALUATION_SCENARIOS = (
    ("normal", "Normal day", {"prior_blocked": 0.30, "p_plow_clears": 0.50}),
    ("clear_forecast", "Clear forecast", {"prior_blocked": 0.05, "p_plow_clears": 0.50}),
    ("blizzard", "Blizzard (slow plow)", {"prior_blocked": 0.30, "p_plow_clears": 0.10}),
)


def _cell(cell):
    return [cell[0], cell[1]] if cell is not None else None


def _path(path):
    return [_cell(c) for c in path] if path is not None else None


def _probability(name, value):
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, got {value}")
    return value


def _readings(readings):
    if isinstance(readings, str):
        readings = [r for r in readings.replace(",", " ").split() if r]
    readings = [str(r).upper() for r in readings]
    if len(readings) > MAX_READINGS:
        raise ValueError(f"at most {MAX_READINGS} readings are allowed")
    for r in readings:
        if r not in bayes.READINGS:
            raise ValueError(f"reading must be SNOW or CLEAR, got {r!r}")
    return readings


def _search_result(result):
    return {
        "path": _path(result["path"]),
        "cost": result["cost"],
        "expanded": result["expanded"],
        "closed": [_cell(c) for c in result["closed"]],
        "trace": [{"node": _cell(t["node"]), "g": t["g"], "h": t["h"], "f": t["f"],
                   "frontier": t["frontier"]} for t in result["trace"]],
    }


def make_agent(prior=bayes.PRIOR_BLOCKED, plow=mdp.DEFAULTS["p_plow_clears"]):
    return QarJolAgent(prior_blocked=_probability("prior", prior),
                       p_plow_clears=_probability("plow", plow))


def scenario(prior=bayes.PRIOR_BLOCKED, plow=mdp.DEFAULTS["p_plow_clears"],
             readings=("SNOW", "CLEAR")):
    """Everything the page shows for one morning: map, A*, Bayes, MDP, decisions."""
    readings = _readings(readings)
    agent = make_agent(prior, plow)
    campus, routes = agent.campus, agent.routes

    # Same value iteration as the agent, but keep every sweep for the chart.
    full = mdp.value_iteration(agent.mdp, keep=10_000)
    sol = agent.solution
    b_star = mdp.threshold(sol)
    ucs = uniform_cost(campus)

    log = agent.run(readings) if readings else []
    minutes = []
    for e in log:
        item = {"minute": e["minute"], "reading": e["reading"], "prior": e["prior"],
                "bayes": dict(e["bayes"]), "belief": e["belief"],
                "scores": dict(e["scores"]), "action": e["action"]}
        if "next_prior" in e:
            item["next_prior"] = e["next_prior"]
        minutes.append(item)

    if not log:
        status, waited = "no_reading", 0
    elif log[-1]["action"] == "Move":
        status, waited = "move", len(log) - 1
    else:
        status, waited = "waiting", len(log)

    buildings = {}
    for r, row in enumerate(campus.rows):
        for c, ch in enumerate(row):
            if ch in BUILDING_NAMES:
                buildings.setdefault(ch, []).append([r, c])

    return {
        "inputs": {"prior": agent.prior_blocked, "plow": agent.mdp["params"]["p_plow_clears"],
                   "readings": readings, "readings_used": len(log)},
        "campus": {"rows": list(campus.rows), "height": campus.height, "width": campus.width,
                   "start": _cell(campus.start), "goal": _cell(campus.goal),
                   "passage": _cell(campus.passage),
                   "buildings": [{"symbol": s, "name": BUILDING_NAMES[s], "cells": cells}
                                 for s, cells in buildings.items()]},
        "search": {
            "heuristic": "Manhattan distance",
            "shortcut": _search_result(routes["shortcut"]),
            "replan": _search_result(routes["replan"]),
            "ucs": {"cost": ucs["cost"], "expanded": ucs["expanded"],
                    "order": [_cell(t["node"]) for t in ucs["trace"]]},
            "replan_from": _cell(routes["replan_from"]),
            "steps_to_turn_back": routes["steps_to_turn_back"],
            "stuck_steps": routes["stuck_steps"],
            "stuck_path": _path(routes["stuck_path"]),
        },
        "bayes": {"prior": agent.prior_blocked, "sensor": {s: dict(v) for s, v in agent.sensor.items()},
                  "first": minutes[0]["bayes"] if minutes else None},
        "mdp": {
            "params": dict(agent.mdp["params"]),
            "rewards": {s: dict(v) for s, v in agent.mdp["rewards"].items()},
            "wait_transition": {s: dict(v) for s, v in agent.mdp["wait_transition"].items()},
            "values": dict(sol["values"]), "q": {s: dict(v) for s, v in sol["q"].items()},
            "policy": dict(sol["policy"]), "iterations": sol["iterations"],
            "sweeps": full["sweeps"],
            "threshold": b_star,
            "qb_at_0": mdp.belief_q(sol, 0.0), "qb_at_1": mdp.belief_q(sol, 1.0),
        },
        "minutes": minutes,
        "result": {"status": status, "waited": waited,
                   "route": _path(routes["shortcut"]["path"]) if status == "move" else None,
                   "route_if_blocked": _path(routes["stuck_path"]) if status == "move" else None},
    }


def evaluate(mornings=10_000, prior=None, plow=None, seed=2026):
    """The policy comparison from ``main.py --evaluate``, plus the user's own settings."""
    if isinstance(mornings, bool) or int(mornings) != mornings:
        raise ValueError("mornings must be a positive integer")
    mornings = int(mornings)
    if not 0 < mornings <= MAX_MORNINGS:
        raise ValueError(f"mornings must be between 1 and {MAX_MORNINGS}")
    scenarios = list(EVALUATION_SCENARIOS)
    if prior is not None and plow is not None:
        custom = {"prior_blocked": _probability("prior", prior),
                  "p_plow_clears": _probability("plow", plow)}
        if all(custom != kw for _, _, kw in scenarios):
            scenarios.append(("custom", "Your settings", custom))
    out = []
    for key, name, kwargs in scenarios:
        results = compare_policies(QarJolAgent(**kwargs), mornings, seed)
        out.append({"key": key, "name": name, "prior": kwargs["prior_blocked"],
                    "plow": kwargs["p_plow_clears"], "results": results})
    return {"mornings": mornings, "seed": seed, "policies": list(POLICIES), "scenarios": out}


def random_morning(prior=bayes.PRIOR_BLOCKED, plow=mdp.DEFAULTS["p_plow_clears"],
                   seed=None, max_wait=10):
    """Play one simulated morning with a hidden true state (same model as ``simulate``).

    The agent only sees the sensor readings. The true state is revealed at the
    end so the page can show whether the decision worked out.
    """
    agent = make_agent(prior, plow)
    seed = random.randrange(1_000_000) if seed is None else int(seed)
    rng = random.Random(seed)
    params, transition, routes = agent.mdp["params"], agent.mdp["wait_transition"], agent.routes
    state = "Blocked" if rng.random() < agent.prior_blocked else "Clear"
    belief = agent.prior_blocked
    steps, reward, minutes = [], 0.0, 0
    for wait_round in range(max_wait + 1):
        reading = "SNOW" if rng.random() < agent.sensor[state]["SNOW"] else "CLEAR"
        prior_now = belief
        belief = bayes.bayes_update(belief, reading, agent.sensor)["posterior_blocked"]
        action, scores = mdp.choose_action(agent.solution, belief)
        forced = False
        if wait_round == max_wait and action == "Wait":
            action, forced = "Move", True
        steps.append({"minute": wait_round, "true_state": state, "reading": reading,
                      "prior": prior_now, "belief": belief, "scores": scores,
                      "action": action, "forced": forced})
        if action == "Wait":
            minutes += 1
            reward -= params["wait_cost"]
            state = "Blocked" if rng.random() < transition[state]["Blocked"] else "Clear"
            belief = bayes.predict(belief, transition)
            continue
        break
    stuck = state == "Blocked"
    travel = routes["stuck_steps"] if stuck else routes["shortcut"]["cost"]
    reward += params["delivery_reward"] - params["step_cost"] * travel
    if stuck:
        reward -= params["stuck_penalty"]
    return {"seed": seed, "steps": steps, "state_on_departure": state, "stuck": stuck,
            "travel_steps": travel, "wait_minutes": minutes, "total_minutes": minutes + travel,
            "reward": reward,
            "path": _path(routes["stuck_path"] if stuck else routes["shortcut"]["path"]),
            "replan_from": _cell(routes["replan_from"])}
