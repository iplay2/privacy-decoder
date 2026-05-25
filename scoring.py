# Privacy Risk Score — 0 (safest) to 100 (most dangerous)
# Each of the 12 analysis categories is weighted by how much it matters to the user.
# Claude returns low/medium/high per category; we convert to 1/2/3, multiply by weight,
# sum, then normalise to 0-100.  Letter grade (A-F) is derived from the final score.

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
