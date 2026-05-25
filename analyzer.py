import os
from datetime import datetime, timezone

import anthropic
from models import AnalysisResult, CategoryResult
from scoring import compute_privacy_score

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
    )
