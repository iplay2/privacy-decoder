# Privacy Risk Score — 0 (safest) to 100 (most dangerous)
# Each of the 12 analysis categories is weighted by how much it matters to the user.
# Claude returns low/medium/high per category; we convert to 1/2/3, multiply by weight,
# sum, then normalise to 0-100.  Letter grade (A-F) is derived from the final score.
#
# Data Collection is special: its risk level is computed directly from the 39-question
# matrix using compute_dc_risk(), then injected before compute_privacy_score() runs.

CATEGORY_WEIGHTS: dict[str, int] = {
    "Data Selling":                 12,   # worst violation — your data as a product
    "Third-Party Sharing":          11,   # who else gets your data
    "Right to Delete":              10,   # your most basic protection
    "Sensitive Data":               10,   # biometrics, health, financial
    "User Profiling":                9,   # building a dossier on you
    "Third-Party Profile Access":    9,   # others buying your profile
    "Government & Legal Disclosure": 9,   # state access to your life
    "Data Collection":               8,   # breadth of what they take
    "Data Retention":                8,   # how long they keep it
    "Targeted Advertising":          7,   # monetisation of attention
    "Children's Data":               7,   # elevated concern if applicable
    "Policy Change Rights":          6,   # can they change the rules on you
}

_DEFAULT_WEIGHT = 8          # fallback if a future category name isn't listed
_RISK_VALUE     = {"low": 1, "medium": 2, "high": 3}
_TOTAL_WEIGHT   = sum(CATEGORY_WEIGHTS.values())   # 105
_MIN_RAW        = _TOTAL_WEIGHT                    # all low  → 105
_MAX_RAW        = _TOTAL_WEIGHT * 3                # all high → 315


def compute_privacy_score(categories) -> tuple[int, str]:
    """
    Given a list of CategoryResult-like objects (each with .name and .risk),
    return (score, grade) where:
      score  — integer 0-100 (higher = more harmful to the user)
      grade  — letter A / B / C / D / F
    """
    raw = sum(
        _RISK_VALUE.get(cat.risk, 2) * CATEGORY_WEIGHTS.get(cat.name, _DEFAULT_WEIGHT)
        for cat in categories
    )
    score = round((raw - _MIN_RAW) / (_MAX_RAW - _MIN_RAW) * 100)
    score = max(0, min(100, score))

    if score <= 20:
        grade = "A"
    elif score <= 40:
        grade = "B"
    elif score <= 60:
        grade = "C"
    elif score <= 75:
        grade = "D"
    else:
        grade = "F"

    return score, grade


# ── Data Collection matrix scoring ───────────────────────────────────────────
#
# Model: collection is the baseline risk; third-party sharing is the dominant
# threat because once data leaves the collecting company the user has zero
# visibility, zero recourse, and the data can propagate through an unlimited
# chain of third-party contracts the user never agreed to.
#
#   per_question = (collection_value × W_COLLECT)
#                + (collection_value × third_party_value × W_SHARE)
#
# The sharing component is conditional on collection (can't share what you
# don't collect) and weighted 4× heavier than collection alone.

_DC_RATING_VALUES: dict[str, float] = {
    "Yes":      1.00,   # explicitly confirmed
    "Likely":   0.75,   # vague language — almost certain
    "Unknown":  0.50,   # silence is not innocence; raised deliberately
    "Unlikely": 0.15,   # implied no, not guaranteed
    "No":       0.00,   # explicitly prohibited
}

# Sensitivity weights for each of the 9 DC sub-categories.
# Averaged per category before weighting so question count doesn't distort results.
_DC_CATEGORY_WEIGHTS: dict[str, int] = {
    "Behavior":     10,   # inferring beliefs, emotions, predicting actions
    "Health":       10,   # biometrics, conditions — most protected class
    "Financial":     9,   # purchases, income, economic profiling
    "Social Graph":  8,   # profiling people who never consented
    "Location":      8,   # movement patterns, home/work inference
    "Audio":         7,   # ambient listening, voiceprint ID
    "Video":         6,   # real-time camera access
    "Photos":        5,   # less intrusive than live video/audio
    "Device":        4,   # least sensitive
}
_DC_DEFAULT_WEIGHT = 5   # fallback for unexpected categories

_W_COLLECT = 1   # collection component weight  — baseline risk
_W_SHARE   = 4   # sharing component weight     — dominant risk (4× heavier)
_Q_MAX     = _W_COLLECT * 1.0 + _W_SHARE * 1.0   # 5.0 per question at Yes/Yes


def compute_dc_risk(dc_answers) -> str | None:
    """
    Compute the Data Collection risk level (low / medium / high) directly from
    the 39-question matrix answers.

    Returns None if no answers are provided (falls back to Claude's judgment).

    Thresholds (0-100 normalised):
      0–30  → low    (limited collection, data mostly kept in-house)
      31–65 → medium (meaningful collection or some third-party exposure)
      66–100 → high  (broad collection with significant third-party sharing)
    """
    if not dc_answers:
        return None

    # Group answers by sub-category
    groups: dict[str, list] = {}
    for answer in dc_answers:
        groups.setdefault(answer.category, []).append(answer)

    weighted_sum = 0.0
    max_weighted_sum = 0.0

    for cat, answers in groups.items():
        weight = _DC_CATEGORY_WEIGHTS.get(cat, _DC_DEFAULT_WEIGHT)

        q_scores = []
        for a in answers:
            cv = _DC_RATING_VALUES.get(a.can_do, 0.50)       # collection value
            tv = _DC_RATING_VALUES.get(a.third_party, 0.50)  # third-party value

            # Sharing is conditional: you can't share what you don't collect
            collection_pts = cv * _W_COLLECT
            sharing_pts    = cv * tv * _W_SHARE

            q_scores.append(collection_pts + sharing_pts)

        # Average within category (normalises for different question counts)
        cat_avg = sum(q_scores) / len(q_scores)

        weighted_sum     += cat_avg  * weight
        max_weighted_sum += _Q_MAX   * weight

    if max_weighted_sum == 0:
        return "medium"

    score = (weighted_sum / max_weighted_sum) * 100

    if score <= 30:
        return "low"
    elif score <= 65:
        return "medium"
    else:
        return "high"
