import io
from pypdf import PdfReader


def extract_text_from_pdf(data: bytes) -> str:
    """Extract plain text from PDF bytes. Raises ValueError if unusable."""
    reader = PdfReader(io.BytesIO(data))

    if len(reader.pages) == 0:
        raise ValueError("The uploaded PDF has no pages.")

    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        parts.append(text)

    full_text = "\n\n".join(parts).strip()

    if not full_text:
        raise ValueError(
            "No text could be extracted from this PDF. "
            "It may be a scanned image PDF — try copy-pasting the text instead."
        )

    return full_text
