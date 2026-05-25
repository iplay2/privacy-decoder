import httpx
import re
from playwright.async_api import async_playwright

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
TIMEOUT = 25
# Pages with less than this from httpx are likely navigation shells
HTTPX_MIN_CHARS = 5000


async def fetch_document(url: str) -> str:
    """Try httpx first; fall back to Playwright for JS-rendered pages."""
    text = await _fetch_httpx(url)  # raises FetchError on HTTP 4xx/5xx
    if text and len(text.strip()) >= HTTPX_MIN_CHARS:
        return text
    try:
        return await _fetch_playwright(url)
    except Exception as exc:
        # Playwright unavailable (e.g. snap Chromium blocked in systemd) — return what httpx got
        if text and len(text.strip()) >= 500:
            return text
        raise FetchError(
            "We couldn't retrieve enough content from that page. "
            "It may require JavaScript or a login session."
        ) from exc


class FetchError(Exception):
    """Raised when a URL is unreachable or access-denied — do not fall back to Playwright."""
    pass


async def _fetch_httpx(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.get(url)
            if response.status_code in (401, 403):
                raise FetchError(
                    "That page requires a login or is access-restricted. "
                    "Try the public URL of the privacy policy instead."
                )
            if response.status_code == 400:
                raise FetchError(
                    "That URL returned an error (400). It may require cookies or a logged-in session. "
                    "Try the main public URL of the privacy policy instead."
                )
            if response.status_code >= 400:
                raise FetchError(
                    f"We couldn't reach that URL (HTTP {response.status_code}). "
                    "Check that it's correct and publicly accessible."
                )
            return _extract_text_from_html(response.text)
    except FetchError:
        raise
    except Exception:
        return ""


_CHROMIUM_PATHS = [
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
]


def _find_chromium() -> str | None:
    import shutil
    for path in _CHROMIUM_PATHS:
        if shutil.which(path) or __import__("os").path.exists(path):
            return path
    return None


async def _fetch_playwright(url: str) -> str:
    async with async_playwright() as p:
        launch_args = {"headless": True, "args": ["--no-sandbox", "--disable-dev-shm-usage"]}
        system_chrome = _find_chromium()
        if system_chrome:
            launch_args["executable_path"] = system_chrome
        browser = await p.chromium.launch(**launch_args)
        try:
            ctx = await browser.new_context(
                user_agent=HEADERS["User-Agent"],
                java_script_enabled=True,
                viewport={"width": 1280, "height": 900},
            )
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT * 1000)
            # Scroll to trigger lazy-loaded content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2500)
            # Use inner_text for clean pre-extracted text
            text = await page.evaluate("document.body.innerText")
            return _normalize_whitespace(text)
        finally:
            await browser.close()


def _extract_text_from_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace to readable plain text."""
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<[^>]+>", " ", html)
    return _normalize_whitespace(text)


def _normalize_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
