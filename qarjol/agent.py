"""The QarJol agent: A* -> Bayes -> MDP working toward one goal (deliver the parcel).

1. A* plans the shortcut and the "stuck" re-plan; their lengths become MDP rewards.
2. Value iteration solves the small MDP and gives Q(s, a) for Move and Wait.
3. Each minute the snow sensor gives a reading; Bayes turns it into
   b = P(Blocked), and the robot picks the action with the larger Q_b.
4. If it waits, the belief is updated with the Wait transition table and the
   next reading is processed the same way.

The evaluation simulates many random winter mornings and compares the agent
with simple fixed rules. Randomness is seeded, so results are reproducible.
"""

import random

from . import bayes, mdp
from .campus import Campus
from .search import plan_routes


class QarJolAgent:
    def __init__(self, campus=None, prior_blocked=bayes.PRIOR_BLOCKED,
                 sensor=bayes.SENSOR, **mdp_params):
        self.campus = campus or Campus()
        self.prior_blocked = prior_blocked
        self.sensor = sensor
        self.routes = plan_routes(self.campus)
        self.mdp = mdp.build_mdp(self.routes, **mdp_params)
        self.solution = mdp.value_iteration(self.mdp)

    def run(self, readings):
        """Process a list of sensor readings, one per minute.

        Stops at the first Move. If the readings run out while the agent still
        wants to wait, the log ends with 'Wait'.
        """
        belief = self.prior_blocked
        log = []
        for minute, reading in enumerate(readings):
            prior_now = belief
            update = bayes.bayes_update(prior_now, reading, self.sensor)
            belief = update["posterior_blocked"]
            action, scores = mdp.choose_action(self.solution, belief)
            entry = {"minute": minute, "prior": prior_now, "reading": reading,
                     "bayes": update, "belief": belief, "scores": scores,
                     "action": action}
            log.append(entry)
            if action == "Move":
                entry["route"] = self.routes["shortcut"]["path"]
                entry["route_if_blocked"] = self.routes["stuck_path"]
                break
            belief = bayes.predict(belief, self.mdp["wait_transition"])
            entry["next_prior"] = belief
        return log


# ----------------------------------------------------------------- evaluation

POLICIES = ("agent", "always_move", "trust_sensor")


def simulate(policy_name, agent, mornings=10_000, seed=2026, max_wait=10):
    """Average minutes to delivery, average reward and stuck rate for one policy.

    agent         Bayes + MDP (this project)
    always_move   ignore the sensor, always go through P at once
    trust_sensor  no Bayes: SNOW -> Wait, CLEAR -> Move
    The true passage state is drawn from the prior; while a robot waits the
    state changes with the MDP Wait transition. After max_wait minutes every
    policy moves. Reward is undiscounted here so the columns are easy to read.
    """
    if policy_name not in POLICIES:
        raise ValueError(f"Unknown policy {policy_name!r}")
    if isinstance(mornings, bool) or not isinstance(mornings, int) or mornings <= 0:
        raise ValueError("mornings must be a positive integer")
    if isinstance(max_wait, bool) or not isinstance(max_wait, int) or max_wait < 0:
        raise ValueError("max_wait must be a non-negative integer")
    rng = random.Random(seed)
    params = agent.mdp["params"]
    transition = agent.mdp["wait_transition"]
    routes = agent.routes
    total_minutes = total_reward = stuck_count = 0.0

    for _ in range(mornings):
        state = "Blocked" if rng.random() < agent.prior_blocked else "Clear"
        belief = agent.prior_blocked
        minutes, reward = 0, 0.0
        for wait_round in range(max_wait + 1):
            reading = "SNOW" if rng.random() < agent.sensor[state]["SNOW"] else "CLEAR"
            if policy_name == "agent":
                belief = bayes.bayes_update(belief, reading, agent.sensor)["posterior_blocked"]
                action, _ = mdp.choose_action(agent.solution, belief)
            elif policy_name == "always_move":
                action = "Move"
            else:  # trust_sensor
                action = "Wait" if reading == "SNOW" else "Move"
            if wait_round == max_wait:
                action = "Move"  # safety cap: never wait forever

            if action == "Wait":
                minutes += 1
                reward -= params["wait_cost"]
                state = "Blocked" if rng.random() < transition[state]["Blocked"] else "Clear"
                belief = bayes.predict(belief, transition)
                continue
            if state == "Clear":
                steps = routes["shortcut"]["cost"]
                reward += params["delivery_reward"] - params["step_cost"] * steps
            else:
                steps = routes["stuck_steps"]
                stuck_count += 1
                reward += (params["delivery_reward"] - params["step_cost"] * steps
                           - params["stuck_penalty"])
            minutes += steps
            break
        total_minutes += minutes
        total_reward += reward

    return {"policy": policy_name, "mornings": mornings, "seed": seed,
            "avg_minutes": total_minutes / mornings,
            "avg_reward": total_reward / mornings,
            "stuck_rate": stuck_count / mornings}


def compare_policies(agent, mornings=10_000, seed=2026):
    return [simulate(name, agent, mornings, seed) for name in POLICIES]
