import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from models import (
    AnalyzeRequest, AnalysisResult, PopularResponse, PopularEntry,
    AdminSettings, HealthResponse,
)
from fetcher import fetch_document, FetchError
from analyzer import analyze_document
from pdf_extractor import extract_text_from_pdf
from database import (
    init_db, get_cached_analysis, save_analysis, increment_request_count,
    get_popular_list, get_popular_list_size, set_popular_list_size,
    get_version_history, _hash_document,
)
from background import check_and_refresh

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Privacy Decoder", lifespan=lifespan)

app.mount("/privacydecoder/static", StaticFiles(directory="static"), name="static")


def require_admin(x_admin_key: str = Header(default="")):
    if ADMIN_API_KEY and x_admin_key != ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid admin key")


# ── Frontend ────────────────────────────────────────────────────────────────

@app.get("/privacydecoder/")
@app.get("/privacydecoder")
async def serve_frontend():
    return FileResponse("static/index.html")


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/privacydecoder/health", response_model=HealthResponse)
async def health():
    return {"status": "ok"}


# ── Core analysis ────────────────────────────────────────────────────────────

@app.post("/privacydecoder/analyze", response_model=AnalysisResult)
async def analyze(req: AnalyzeRequest, background_tasks: BackgroundTasks):
    url = str(req.url).rstrip("/")

    # Increment request count regardless of cache state
    await increment_request_count(url)

    # Check cache
    cached = await get_cached_analysis(url)
    if cached:
        if not url.startswith("pdf:"):
            background_tasks.add_task(check_and_refresh, url)
        return cached

    # Fresh analysis
    try:
        text = await fetch_document(url)
    except FetchError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not text:
        raise HTTPException(
            status_code=422,
            detail="We couldn't reach that URL. Check that it's correct and publicly accessible.",
        )
    if len(text.strip()) < 500:
        raise HTTPException(
            status_code=422,
            detail="The document retrieved seems too short to be a full privacy policy. Try a different URL.",
        )

    doc_hash = _hash_document(text)

    try:
        result = await analyze_document(url, text)
    except Exception as exc:
        logger.error("Claude analysis failed: %s", exc)
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429:
            raise HTTPException(status_code=429, detail="Rate limit reached. Please try again shortly.")
        raise HTTPException(status_code=500, detail="Analysis failed. Please try again in a moment.")

    result = await save_analysis(url, result, doc_hash)
    return result


# ── PDF upload analysis ───────────────────────────────────────────────────────

@app.post("/privacydecoder/analyze/upload", response_model=AnalysisResult)
async def analyze_upload(file: UploadFile = File(...)):
    if file.content_type not in ("application/pdf", "application/octet-stream") and \
            not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Only PDF files are supported.")

    data = await file.read()
    if len(data) > 20 * 1024 * 1024:  # 20 MB cap
        raise HTTPException(status_code=413, detail="PDF must be under 20 MB.")

    try:
        text = extract_text_from_pdf(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if len(text) < 500:
        raise HTTPException(
            status_code=422,
            detail="The document retrieved seems too short to be a full privacy policy.",
        )

    source_label = f"pdf:{file.filename or 'upload'}"

    try:
        result = await analyze_document(source_label, text)
    except Exception as exc:
        logger.error("Claude analysis failed for PDF upload: %s", exc)
        raise HTTPException(status_code=500, detail="Analysis failed. Please try again in a moment.")

    result.url = source_label
    doc_hash = _hash_document(text)
    await increment_request_count(source_label)
    result = await save_analysis(source_label, result, doc_hash, is_pdf=True)
    return result


# ── Popular list ─────────────────────────────────────────────────────────────

@app.get("/privacydecoder/popular", response_model=PopularResponse)
async def popular():
    size = await get_popular_list_size()
    rows = await get_popular_list(size)
    entries = [
        PopularEntry(
            url=r["url"],
            company=r["company"],
            overall_risk=r["overall_risk"],
            overall_summary=r["overall_summary"],
            request_count=r["request_count"],
            analyzed_at=r["analyzed_at"],
            document_date=r.get("document_date"),
            is_pdf=r.get("is_pdf", False),
            privacy_score=r.get("privacy_score"),
            grade=r.get("grade"),
        )
        for r in rows
    ]
    return PopularResponse(entries=entries, list_size=size)


# ── Version history ──────────────────────────────────────────────────────────

@app.get("/privacydecoder/history")
async def history(url: str):
    versions = await get_version_history(url)
    if not versions:
        raise HTTPException(status_code=404, detail="No version history found for this URL.")
    return {"url": url, "versions": versions}


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.post("/privacydecoder/admin/settings", dependencies=[Depends(require_admin)])
async def update_settings(settings: AdminSettings):
    if settings.popular_list_size < 1:
        raise HTTPException(status_code=400, detail="popular_list_size must be at least 1")
    await set_popular_list_size(settings.popular_list_size)
    return {"popular_list_size": settings.popular_list_size}


@app.get("/privacydecoder/admin/settings", dependencies=[Depends(require_admin)])
async def get_settings():
    size = await get_popular_list_size()
    return {"popular_list_size": size}
