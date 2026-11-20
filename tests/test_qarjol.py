"""Test cases for QarJol. Run:  python -m unittest discover -s tests -v

Expected numbers were worked out by hand (see README, "Hand check").
"""

import os
import sys
import unittest
from collections import deque
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qarjol import bayes, mdp  # noqa: E402
from qarjol.agent import QarJolAgent, compare_policies, simulate  # noqa: E402
from qarjol.campus import Campus  # noqa: E402
from qarjol.search import astar, plan_routes, uniform_cost  # noqa: E402
from main import main  # noqa: E402


def bfs_length(campus, start, goal, closed=frozenset()):
    """Independent breadth-first check of shortest path lengths."""
    frontier, seen = deque([(start, 0)]), {start}
    while frontier:
        cell, dist = frontier.popleft()
        if cell == goal:
            return dist
        for nxt in campus.neighbors(cell, closed):
            if nxt not in seen:
                seen.add(nxt)
                frontier.append((nxt, dist + 1))
    return None


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.campus = Campus()
        self.routes = plan_routes(self.campus)

    def test_route_lengths(self):
        self.assertEqual(self.routes["shortcut"]["cost"], 8)
        self.assertEqual(self.routes["replan_from"], (3, 5))
        self.assertEqual(self.routes["steps_to_turn_back"], 3)
        self.assertEqual(self.routes["replan"]["cost"], 11)
        self.assertEqual(self.routes["stuck_steps"], 14)

    def test_astar_is_optimal_against_bfs(self):
        c = self.campus
        self.assertEqual(self.routes["shortcut"]["cost"], bfs_length(c, c.start, c.goal))
        self.assertEqual(self.routes["replan"]["cost"],
                         bfs_length(c, (3, 5), c.goal, {c.passage}))

    def test_paths_are_valid_walks(self):
        c = self.campus
        for path, closed in ((self.routes["shortcut"]["path"], frozenset()),
                             (self.routes["replan"]["path"], frozenset({c.passage}))):
            self.assertEqual(path[-1], c.goal)
            for a, b in zip(path, path[1:]):
                self.assertEqual(abs(a[0] - b[0]) + abs(a[1] - b[1]), 1)
                self.assertTrue(c.walkable(b, closed))
        self.assertIn(c.passage, self.routes["shortcut"]["path"])
        self.assertNotIn(c.passage, self.routes["replan"]["path"])

    def test_heuristic_saves_work(self):
        ucs = uniform_cost(self.campus)
        self.assertEqual(ucs["cost"], self.routes["shortcut"]["cost"])
        self.assertLess(self.routes["shortcut"]["expanded"], ucs["expanded"])

    def test_no_route_when_goal_walled_in(self):
        self.assertIsNone(astar(Campus(("S.#G", "..#.", "P.#.")))["path"])


class TestBayes(unittest.TestCase):
    def test_snow_reading(self):
        u = bayes.bayes_update(0.30, "SNOW")
        self.assertAlmostEqual(u["joint_blocked"], 0.255)
        self.assertAlmostEqual(u["joint_clear"], 0.105)
        self.assertAlmostEqual(u["evidence"], 0.36)
        self.assertAlmostEqual(u["posterior_blocked"], 0.255 / 0.36)  # 0.708333

    def test_clear_reading(self):
        u = bayes.bayes_update(0.30, "CLEAR")
        self.assertAlmostEqual(u["posterior_blocked"], 0.045 / 0.64)  # 0.0703125

    def test_uninformative_sensor_keeps_prior(self):
        coin = {"Blocked": {"SNOW": 0.5, "CLEAR": 0.5}, "Clear": {"SNOW": 0.5, "CLEAR": 0.5}}
        self.assertAlmostEqual(bayes.bayes_update(0.3, "SNOW", coin)["posterior_blocked"], 0.3)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            bayes.bayes_update(1.2, "SNOW")
        with self.assertRaises(ValueError):
            bayes.bayes_update(0.3, "RAIN")

    def test_belief_after_waiting(self):
        t = {"Clear": {"Clear": 0.9, "Blocked": 0.1}, "Blocked": {"Clear": 0.5, "Blocked": 0.5}}
        self.assertAlmostEqual(bayes.predict(0.7, t), 0.7 * 0.5 + 0.3 * 0.1)

    def test_invalid_sensor_probabilities_are_rejected(self):
        for bad in (float("nan"), float("inf"), -1e-10, 1.1):
            for reading in bayes.READINGS:
                with self.subTest(bad=bad, reading=reading):
                    sensor = {state: dict(row) for state, row in bayes.SENSOR.items()}
                    sensor["Blocked"][reading] = bad
                    if bad == -1e-10:
                        other = "CLEAR" if reading == "SNOW" else "SNOW"
                        sensor["Blocked"][other] = 1.0
                    with self.assertRaises(ValueError):
                        bayes.bayes_update(0.3, reading, sensor)


class TestMDP(unittest.TestCase):
    def setUp(self):
        self.routes = plan_routes(Campus())

    def test_rewards_come_from_routes(self):
        r = mdp.build_mdp(self.routes)["rewards"]
        self.assertEqual(r["Clear"]["Move"], 12)    # 20 - 8
        self.assertEqual(r["Blocked"]["Move"], 3)   # 20 - 14 - 3
        self.assertEqual(r["Clear"]["Wait"], -1)

    def test_values_satisfy_bellman_equation(self):
        sol = mdp.value_iteration(mdp.build_mdp(self.routes))
        # Wait is best when Blocked: V(B) = -1 + 0.95 * (0.5 * 12 + 0.5 * V(B))
        # => V(B) = 4.7 / 0.525 = 8.952381
        self.assertAlmostEqual(sol["values"]["Clear"], 12.0, places=6)
        self.assertAlmostEqual(sol["values"]["Blocked"], 4.7 / 0.525, places=6)
        self.assertAlmostEqual(sol["q"]["Clear"]["Wait"],
                               -1 + 0.95 * (0.9 * 12 + 0.1 * 4.7 / 0.525), places=6)
        for s in mdp.STATES:
            self.assertAlmostEqual(sol["values"][s], max(sol["q"][s].values()), places=6)

    def test_policy_normal_day_and_blizzard(self):
        normal = mdp.value_iteration(mdp.build_mdp(self.routes))
        self.assertEqual(normal["policy"], {"Clear": "Move", "Blocked": "Wait"})
        blizzard = mdp.value_iteration(mdp.build_mdp(self.routes, p_plow_clears=0.1))
        self.assertEqual(blizzard["policy"], {"Clear": "Move", "Blocked": "Move"})

    def test_threshold(self):
        normal = mdp.value_iteration(mdp.build_mdp(self.routes))
        b_star = mdp.threshold(normal)
        self.assertAlmostEqual(b_star, 0.240952, places=5)
        self.assertEqual(mdp.choose_action(normal, b_star - 0.01)[0], "Move")
        self.assertEqual(mdp.choose_action(normal, b_star + 0.01)[0], "Wait")
        blizzard = mdp.value_iteration(mdp.build_mdp(self.routes, p_plow_clears=0.1))
        self.assertIsNone(mdp.threshold(blizzard))

    def test_unknown_parameter_rejected(self):
        with self.assertRaises(ValueError):
            mdp.build_mdp(self.routes, gama=0.9)

    def test_equal_action_scores_prefer_move(self):
        tied = {"q": {"Clear": {"Move": 12.0, "Wait": 10.0},
                      "Blocked": {"Move": 3.0, "Wait": 5.0}}}
        action, scores = mdp.choose_action(tied, 0.5)
        self.assertEqual(scores["Move"], scores["Wait"])
        self.assertEqual(action, "Move")


class TestAgent(unittest.TestCase):
    def test_clear_reading_moves_at_once(self):
        log = QarJolAgent().run(["CLEAR"])
        self.assertEqual([e["action"] for e in log], ["Move"])
        self.assertEqual(len(log[0]["route"]) - 1, 8)

    def test_snow_then_clear_waits_then_moves(self):
        log = QarJolAgent().run(["SNOW", "CLEAR"])
        self.assertEqual([e["action"] for e in log], ["Wait", "Move"])
        b0 = 0.255 / 0.36
        self.assertAlmostEqual(log[0]["next_prior"], b0 * 0.5 + (1 - b0) * 0.1)  # 0.383333
        b1 = b0 * 0.5 + (1 - b0) * 0.1
        expected = 0.15 * b1 / (0.15 * b1 + 0.85 * (1 - b1))  # 0.0575 / 0.581667
        self.assertAlmostEqual(log[1]["belief"], expected)  # 0.098854

    def test_clear_forecast_ignores_one_false_alarm(self):
        log = QarJolAgent(prior_blocked=0.05).run(["SNOW"])
        self.assertAlmostEqual(log[0]["belief"], 0.0425 / 0.185)  # 0.229730 < 0.2410
        self.assertEqual(log[0]["action"], "Move")

    def test_blizzard_snow_moves_anyway(self):
        log = QarJolAgent(p_plow_clears=0.1).run(["SNOW"])
        self.assertEqual(log[0]["action"], "Move")

    def test_agent_never_worse_than_fixed_rules(self):
        for kwargs in ({}, {"prior_blocked": 0.05}, {"p_plow_clears": 0.1}):
            results = {r["policy"]: r["avg_reward"]
                       for r in compare_policies(QarJolAgent(**kwargs), mornings=3000)}
            best_rule = max(v for k, v in results.items() if k != "agent")
            self.assertGreaterEqual(results["agent"], best_rule - 1e-9, kwargs)

    def test_simulation_is_reproducible(self):
        a = compare_policies(QarJolAgent(), mornings=500, seed=7)
        b = compare_policies(QarJolAgent(), mornings=500, seed=7)
        self.assertEqual(a, b)

    def test_simulation_rejects_invalid_counts(self):
        agent = QarJolAgent()
        for count in (0, -1, 1.5, True):
            with self.subTest(mornings=count), self.assertRaises(ValueError):
                simulate("agent", agent, mornings=count)
        for cap in (-1, 1.5, True):
            with self.subTest(max_wait=cap), self.assertRaises(ValueError):
                simulate("agent", agent, mornings=1, max_wait=cap)
        result = simulate("agent", agent, mornings=1, max_wait=0)
        self.assertIn(result["avg_minutes"], (8, 14))


class TestCLI(unittest.TestCase):
    def test_invalid_numeric_arguments_fail_before_output(self):
        for args in (["--evaluate", "--mornings", "0"],
                     ["--evaluate", "--mornings", "-1"],
                     ["--prior", "1.2"], ["--prior", "nan"],
                     ["--plow", "-0.1"], ["--plow", "inf"]):
            with self.subTest(args=args):
                output, error = StringIO(), StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    with self.assertRaises(SystemExit) as raised:
                        main(args)
                self.assertEqual(raised.exception.code, 2)
                self.assertEqual(output.getvalue(), "")
                self.assertIn("error:", error.getvalue())


if __name__ == "__main__":
    unittest.main()
