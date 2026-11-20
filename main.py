"""QarJol - winter campus courier robot. Console demo for the AIF1303 Final Project.

Run:   python main.py                       # default morning: SNOW, then CLEAR
       python main.py --readings CLEAR      # the sensor says CLEAR
       python main.py --plow 0.1            # blizzard: the snowplow is slow
       python main.py --evaluate            # add the 10,000-morning comparison

Standard library only (Python 3.9+).
"""

import argparse

from qarjol import bayes, mdp
from qarjol.agent import QarJolAgent, compare_policies
from qarjol.search import uniform_cost

LINE = "=" * 72


def header(title):
    print(f"\n{LINE}\n{title}\n{LINE}")


def fmt_path(path):
    return " -> ".join(f"({r},{c})" for r, c in path)


def part_search(agent):
    campus, routes = agent.campus, agent.routes
    header("PART 1 - A* SEARCH: which route can the robot take?")
    print("INPUT   6x6 campus grid, 4-connected moves, cost 1 per step,")
    print(f"        start S={campus.start}, goal G={campus.goal}, "
          f"snow-prone passage P={campus.passage}")
    print("        heuristic h(n) = Manhattan distance to G (admissible)\n")
    print(campus.render())
    print("\nSTEPS   A* expansions for the shortcut (node, g, h, f = g + h):")
    for row in routes["shortcut"]["trace"]:
        print(f"        {str(row['node']):7} g={row['g']:<2} h={row['h']:<2} f={row['f']:<2}")
    ucs = uniform_cost(campus)
    print(f"\n        A* expanded {routes['shortcut']['expanded']} nodes; uniform-cost search "
          f"(h=0) expanded {ucs['expanded']} for the same length {ucs['cost']}.")
    print(f"\nOUTPUT  shortcut through P ({routes['shortcut']['cost']} steps): "
          f"{fmt_path(routes['shortcut']['path'])}")
    print(campus.render(routes["shortcut"]["path"]))
    print(f"\n        if P is blocked, the robot sees it at {routes['replan_from']} after "
          f"{routes['steps_to_turn_back']} steps and A* re-plans without P: "
          f"total {routes['stuck_steps']} steps")
    print(campus.render(routes["stuck_path"], closed={campus.passage}))
    print("EXPLAIN A* finds the shortest routes, and their lengths become the rewards of"
          "\n        the MDP; the Manhattan heuristic lets it skip useless cells.")


def part_bayes(agent, reading):
    header("PART 2 - BAYES: is the passage blocked by snow?")
    u = bayes.bayes_update(agent.prior_blocked, reading, agent.sensor)
    s = agent.sensor
    print(f"INPUT   prior P(Blocked) = {u['prior_blocked']:.2f} (overnight snow forecast)")
    print(f"        sensor: P(SNOW|Blocked) = {s['Blocked']['SNOW']:.2f}, "
          f"P(SNOW|Clear) = {s['Clear']['SNOW']:.2f}")
    print(f"        observed reading = {u['reading']}")
    print("STEPS   P(reading|Blocked) * P(Blocked) = "
          f"{u['likelihood_blocked']:.2f} * {u['prior_blocked']:.2f} = {u['joint_blocked']:.4f}")
    print("        P(reading|Clear)   * P(Clear)   = "
          f"{u['likelihood_clear']:.2f} * {1 - u['prior_blocked']:.2f} = {u['joint_clear']:.4f}")
    print(f"        P(reading) = {u['joint_blocked']:.4f} + {u['joint_clear']:.4f} "
          f"= {u['evidence']:.4f}")
    print(f"OUTPUT  P(Blocked | {u['reading']}) = {u['joint_blocked']:.4f} / "
          f"{u['evidence']:.4f} = {u['posterior_blocked']:.4f}")
    print("EXPLAIN Bayes combines the forecast with a noisy sensor, so the robot neither"
          "\n        trusts one reading blindly nor ignores it.")


def part_mdp(agent):
    header("PART 3 - MDP: Move now or Wait for the snowplow?")
    m, sol = agent.mdp, agent.solution
    p = m["params"]
    print("INPUT   states Clear / Blocked (+ terminal Delivered); actions Move, Wait")
    print(f"        delivery +{p['delivery_reward']:g}, step -{p['step_cost']:g}, "
          f"stuck penalty -{p['stuck_penalty']:g}, wait -{p['wait_cost']:g}, "
          f"gamma {p['gamma']}")
    print(f"        Wait transitions: Clear->Blocked {p['p_new_drift']:.2f} (new drift), "
          f"Blocked->Clear {p['p_plow_clears']:.2f} (snowplow)")
    print("        rewards R(s,a) from the A* route lengths:")
    r = m["rewards"]
    print(f"          R(Clear, Move)   = 20 - {agent.routes['shortcut']['cost']} "
          f"= {r['Clear']['Move']:+.0f}")
    print(f"          R(Blocked, Move) = 20 - {agent.routes['stuck_steps']} - 3 "
          f"= {r['Blocked']['Move']:+.0f}")
    print(f"          R(any, Wait)     = {r['Clear']['Wait']:+.0f}")
    print("STEPS   value iteration: V(s) = max_a [R(s,a) + gamma * sum T(s,a,s') V(s')]")
    for sweep in sol["sweeps"]:
        print(f"          sweep {sweep['iteration']}: V(Clear)={sweep['Clear']:.4f}  "
              f"V(Blocked)={sweep['Blocked']:.4f}")
    print(f"          ... converged after {sol['iterations']} sweeps")
    for s in mdp.STATES:
        cells = ", ".join(f"{a} {sol['q'][s][a]:.4f}" for a in mdp.ACTIONS)
        print(f"          Q({s}, .) = {cells}  -> best {sol['policy'][s]}")
    b_star = mdp.threshold(sol)
    print("OUTPUT  if the state were known: " +
          ", ".join(f"{s} -> {sol['policy'][s]}" for s in mdp.STATES))
    if b_star is None:
        only = mdp.choose_action(sol, 0.5)[0]
        print(f"        with belief b = P(Blocked): {only} is best for every b")
    else:
        below = mdp.choose_action(sol, 0.0)[0]
        above = mdp.choose_action(sol, 1.0)[0]
        print(f"        score crossover b ~= {b_star:.4f} (rounded); compare full-precision Q_b")
        print(f"        below crossover: {below}; above: {above}; equal scores: Move")
    print("EXPLAIN The MDP weighs a quick delivery against getting stuck, and counts what"
          "\n        can happen while waiting (snowplow or new snow).")


def part_agent(agent, readings):
    header("TOGETHER - one winter morning, minute by minute")
    log = agent.run(readings)
    for e in log:
        scores = ", ".join(f"{a} {v:.3f}" for a, v in e["scores"].items())
        print(f"minute {e['minute']}: prior {e['prior']:.4f}, reading {e['reading']:5} "
              f"-> P(Blocked) {e['belief']:.4f}")
        print(f"          Q_b: {scores}  => {e['action']}")
        if "next_prior" in e:
            print(f"          waits 1 minute; P(Blocked) before the next reading "
                  f"{e['next_prior']:.4f}")
    last = log[-1]
    if last["action"] == "Wait":
        print("RESULT  still waiting: no more readings were given")
    else:
        print(f"RESULT  recommended Move after waiting {len(log) - 1} min; "
              f"planned shortcut if P is clear "
              f"({len(last['route']) - 1} steps): {fmt_path(last['route'])}")
        print(f"        if P is blocked on arrival: fallback route "
              f"({len(last['route_if_blocked']) - 1} steps)")
        print(agent.campus.render(last["route"]))


def part_evaluation(mornings):
    header(f"EVALUATION - {mornings:,} simulated mornings per scenario (seed 2026)")
    scenarios = (("normal day (prior 0.30, plow 0.5)", {}),
                 ("clear forecast (prior 0.05, plow 0.5)", {"prior_blocked": 0.05}),
                 ("blizzard (prior 0.30, plow 0.1)", {"p_plow_clears": 0.1}))
    for name, kwargs in scenarios:
        print(f"\n{name}")
        print(f"  {'policy':14} {'avg minutes':>12} {'avg reward':>11} {'stuck rate':>11}")
        for res in compare_policies(QarJolAgent(**kwargs), mornings):
            print(f"  {res['policy']:14} {res['avg_minutes']:12.3f} "
                  f"{res['avg_reward']:11.3f} {res['stuck_rate']:11.3f}")
    print("\nHigher reward is better. The simulation uses the same assumed model the"
          "\nagent uses, so it checks the decision logic, not real-world accuracy.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--readings", nargs="+", default=["SNOW", "CLEAR"],
                        choices=bayes.READINGS, help="sensor readings, one per minute")
    parser.add_argument("--prior", type=float, default=bayes.PRIOR_BLOCKED,
                        help="prior P(Blocked) from the forecast")
    parser.add_argument("--plow", type=float, default=mdp.DEFAULTS["p_plow_clears"],
                        help="P(Blocked -> Clear) during one minute of waiting")
    parser.add_argument("--evaluate", action="store_true",
                        help="also run the policy comparison simulation")
    parser.add_argument("--mornings", type=int, default=10_000)
    args = parser.parse_args(argv)
    if not 0.0 <= args.prior <= 1.0:
        parser.error("--prior must be between 0 and 1")
    if not 0.0 <= args.plow <= 1.0:
        parser.error("--plow must be between 0 and 1")
    if args.mornings <= 0:
        parser.error("--mornings must be a positive integer")

    agent = QarJolAgent(prior_blocked=args.prior, p_plow_clears=args.plow)
    print("QarJol: a winter campus courier robot (A* + Bayes + MDP)")
    print("All numbers are classroom assumptions; the map is a hypothetical campus.")
    part_search(agent)
    part_bayes(agent, args.readings[0])
    part_mdp(agent)
    part_agent(agent, args.readings)
    if args.evaluate:
        part_evaluation(args.mornings)


if __name__ == "__main__":
    main()
