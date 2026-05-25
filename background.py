import hashlib
import logging

from fetcher import fetch_document
from analyzer import analyze_document
from database import get_stored_hash, save_analysis, _hash_document

logger = logging.getLogger(__name__)


async def check_and_refresh(url: str):
    """Fetch the live document; if its hash differs from stored, re-analyze and save."""
    try:
        text = await fetch_document(url)
        if not text or len(text.strip()) < 500:
            return

        current_hash = _hash_document(text)
        stored_hash = await get_stored_hash(url)

        if current_hash == stored_hash:
            return  # document unchanged

        logger.info("Document changed for %s — re-analyzing", url)
        result = await analyze_document(url, text)
        await save_analysis(url, result, current_hash)
        logger.info("Re-analysis complete for %s (new version saved)", url)

    except Exception as exc:
        logger.warning("Background refresh failed for %s: %s", url, exc)
