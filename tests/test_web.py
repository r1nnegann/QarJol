"""Tests for the web interface layer (qarjol/web_api.py and app.py).

The web page must show exactly the numbers the console prints, so these tests
compare the JSON views with the hand-checked values from the README.
"""

import json
import os
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qarjol import web_api  # noqa: E402
import app  # noqa: E402


class TestWebApi(unittest.TestCase):
    def test_default_morning_matches_console(self):
        s = web_api.scenario(0.30, 0.50, ["SNOW", "CLEAR"])
        json.dumps(s)  # must be JSON-ready
        m0, m1 = s["minutes"]
        self.assertAlmostEqual(m0["belief"], 0.7083, places=4)
        self.assertEqual(m0["action"], "Wait")
        self.assertAlmostEqual(m0["next_prior"], 0.3833, places=4)
        self.assertAlmostEqual(m1["belief"], 0.0989, places=4)
        self.assertEqual(m1["action"], "Move")
        self.assertEqual(s["result"], {**s["result"], "status": "move", "waited": 1})
        self.assertEqual(s["search"]["shortcut"]["cost"], 8)
        self.assertEqual(s["search"]["stuck_steps"], 14)
        self.assertEqual(s["search"]["shortcut"]["expanded"], 13)
        self.assertEqual(s["search"]["ucs"]["expanded"], 24)
        self.assertAlmostEqual(s["mdp"]["threshold"], 0.2410, places=4)
        self.assertEqual(s["mdp"]["iterations"], 32)
        self.assertEqual(len(s["mdp"]["sweeps"]), 33)  # sweep 0 .. 32

    def test_slow_plow_moves(self):
        s = web_api.scenario(0.30, 0.10, "SNOW")
        e = s["minutes"][0]
        self.assertAlmostEqual(e["scores"]["Wait"], 4.700, places=3)
        self.assertAlmostEqual(e["scores"]["Move"], 5.625, places=3)
        self.assertEqual(e["action"], "Move")
        self.assertIsNone(s["mdp"]["threshold"])

    def test_waiting_and_empty(self):
        self.assertEqual(web_api.scenario(0.30, 0.50, ["SNOW"])["result"]["status"], "waiting")
        self.assertEqual(web_api.scenario(0.30, 0.50, [])["result"]["status"], "no_reading")

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            web_api.scenario(1.5, 0.5, ["SNOW"])
        with self.assertRaises(ValueError):
            web_api.scenario(0.3, 0.5, ["RAIN"])
        with self.assertRaises(ValueError):
            web_api.evaluate(0)

    def test_evaluation_matches_console(self):
        ev = web_api.evaluate(10_000)
        normal = {r["policy"]: r["avg_reward"] for r in ev["scenarios"][0]["results"]}
        self.assertAlmostEqual(normal["agent"], 10.624, places=3)
        self.assertAlmostEqual(normal["always_move"], 9.283, places=3)
        self.assertEqual(len(ev["scenarios"]), 3)
        self.assertEqual(len(web_api.evaluate(100, prior=0.2, plow=0.3)["scenarios"]), 4)

    def test_random_morning_is_reproducible(self):
        a = web_api.random_morning(0.30, 0.50, seed=11)
        b = web_api.random_morning(0.30, 0.50, seed=11)
        self.assertEqual(a, b)
        self.assertEqual(a["steps"][-1]["action"], "Move")
        self.assertIn(a["travel_steps"], (8, 14))
        self.assertEqual(a["total_minutes"], a["wait_minutes"] + a["travel_steps"])


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = app.make_server("127.0.0.1", 8790, tries=50)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path):
        with urlopen(self.base + path, timeout=10) as r:
            return r.status, r.read()

    def test_page_and_api(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"QarJol", body)
        status, body = self.get("/api/scenario?prior=0.3&plow=0.5&readings=SNOW,CLEAR")
        self.assertEqual(json.loads(body)["result"]["status"], "move")
        status, body = self.get("/qarjol/agent.py")
        self.assertIn(b"class QarJolAgent", body)

    def test_bad_request(self):
        with self.assertRaises(HTTPError) as ctx:
            self.get("/api/scenario?prior=2")
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
