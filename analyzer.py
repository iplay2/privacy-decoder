import os
from datetime import datetime, timezone

import anthropic
from models import AnalysisResult, CategoryResult, DataCollectionAnswer
from scoring import compute_privacy_score, compute_dc_risk

_client: anthropic.Anthropic | None = None

def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client

MAX_DOC_CHARS = int(os.getenv("MAX_DOC_CHARS", "150000"))

SYSTEM_PROMPT = """You are a privacy rights advocate helping everyday people understand exactly what they are signing away when they accept a Privacy Policy or EULA.

Your job is to read the legal document and produce a plain-English analysis written entirely from the USER'S perspective — what the company can do TO them and WITH their data.

Rules:
- Write every summary in second person ("they can see your photos", "you've given them the right to sell your location", "they can keep your data even after you delete your account").
- Be concrete and specific. Name the actual types of data, the actual actions the company can take. Avoid vague phrases like "certain information" or "may be used for various purposes."
- Give real examples of what the policy permits: "This means they can scan your text messages, see who you call, and track everywhere you go."
- Be conservative: if a clause is ambiguous, assume the worst-case interpretation for the user.
- Risk levels: "low" (you have real, enforceable protections), "medium" (vague or conditional — company has wiggle room), "high" (they can do a lot, you gave up significant rights).
- If a category is not addressed in the document at all, mark it "high" — silence favors the company.
- For quotes: pick the most alarming or revealing verbatim line from the document (under 200 characters).
- Keep each summary to 2–3 punchy sentences. No legal jargon. No hedging."""

CATEGORIES = [
    "Data Collection",
    "Data Selling",
    "Third-Party Sharing",
    "User Profiling",
    "Third-Party Profile Access",
    "Targeted Advertising",
    "Data Retention",
    "Right to Delete",
    "Government & Legal Disclosure",
    "Policy Change Rights",
    "Children's Data",
    "Sensitive Data",
]

# Tool schema — forces Claude to return structured, validated output
ANALYSIS_TOOL = {
    "name": "submit_privacy_analysis",
    "description": "Submit the structured privacy policy analysis result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "company": {"type": "string", "description": "Company name inferred from the document"},
            "document_date": {
                "type": "string",
                "description": (
                    "The revision or effective date of the document as stated in the document itself "
                    "(e.g. 'Last updated: January 1, 2024' → 'January 1, 2024'). "
                    "Use the document's own wording. Empty string if no date is found."
                ),
            },
            "overall_risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "overall_summary": {"type": "string", "description": "2-3 sentence plain-English verdict from the user's perspective — what you've actually signed away and what the company can do with it."},
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                        "summary": {"type": "string", "description": "2-3 punchy sentences written from the user's perspective: what the company can do to/with you and your data. Use 'they', 'you', concrete examples."},
                        "quote": {"type": "string", "description": "Short verbatim excerpt under 200 chars, or empty string if none"},
                    },
                    "required": ["name", "risk", "summary", "quote"],
                },
                "minItems": 12,
                "maxItems": 12,
            },
        },
        "required": ["company", "document_date", "overall_risk", "overall_summary", "categories"],
    },
}

# ── Data Collection matrix ────────────────────────────────────────────────────

DC_QUESTIONS = [
    #  id   category         question
    (  1, "Photos",        "Can they access and view all my photos?"),
    (  2, "Photos",        "Can they identify people in my photos?"),
    (  3, "Photos",        "Can they identify my pets in my photos?"),
    (  4, "Photos",        "Can they read GPS/location metadata embedded in my photos?"),
    (  5, "Photos",        "Can they identify other people's phones or devices visible in my photos?"),
    (  6, "Photos",        "Can they use my photos to train AI models?"),
    (  7, "Video",         "Can they access and watch my videos?"),
    (  8, "Video",         "Can they analyze the content of my videos?"),
    (  9, "Video",         "Can they identify people who appear in my videos?"),
    ( 10, "Video",         "Can they access my camera in real time without me actively recording?"),
    ( 11, "Audio",         "Can they listen through my microphone?"),
    ( 12, "Audio",         "Can they record my voice or conversations?"),
    ( 13, "Audio",         "Can they identify me by my voice (voiceprint)?"),
    ( 14, "Audio",         "Can they identify other people speaking near me?"),
    ( 15, "Audio",         "Can they capture ambient sound in my environment?"),
    ( 16, "Location",      "Can they see my current location?"),
    ( 17, "Location",      "Can they track my location history and movement patterns?"),
    ( 18, "Location",      "Can they infer where I live or work from my patterns?"),
    ( 19, "Location",      "Can they see the location metadata of photos I take?"),
    ( 20, "Social Graph",  "Can they build a profile of my friends/family who don't have an account?"),
    ( 21, "Social Graph",  "Can they map who I communicate with and how often?"),
    ( 22, "Social Graph",  "Can they detect other phones near me (Bluetooth/WiFi probing)?"),
    ( 23, "Social Graph",  "Can they see my contacts list?"),
    ( 24, "Social Graph",  "Can they see my call or message logs?"),
    ( 25, "Behavior",      "Can they track what I look at and for how long?"),
    ( 26, "Behavior",      "Can they infer my mood or emotional state?"),
    ( 27, "Behavior",      "Can they infer my political or religious beliefs?"),
    ( 28, "Behavior",      "Can they infer my sexual orientation or identity?"),
    ( 29, "Behavior",      "Can they build a behavioral profile to predict my future actions?"),
    ( 30, "Health",        "Can they collect health or fitness data?"),
    ( 31, "Health",        "Can they infer health conditions from my behavior or searches?"),
    ( 32, "Health",        "Can they collect biometric data (face, fingerprint, iris)?"),
    ( 33, "Financial",     "Can they see my purchase history?"),
    ( 34, "Financial",     "Can they infer my income or financial situation?"),
    ( 35, "Financial",     "Can they share or sell financial inferences to third parties?"),
    ( 36, "Device",        "Can they see what other apps I have installed?"),
    ( 37, "Device",        "Can they access my clipboard?"),
    ( 38, "Device",        "Can they see my browsing history across other sites?"),
    ( 39, "Device",        "Can they identify other devices on my home network?"),
]

DC_RATINGS = ["Yes", "No", "Likely", "Unlikely", "Unknown"]

DC_SYSTEM = """You are a privacy rights expert. You will receive a privacy policy and a numbered list of questions about what the company can collect and do with user data.

For EACH question answer two things:
1. can_do  — Can the company perform this action based on the policy?
2. third_party — Can they share this specific data or capability with third parties?

Rating scale (use EXACTLY one of these strings):
- "Yes"      — The policy explicitly permits this
- "No"       — The policy explicitly prohibits or opts the user out of this
- "Likely"   — The policy uses vague language that almost certainly permits this
- "Unlikely" — The policy implies this is not done but does not explicitly forbid it
- "Unknown"  — The policy is completely silent on this point

If the policy is silent, lean "Likely" for common industry practices, "Unknown" for niche capabilities.
Never assume good faith — when ambiguous, flag it.

For basis: one concise sentence citing the relevant clause, or "Not addressed in policy." """

DC_TOOL = {
    "name": "submit_data_collection_matrix",
    "description": "Submit answers to every data collection question.",
    "input_schema": {
        "type": "object",
        "properties": {
            "answers": {
                "type": "array",
                "description": "One entry per question, in order 1–39.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id":          {"type": "integer"},
                        "can_do":      {"type": "string", "enum": DC_RATINGS},
                        "third_party": {"type": "string", "enum": DC_RATINGS},
                        "basis":       {"type": "string"},
                    },
                    "required": ["id", "can_do", "third_party", "basis"],
                },
                "minItems": 39,
                "maxItems": 39,
            },
        },
        "required": ["answers"],
    },
}


def _analyze_data_collection(document_text: str) -> list[DataCollectionAnswer]:
    """Run the 39-question matrix against the document. Returns [] on failure."""
    q_block = "\n".join(f"{q[0]}. [{q[1]}] {q[2]}" for q in DC_QUESTIONS)
    user_msg = (
        f"Answer every question about this privacy policy:\n\n{q_block}\n\n"
        f"Policy text:\n---\n{document_text}\n---"
    )
    try:
        resp = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=[{"type": "text", "text": DC_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=[DC_TOOL],
            tool_choice={"type": "tool", "name": "submit_data_collection_matrix"},
            messages=[{
                "role": "user",
                "content": [{"type": "text", "text": user_msg, "cache_control": {"type": "ephemeral"}}],
            }],
        )
        block = next(b for b in resp.content if b.type == "tool_use")
        q_map = {q[0]: q for q in DC_QUESTIONS}
        return [
            DataCollectionAnswer(
                id=a["id"],
                category=q_map[a["id"]][1] if a["id"] in q_map else "Other",
                question=q_map[a["id"]][2] if a["id"] in q_map else f"Question {a['id']}",
                can_do=a["can_do"],
                third_party=a["third_party"],
                basis=a.get("basis", "Not addressed in policy."),
            )
            for a in block.input["answers"]
        ]
    except Exception:
        return []


# ── Main analysis ──────────────────────────────────────────────────────────────

USER_PROMPT_TEMPLATE = """Analyze the following Privacy Policy / EULA document.

Evaluate ALL of these categories in this exact order:
{categories}

The URL being analyzed is: {url}

Document to analyze:
---
{document_text}
---"""


async def analyze_document(url: str, document_text: str) -> AnalysisResult:
    truncated = document_text[:MAX_DOC_CHARS]

    user_prompt = USER_PROMPT_TEMPLATE.format(
        categories="\n".join(f"{i+1}. {c}" for i, c in enumerate(CATEGORIES)),
        url=url,
        document_text=truncated,
    )

    response = _get_client().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[ANALYSIS_TOOL],
        tool_choice={"type": "tool", "name": "submit_privacy_analysis"},
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    )

    # With forced tool_choice the first content block is always tool_use
    tool_block = next(b for b in response.content if b.type == "tool_use")
    data = tool_block.input

    categories = [
        CategoryResult(
            name=c["name"],
            risk=c["risk"],
            summary=c["summary"],
            quote=c["quote"] if c.get("quote") else None,
        )
        for c in data["categories"]
    ]

    doc_date = data.get("document_date", "").strip() or None

    # Second pass: data-collection matrix (uses cached document tokens)
    dc_matrix = _analyze_data_collection(truncated)

    # Override the Data Collection category risk with the matrix-computed score.
    # This replaces Claude's single broad judgment with a precise point-weighted
    # model that accounts for collection breadth, data sensitivity, and —
    # critically — third-party sharing (weighted 4× heavier than collection alone).
    dc_risk = compute_dc_risk(dc_matrix)
    if dc_risk:
        categories = [
            CategoryResult(
                name=cat.name,
                risk=dc_risk if cat.name == "Data Collection" else cat.risk,
                summary=cat.summary,
                quote=cat.quote,
            )
            for cat in categories
        ]

    privacy_score, grade = compute_privacy_score(categories)

    return AnalysisResult(
        company=data["company"],
        url=url,
        analyzed_at=datetime.now(timezone.utc),
        document_date=doc_date,
        overall_risk=data["overall_risk"],
        overall_summary=data["overall_summary"],
        categories=categories,
        privacy_score=privacy_score,
        grade=grade,
        data_collection_matrix=dc_matrix or None,
    )
