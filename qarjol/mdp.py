"""Part 3 - sequential decision making: a 2-state / 2-action MDP, Move or Wait (Week 5).

States   Clear, Blocked  (condition of the courtyard passage P)  + terminal Delivered
Actions  Move  go now along the A* shortcut through P
         Wait  stay one minute; snow can fall or the campus snowplow can clear P

Rewards come from the A* route lengths (this is where search feeds the MDP):

    R(Clear,   Move) = DELIVERY - STEP * len(shortcut)
    R(Blocked, Move) = DELIVERY - STEP * len(walk to P + A* re-plan) - STUCK
    R(any,     Wait) = -WAIT

Move ends the episode (parcel delivered). Wait keeps it going with the
transition table below. Value iteration solves the Bellman equation

    V(s) = max_a [ R(s, a) + gamma * sum_s' T(s, a, s') V(s') ]

and gives Q(s, a). The robot does not know the true state, only the Bayes
belief b = P(Blocked), so it scores each action with the belief-weighted Q:

    Q_b(a) = (1 - b) * Q(Clear, a) + b * Q(Blocked, a)

and picks the larger one.
"""

STATES = ("Clear", "Blocked")
ACTIONS = ("Move", "Wait")

DEFAULTS = {
    "delivery_reward": 20.0,  # value of a delivered parcel (assumption)
    "step_cost": 1.0,         # one grid step ~ one minute of battery/time
    "stuck_penalty": 3.0,     # turning around in a drift, extra battery drain
    "wait_cost": 1.0,         # one minute idle in the cold
    "gamma": 0.95,            # discount: a later delivery is worth a bit less
    "p_new_drift": 0.10,      # Clear -> Blocked during one minute of waiting
    "p_plow_clears": 0.50,    # Blocked -> Clear during one minute of waiting
}


def build_mdp(routes, **overrides):
    """Turn the A* route plan into rewards and transitions."""
    unknown = set(overrides) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown MDP parameters: {sorted(unknown)}")
    p = {**DEFAULTS, **overrides}
    for key in ("p_new_drift", "p_plow_clears"):
        if not 0.0 <= p[key] <= 1.0:
            raise ValueError(f"{key} must be a probability")
    if not 0.0 <= p["gamma"] < 1.0:
        raise ValueError("gamma must be in [0, 1)")

    deliver, step = p["delivery_reward"], p["step_cost"]
    rewards = {
        "Clear": {"Move": deliver - step * routes["shortcut"]["cost"],
                  "Wait": -p["wait_cost"]},
        "Blocked": {"Move": deliver - step * routes["stuck_steps"] - p["stuck_penalty"],
                    "Wait": -p["wait_cost"]},
    }
    wait_transition = {
        "Clear": {"Clear": 1.0 - p["p_new_drift"], "Blocked": p["p_new_drift"]},
        "Blocked": {"Clear": p["p_plow_clears"], "Blocked": 1.0 - p["p_plow_clears"]},
    }
    return {"params": p, "rewards": rewards, "wait_transition": wait_transition}


def q_value(mdp, state, action, values):
    """One Bellman backup for one state-action pair."""
    reward = mdp["rewards"][state][action]
    if action == "Move":
        return reward  # the episode ends; Delivered has value 0 afterwards
    future = sum(prob * values[nxt]
                 for nxt, prob in mdp["wait_transition"][state].items())
    return reward + mdp["params"]["gamma"] * future


def value_iteration(mdp, theta=1e-9, max_iter=10_000, keep=3):
    """Repeat Bellman updates until V stops changing; keep the first sweeps for display."""
    values = {s: 0.0 for s in STATES}
    sweeps = [{"iteration": 0, **values}]
    for iteration in range(1, max_iter + 1):
        q = {s: {a: q_value(mdp, s, a, values) for a in ACTIONS} for s in STATES}
        new_values = {s: max(q[s].values()) for s in STATES}
        delta = max(abs(new_values[s] - values[s]) for s in STATES)
        values = new_values
        if iteration <= keep:
            sweeps.append({"iteration": iteration, **values})
        if delta < theta:
            break
    else:
        raise RuntimeError("Value iteration did not converge")
    q = {s: {a: q_value(mdp, s, a, values) for a in ACTIONS} for s in STATES}
    policy = {s: max(ACTIONS, key=lambda a, s=s: q[s][a]) for s in STATES}
    return {"values": values, "q": q, "policy": policy,
            "iterations": iteration, "sweeps": sweeps}


def belief_q(solution, belief_blocked):
    """Q_b(a) = (1 - b) Q(Clear, a) + b Q(Blocked, a)."""
    if not 0.0 <= belief_blocked <= 1.0:
        raise ValueError("belief must be a probability")
    q = solution["q"]
    return {a: (1.0 - belief_blocked) * q["Clear"][a] + belief_blocked * q["Blocked"][a]
            for a in ACTIONS}


def choose_action(solution, belief_blocked):
    scores = belief_q(solution, belief_blocked)
    best = "Move" if scores["Move"] >= scores["Wait"] else "Wait"  # tie -> Move
    return best, scores


def threshold(solution):
    """Belief b* where Move and Wait score the same.

    Q_b is linear in b for both actions, so b* solves
    (1-b) Qc_m + b Qb_m = (1-b) Qc_w + b Qb_w.  Returns None if one action
    is best for every belief. The winning side depends on the supplied Q values;
    choose_action compares them directly and resolves exact ties in favor of Move.
    """
    q = solution["q"]
    gap_clear = q["Clear"]["Move"] - q["Clear"]["Wait"]
    gap_blocked = q["Blocked"]["Move"] - q["Blocked"]["Wait"]
    if gap_clear == gap_blocked:
        return None
    b = gap_clear / (gap_clear - gap_blocked)
    return b if 0.0 <= b <= 1.0 else None
