import json
import hashlib
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from models import AnalysisResult, CategoryResult, CategoryChange, DataCollectionAnswer
from scoring import compute_privacy_score

DB_PATH = "privacy_decoder.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    company TEXT NOT NULL,
    overall_risk TEXT NOT NULL,
    overall_summary TEXT NOT NULL,
    categories_json TEXT NOT NULL,
    doc_hash TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    document_date TEXT,
    is_pdf INTEGER NOT NULL DEFAULT 0,
    privacy_score INTEGER,
    grade TEXT
);

CREATE TABLE IF NOT EXISTS analysis_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    company TEXT NOT NULL,
    overall_risk TEXT NOT NULL,
    overall_summary TEXT NOT NULL,
    categories_json TEXT NOT NULL,
    doc_hash TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    version INTEGER NOT NULL,
    document_date TEXT,
    is_pdf INTEGER NOT NULL DEFAULT 0,
    privacy_score INTEGER,
    grade TEXT
);

CREATE TABLE IF NOT EXISTS request_counts (
    url TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 1,
    last_requested TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('popular_list_size', '10');
"""

# Columns added after initial release — applied safely to existing DBs
MIGRATIONS = [
    "ALTER TABLE analyses ADD COLUMN document_date TEXT",
    "ALTER TABLE analyses ADD COLUMN is_pdf INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE analysis_versions ADD COLUMN document_date TEXT",
    "ALTER TABLE analysis_versions ADD COLUMN is_pdf INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE analyses ADD COLUMN privacy_score INTEGER",
    "ALTER TABLE analyses ADD COLUMN grade TEXT",
    "ALTER TABLE analysis_versions ADD COLUMN privacy_score INTEGER",
    "ALTER TABLE analysis_versions ADD COLUMN grade TEXT",
    "ALTER TABLE analyses ADD COLUMN data_collection_json TEXT",
    "ALTER TABLE analysis_versions ADD COLUMN data_collection_json TEXT",
]


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        for stmt in MIGRATIONS:
            try:
                await db.execute(stmt)
            except Exception:
                pass  # column already exists
        await db.commit()
    await _backfill_scores()


async def _backfill_scores():
    """Compute and store privacy_score/grade for any rows written before scoring was added."""
    async with aiosqlite.connect(DB_PATH) as db:
        for table in ("analyses", "analysis_versions"):
            async with db.execute(
                f"SELECT id, categories_json FROM {table} WHERE privacy_score IS NULL"
            ) as cursor:
                rows = await cursor.fetchall()
            for row_id, cats_json in rows:
                cats = [CategoryResult(**c) for c in json.loads(cats_json)]
                score, grade = compute_privacy_score(cats)
                await db.execute(
                    f"UPDATE {table} SET privacy_score=?, grade=? WHERE id=?",
                    (score, grade, row_id),
                )
        await db.commit()


def _hash_document(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _row_to_result(row, from_cache=True) -> AnalysisResult:
    # columns: id=0, url=1, company=2, overall_risk=3, overall_summary=4,
    #          categories_json=5, doc_hash=6, analyzed_at=7, version=8,
    #          document_date=9, is_pdf=10, privacy_score=11, grade=12,
    #          data_collection_json=13
    url             = row[1]
    company         = row[2]
    overall_risk    = row[3]
    overall_summary = row[4]
    categories      = [CategoryResult(**c) for c in json.loads(row[5])]
    analyzed_at     = row[7]
    version         = row[8]
    document_date   = row[9]  if len(row) > 9  else None
    is_pdf          = bool(row[10]) if len(row) > 10 else False
    privacy_score   = row[11] if len(row) > 11 else None
    grade           = row[12] if len(row) > 12 else None
    dc_json         = row[13] if len(row) > 13 else None

    # Back-fill score for rows written before scoring was introduced
    if privacy_score is None:
        privacy_score, grade = compute_privacy_score(categories)

    dc_matrix = None
    if dc_json:
        try:
            dc_matrix = [DataCollectionAnswer(**a) for a in json.loads(dc_json)]
        except Exception:
            pass

    return AnalysisResult(
        company=company,
        url=url,
        analyzed_at=datetime.fromisoformat(analyzed_at),
        document_date=document_date,
        overall_risk=overall_risk,
        overall_summary=overall_summary,
        categories=categories,
        privacy_score=privacy_score,
        grade=grade,
        from_cache=from_cache,
        cached_at=datetime.fromisoformat(analyzed_at),
        version=version,
        is_pdf=is_pdf,
        data_collection_matrix=dc_matrix,
    )


async def get_cached_analysis(url: str) -> Optional[AnalysisResult]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM analyses WHERE url = ?", (url,)
        ) as cursor:
            row = await cursor.fetchone()
    return _row_to_result(row) if row else None


async def get_stored_hash(url: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT doc_hash FROM analyses WHERE url = ?", (url,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def get_version_history(url: str) -> list[AnalysisResult]:
    """Returns all versions (past + current) ordered oldest to newest."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT * FROM analysis_versions WHERE url = ? ORDER BY version ASC", (url,)
        ) as cursor:
            past_rows = await cursor.fetchall()
        async with db.execute(
            "SELECT * FROM analyses WHERE url = ?", (url,)
        ) as cursor:
            current_row = await cursor.fetchone()

    results = [_row_to_result(r, from_cache=True) for r in past_rows]
    if current_row:
        results.append(_row_to_result(current_row, from_cache=True))
    return results


def _compute_changes(old: AnalysisResult, new: AnalysisResult) -> list[CategoryChange]:
    old_map = {c.name: c for c in old.categories}
    return [
        CategoryChange(
            name=cat.name,
            previous_risk=old_map[cat.name].risk,
            current_risk=cat.risk,
            risk_changed=old_map[cat.name].risk != cat.risk,
            summary_changed=old_map[cat.name].summary != cat.summary,
        )
        for cat in new.categories
        if cat.name in old_map
    ]


async def save_analysis(url: str, result: AnalysisResult, doc_hash: str,
                        is_pdf: bool = False) -> AnalysisResult:
    categories_json = json.dumps([c.model_dump() for c in result.categories])
    analyzed_at = result.analyzed_at.isoformat()
    doc_date = result.document_date
    dc_json = (
        json.dumps([a.model_dump() for a in result.data_collection_matrix])
        if result.data_collection_matrix else None
    )

    # Ensure score is computed (analyzer already sets it; this is a safety net)
    if result.privacy_score is None:
        result.privacy_score, result.grade = compute_privacy_score(result.categories)

    async with aiosqlite.connect(DB_PATH) as db:
        existing = await db.execute("SELECT version FROM analyses WHERE url = ?", (url,))
        row = await existing.fetchone()

        if row is None:
            version = 1
            await db.execute(
                """INSERT INTO analyses
                   (url, company, overall_risk, overall_summary, categories_json,
                    doc_hash, analyzed_at, version, document_date, is_pdf,
                    privacy_score, grade, data_collection_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (url, result.company, result.overall_risk, result.overall_summary,
                 categories_json, doc_hash, analyzed_at, version, doc_date, int(is_pdf),
                 result.privacy_score, result.grade, dc_json),
            )
        else:
            version = row[0] + 1
            await db.execute(
                """INSERT INTO analysis_versions
                   SELECT NULL, url, company, overall_risk, overall_summary,
                          categories_json, doc_hash, analyzed_at, version,
                          document_date, is_pdf, privacy_score, grade,
                          data_collection_json
                   FROM analyses WHERE url = ?""",
                (url,),
            )
            await db.execute(
                """UPDATE analyses
                   SET company=?, overall_risk=?, overall_summary=?, categories_json=?,
                       doc_hash=?, analyzed_at=?, version=?, document_date=?, is_pdf=?,
                       privacy_score=?, grade=?, data_collection_json=?
                   WHERE url=?""",
                (result.company, result.overall_risk, result.overall_summary,
                 categories_json, doc_hash, analyzed_at, version, doc_date,
                 int(is_pdf), result.privacy_score, result.grade, dc_json, url),
            )

        await db.commit()

    result.version = version
    result.from_cache = False
    result.is_pdf = is_pdf
    return result


async def increment_request_count(url: str):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO request_counts (url, count, last_requested)
               VALUES (?, 1, ?)
               ON CONFLICT(url) DO UPDATE SET count = count + 1, last_requested = ?""",
            (url, now, now),
        )
        await db.commit()


async def get_popular_list(limit: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT r.url, r.count, a.company, a.overall_risk, a.overall_summary,
                      a.analyzed_at, a.version, a.document_date, a.is_pdf,
                      a.privacy_score, a.grade
               FROM request_counts r
               JOIN analyses a ON r.url = a.url
               ORDER BY r.count DESC
               LIMIT ?""",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            "url": row[0],
            "request_count": row[1],
            "company": row[2],
            "overall_risk": row[3],
            "overall_summary": row[4],
            "analyzed_at": row[5],
            "version": row[6],
            "document_date": row[7],
            "is_pdf": bool(row[8]),
            "privacy_score": row[9],
            "grade": row[10],
        }
        for row in rows
    ]


async def get_popular_list_size() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT value FROM admin_settings WHERE key = 'popular_list_size'"
        ) as cursor:
            row = await cursor.fetchone()
    return int(row[0]) if row else 10


async def set_popular_list_size(size: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE admin_settings SET value = ? WHERE key = 'popular_list_size'",
            (str(size),),
        )
        await db.commit()
