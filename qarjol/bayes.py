"""Part 2 - probabilistic reasoning: Bayesian update of P(passage blocked) (Week 6).

Hidden variable: the courtyard passage P is BLOCKED by snow or CLEAR.
Evidence: one reading from a cheap snow-depth sensor on a lamp post next to
P. The sensor is noisy, so we keep a probability instead of trusting it.

    P(Blocked | reading) = P(reading | Blocked) P(Blocked) / P(reading)
    P(reading) = P(reading | Blocked) P(Blocked) + P(reading | Clear) P(Clear)

All numbers are hypothetical classroom assumptions (no real sensor data).
"""

# Prior: the morning forecast says snowfall overnight, so 30 % of such
# mornings start with the passage drifted shut (assumption).
PRIOR_BLOCKED = 0.30

# Sensor model P(reading | state). Rows sum to 1 for each state.
SENSOR = {
    "Blocked": {"SNOW": 0.85, "CLEAR": 0.15},  # hit rate 85 %
    "Clear": {"SNOW": 0.15, "CLEAR": 0.85},    # false-alarm rate 15 %
}
READINGS = ("SNOW", "CLEAR")


def _check_probability(name, value):
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, got {value}")


def bayes_update(prior_blocked, reading, sensor=SENSOR):
    """One Bayesian update; returns every intermediate number for display."""
    _check_probability("prior_blocked", prior_blocked)
    if reading not in READINGS:
        raise ValueError(f"reading must be one of {READINGS}, got {reading!r}")
    for state in ("Blocked", "Clear"):
        row = sensor[state]
        for observation in READINGS:
            _check_probability(f"P({observation}|{state})", row[observation])
        if abs(row["SNOW"] + row["CLEAR"] - 1.0) > 1e-9:
            raise ValueError(f"sensor row for {state} must sum to 1")

    likelihood_blocked = sensor["Blocked"][reading]
    likelihood_clear = sensor["Clear"][reading]
    joint_blocked = likelihood_blocked * prior_blocked
    joint_clear = likelihood_clear * (1.0 - prior_blocked)
    evidence = joint_blocked + joint_clear
    if evidence == 0.0:
        raise ValueError("The reading has zero probability under the model")
    posterior = joint_blocked / evidence
    return {
        "prior_blocked": prior_blocked,
        "reading": reading,
        "likelihood_blocked": likelihood_blocked,
        "likelihood_clear": likelihood_clear,
        "joint_blocked": joint_blocked,
        "joint_clear": joint_clear,
        "evidence": evidence,
        "posterior_blocked": posterior,
    }


def predict(belief_blocked, transition):
    """Belief after waiting one minute, before the next reading.

    P(Blocked next) = P(Blocked) * P(stays blocked) + P(Clear) * P(new drift),
    using the MDP's Wait transition table transition[s][s2].
    """
    _check_probability("belief_blocked", belief_blocked)
    return (belief_blocked * transition["Blocked"]["Blocked"]
            + (1.0 - belief_blocked) * transition["Clear"]["Blocked"])
