"""SQLite persistence for 문의함."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "munuiham.db"

# Shared status codes stored in DB (분양 + 인테리어).
STATUSES = ["미연락", "상담중", "방문예정", "계약", "보류"]

# Admin display labels for interior-quote (방문예정 → 실측예정).
# 견적발송은 별도 status 없이 notes에 기록.
INTERIOR_STATUS_LABELS = {
    "미연락": "미연락",
    "상담중": "상담중",
    "방문예정": "실측예정",
    "계약": "계약",
    "보류": "보류",
}

DEFAULT_SETTINGS = {
    "form_title": "달서 푸르지오 시그니처 상담 문의",
    "welcome_text": "관심 단지 상담을 남겨주시면 빠르게 연락드리겠습니다.",
    "success_text": "문의가 접수되었습니다. 담당자가 확인 후 연락드릴게요.",
    "default_complex": "달서 푸르지오 시그니처",
}

ZENIQUE_FORM = {
    "slug": "dalseo-xi-zenique",
    "title": "달서자이 제니크 상담 문의",
    "complex_name": "달서자이 제니크",
    "welcome_text": "관심 단지·타입을 남겨주시면 빠르게 상담 안내드리겠습니다.",
    "success_text": "문의가 접수되었습니다. 담당자가 확인 후 연락드릴게요.",
}

INTERIOR_FORM = {
    "slug": "interior-quote",
    "title": "인테리어 무료 견적 문의",
    "complex_name": "한빛인테리어",
    "welcome_text": "시공 유형·평수·예산을 알려주시면 빠르게 무료 견적을 안내해 드릴게요.",
    "success_text": "견적 문의가 접수되었습니다. 담당자가 확인 후 연락드릴게요.",
}


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                complex_name TEXT NOT NULL,
                welcome_text TEXT NOT NULL,
                success_text TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                form_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                complex_name TEXT NOT NULL,
                budget TEXT,
                unit_size TEXT,
                move_timing TEXT,
                message TEXT,
                source TEXT,
                status TEXT NOT NULL DEFAULT '미연락',
                notes TEXT NOT NULL DEFAULT '',
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (form_id) REFERENCES forms(id)
            );

            CREATE TABLE IF NOT EXISTS rate_limits (
                ip TEXT PRIMARY KEY,
                hits TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_leads_form ON leads(form_id);
            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at DESC);
            """
        )

        _ensure_column(conn, "leads", "meta", "meta TEXT NOT NULL DEFAULT ''")

        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

        conn.execute(
            """
            INSERT OR IGNORE INTO forms (slug, title, complex_name, welcome_text, success_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "dalseo-prugio",
                DEFAULT_SETTINGS["form_title"],
                DEFAULT_SETTINGS["default_complex"],
                DEFAULT_SETTINGS["welcome_text"],
                DEFAULT_SETTINGS["success_text"],
            ),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO forms (slug, title, complex_name, welcome_text, success_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                INTERIOR_FORM["slug"],
                INTERIOR_FORM["title"],
                INTERIOR_FORM["complex_name"],
                INTERIOR_FORM["welcome_text"],
                INTERIOR_FORM["success_text"],
            ),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO forms (slug, title, complex_name, welcome_text, success_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ZENIQUE_FORM["slug"],
                ZENIQUE_FORM["title"],
                ZENIQUE_FORM["complex_name"],
                ZENIQUE_FORM["welcome_text"],
                ZENIQUE_FORM["success_text"],
            ),
        )

        init_landing_pages(conn)



def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_form_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM forms WHERE slug = ? AND is_active = 1", (slug,)
    ).fetchone()


def get_form_by_id(conn: sqlite3.Connection, form_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()


def get_default_form(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM forms WHERE is_active = 1 ORDER BY id ASC LIMIT 1"
    ).fetchone()



def is_zenique_form(form_or_slug: Any) -> bool:
    if form_or_slug is None:
        return False
    if isinstance(form_or_slug, str):
        return form_or_slug in ("dalseo-xi-zenique", "dalseo-xi")
    try:
        return form_or_slug["slug"] == "dalseo-xi-zenique"
    except (KeyError, TypeError, IndexError):
        return False

def is_interior_form(form_or_slug: Any) -> bool:
    if form_or_slug is None:
        return False
    if isinstance(form_or_slug, str):
        return form_or_slug == "interior-quote"
    try:
        return form_or_slug["slug"] == "interior-quote"
    except (KeyError, TypeError, IndexError):
        return False


def status_label(status: str, *, interior: bool = False) -> str:
    if interior:
        return INTERIOR_STATUS_LABELS.get(status, status)
    return status


def parse_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def create_lead(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    meta = data.get("meta")
    if isinstance(meta, dict):
        meta_str = json.dumps(meta, ensure_ascii=False)
    else:
        meta_str = meta or ""
    cur = conn.execute(
        """
        INSERT INTO leads (
            form_id, name, phone, complex_name, budget, unit_size,
            move_timing, message, source, meta
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["form_id"],
            data["name"],
            data["phone"],
            data["complex_name"],
            data.get("budget") or "",
            data.get("unit_size") or "",
            data.get("move_timing") or "",
            data.get("message") or "",
            data.get("source") or "",
            meta_str,
        ),
    )
    return int(cur.lastrowid)


def list_leads(
    conn: sqlite3.Connection,
    status: str | None = None,
    unread_only: bool = False,
) -> list[sqlite3.Row]:
    sql = """
        SELECT leads.*, forms.slug AS form_slug, forms.title AS form_title
        FROM leads
        JOIN forms ON forms.id = leads.form_id
        WHERE 1=1
    """
    params: list[Any] = []
    if status:
        sql += " AND leads.status = ?"
        params.append(status)
    if unread_only:
        sql += " AND leads.is_read = 0"
    sql += " ORDER BY leads.created_at DESC"
    return list(conn.execute(sql, params).fetchall())


def get_lead(conn: sqlite3.Connection, lead_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT leads.*, forms.slug AS form_slug, forms.title AS form_title
        FROM leads
        JOIN forms ON forms.id = leads.form_id
        WHERE leads.id = ?
        """,
        (lead_id,),
    ).fetchone()


def update_lead(
    conn: sqlite3.Connection,
    lead_id: int,
    *,
    status: str | None = None,
    notes: str | None = None,
    mark_read: bool | None = None,
) -> None:
    fields: list[str] = ["updated_at = datetime('now','localtime')"]
    params: list[Any] = []
    if status is not None:
        fields.append("status = ?")
        params.append(status)
    if notes is not None:
        fields.append("notes = ?")
        params.append(notes)
    if mark_read is not None:
        fields.append("is_read = ?")
        params.append(1 if mark_read else 0)
    params.append(lead_id)
    conn.execute(f"UPDATE leads SET {', '.join(fields)} WHERE id = ?", params)


def count_unread(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM leads WHERE is_read = 0").fetchone()
    return int(row["c"])


def check_rate_limit(conn: sqlite3.Connection, ip: str, limit: int = 5, window: int = 600) -> bool:
    """Return True if request is allowed. Stores recent hit timestamps as comma-separated epoch seconds."""
    import time

    now = int(time.time())
    row = conn.execute("SELECT hits FROM rate_limits WHERE ip = ?", (ip,)).fetchone()
    hits: list[int] = []
    if row and row["hits"]:
        hits = [int(x) for x in row["hits"].split(",") if x.strip()]
    hits = [t for t in hits if now - t < window]
    if len(hits) >= limit:
        conn.execute(
            "INSERT INTO rate_limits (ip, hits) VALUES (?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET hits = excluded.hits",
            (ip, ",".join(str(t) for t in hits)),
        )
        return False
    hits.append(now)
    conn.execute(
        "INSERT INTO rate_limits (ip, hits) VALUES (?, ?) "
        "ON CONFLICT(ip) DO UPDATE SET hits = excluded.hits",
        (ip, ",".join(str(t) for t in hits)),
    )
    return True

# ── Landing pages ────────────────────────────────────────────

LANDING_SLUGS = ("dalseo-xi-zenique", "dalseo-prugio")

LANDING_LABELS = {
    "dalseo-xi-zenique": "달서자이 제니크",
    "dalseo-prugio": "달서 푸르지오 시그니처",
}

# Preview public paths (/l/...)
LANDING_PREVIEW_PATHS = {
    "dalseo-xi-zenique": "/l/dalseo-xi",
    "dalseo-prugio": "/l/dalseo-prugio",
}

ZENIQUE_LANDING_SEED = {
    "slug": "dalseo-xi-zenique",
    "hero_title": "달서자이 제니크",
    "hero_subtitle": "후분양으로 더 빠르게,\n선착순 동호지정 상담",
    "hero_cta": "무료 상담 신청",
    "hero_eyebrow": "대구 달서 · 본리동",
    "hero_lead": "지하 5층~최고 49층 · 총 438세대\n전용 84㎡ 단일 · 2027년 2월 입주 예정",
    "highlights_json": json.dumps(
        [
            {
                "title": "최고 49층, 본리동 스카이라인을 열다",
                "body": "최고 49층 스카이라인으로 본리동 일대를 새롭게 여는 GS건설 자이 단지입니다.",
            },
            {
                "title": "계약 조건 (보도 기준)",
                "body": "선착순 동호지정 계약 진행 · 1차 계약금 100만원 정액제 언급 사례가 있습니다. 최종은 사업주체 안내를 확인해 주세요.",
            },
            {
                "title": "상품성",
                "body": "남향 위주 · 알파룸·수납특화 · 시스템에어컨 등 기본옵션 · 주차 약 세대당 1.35대 수준.",
            },
            {
                "title": "생활권",
                "body": "본리네거리 생활권 · 덕인초 도보권(보도 기준).",
            },
        ],
        ensure_ascii=False,
    ),
    "price_range": "약 4.6억 ~ 5.97억대",
    "price_note": "공개 보도 기준의 대략적 범위이며 층·타입별 상이합니다. 실제 분양가·일정·혜택은 모집공고 및 사업주체 안내가 우선하며, 상담 시 반드시 확인해 주세요. 본 페이지 정보는 변경될 수 있습니다.",
    "disclaimer": "본 페이지는 홍보·상담 안내용이며 분양가·일정·혜택은 모집공고·사업주체 안내가 우선합니다. 단지 정보·조건은 변경될 수 있으니 상담 시 확인해 주세요.",
    "fact_location": "달서구 본리동",
    "fact_location_detail": "661-9번지 일원 · 본리네거리 생활권",
    "fact_scale": "총 438세대",
    "fact_scale_detail": "지하5~지상 최고 49층",
    "fact_unit": "전용 84㎡",
    "fact_unit_detail": "타입 84A · 84B",
    "fact_move_in": "2027. 2. 예정",
    "fact_move_in_detail": "",
    "hero_image": "",
    "gallery_json": "[]",
}

PRUGIO_LANDING_SEED = {
    "slug": "dalseo-prugio",
    "hero_title": "달서 푸르지오 시그니처 상담 문의",
    "hero_subtitle": "9월부터 분양가 약 1억 조정 · 준공 후 미분양",
    "hero_cta": "무료 상담 신청",
    "hero_eyebrow": "대구 달서 · 분양 상담",
    "hero_lead": "모델하우스 방문·조건 상담을 편하게 받아 보세요. 부담 없는 무료 상담입니다.",
    "highlights_json": json.dumps(
        [
            {"title": "전용 84㎡", "body": "A / B / C 타입"},
            {"title": "대단지", "body": "생활·단지 인프라"},
            {"title": "준공 후 미분양", "body": "주택수·취득세 관점 안내 가능"},
            {"title": "모델하우스 상담", "body": "일정·조건 맞춤 안내"},
        ],
        ensure_ascii=False,
    ),
    "price_range": "",
    "price_note": "",
    "disclaimer": "개인정보는 상담 목적에만 사용되며, 스팸·광고 문자를 보내지 않습니다.",
    "fact_location": "대구 달서",
    "fact_location_detail": "",
    "fact_scale": "대단지",
    "fact_scale_detail": "",
    "fact_unit": "전용 84㎡",
    "fact_unit_detail": "A / B / C 타입",
    "fact_move_in": "준공 후 미분양",
    "fact_move_in_detail": "",
    "hero_image": "",
    "gallery_json": "[]",
}


def _seed_landing(conn: sqlite3.Connection, seed: dict[str, str]) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO landing_pages (
            slug, hero_title, hero_subtitle, hero_cta, hero_eyebrow, hero_lead,
            highlights_json, price_range, price_note, disclaimer,
            fact_location, fact_location_detail, fact_scale, fact_scale_detail,
            fact_unit, fact_unit_detail, fact_move_in, fact_move_in_detail,
            hero_image, gallery_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?
        )
        """,
        (
            seed["slug"],
            seed["hero_title"],
            seed["hero_subtitle"],
            seed["hero_cta"],
            seed["hero_eyebrow"],
            seed["hero_lead"],
            seed["highlights_json"],
            seed["price_range"],
            seed["price_note"],
            seed["disclaimer"],
            seed["fact_location"],
            seed["fact_location_detail"],
            seed["fact_scale"],
            seed["fact_scale_detail"],
            seed["fact_unit"],
            seed["fact_unit_detail"],
            seed["fact_move_in"],
            seed["fact_move_in_detail"],
            seed["hero_image"],
            seed["gallery_json"],
        ),
    )


def init_landing_pages(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS landing_pages (
            slug TEXT PRIMARY KEY,
            hero_title TEXT NOT NULL DEFAULT '',
            hero_subtitle TEXT NOT NULL DEFAULT '',
            hero_cta TEXT NOT NULL DEFAULT '',
            hero_eyebrow TEXT NOT NULL DEFAULT '',
            hero_lead TEXT NOT NULL DEFAULT '',
            highlights_json TEXT NOT NULL DEFAULT '[]',
            price_range TEXT NOT NULL DEFAULT '',
            price_note TEXT NOT NULL DEFAULT '',
            disclaimer TEXT NOT NULL DEFAULT '',
            fact_location TEXT NOT NULL DEFAULT '',
            fact_location_detail TEXT NOT NULL DEFAULT '',
            fact_scale TEXT NOT NULL DEFAULT '',
            fact_scale_detail TEXT NOT NULL DEFAULT '',
            fact_unit TEXT NOT NULL DEFAULT '',
            fact_unit_detail TEXT NOT NULL DEFAULT '',
            fact_move_in TEXT NOT NULL DEFAULT '',
            fact_move_in_detail TEXT NOT NULL DEFAULT '',
            hero_image TEXT NOT NULL DEFAULT '',
            gallery_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        """
    )
    _seed_landing(conn, ZENIQUE_LANDING_SEED)
    _seed_landing(conn, PRUGIO_LANDING_SEED)


def parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def landing_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    highlights = parse_json_list(d.get("highlights_json"))
    # Normalize highlights to list of {title, body}
    norm: list[dict[str, str]] = []
    for item in highlights:
        if isinstance(item, dict):
            norm.append(
                {
                    "title": str(item.get("title") or ""),
                    "body": str(item.get("body") or ""),
                }
            )
        elif isinstance(item, str):
            norm.append({"title": item, "body": ""})
    while len(norm) < 4:
        norm.append({"title": "", "body": ""})
    d["highlights"] = norm[:8]
    d["gallery"] = [
        str(x) for x in parse_json_list(d.get("gallery_json")) if str(x).strip()
    ]
    return d


def get_landing(conn: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM landing_pages WHERE slug = ?", (slug,)
    ).fetchone()
    if not row:
        return None
    return landing_row_to_dict(row)


def list_landings(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM landing_pages ORDER BY slug ASC"
    ).fetchall()
    return [landing_row_to_dict(r) for r in rows]


def update_landing(
    conn: sqlite3.Connection,
    slug: str,
    fields: dict[str, Any],
) -> None:
    highlights = fields.get("highlights")
    if isinstance(highlights, list):
        highlights_json = json.dumps(highlights, ensure_ascii=False)
    else:
        highlights_json = fields.get("highlights_json") or "[]"

    gallery = fields.get("gallery")
    if isinstance(gallery, list):
        gallery_json = json.dumps(gallery, ensure_ascii=False)
    else:
        gallery_json = fields.get("gallery_json")
        if gallery_json is None:
            # keep existing
            row = conn.execute(
                "SELECT gallery_json FROM landing_pages WHERE slug = ?", (slug,)
            ).fetchone()
            gallery_json = row["gallery_json"] if row else "[]"

    conn.execute(
        """
        UPDATE landing_pages SET
            hero_title = ?,
            hero_subtitle = ?,
            hero_cta = ?,
            hero_eyebrow = ?,
            hero_lead = ?,
            highlights_json = ?,
            price_range = ?,
            price_note = ?,
            disclaimer = ?,
            fact_location = ?,
            fact_location_detail = ?,
            fact_scale = ?,
            fact_scale_detail = ?,
            fact_unit = ?,
            fact_unit_detail = ?,
            fact_move_in = ?,
            fact_move_in_detail = ?,
            hero_image = ?,
            gallery_json = ?,
            updated_at = datetime('now','localtime')
        WHERE slug = ?
        """,
        (
            fields.get("hero_title", ""),
            fields.get("hero_subtitle", ""),
            fields.get("hero_cta", ""),
            fields.get("hero_eyebrow", ""),
            fields.get("hero_lead", ""),
            highlights_json,
            fields.get("price_range", ""),
            fields.get("price_note", ""),
            fields.get("disclaimer", ""),
            fields.get("fact_location", ""),
            fields.get("fact_location_detail", ""),
            fields.get("fact_scale", ""),
            fields.get("fact_scale_detail", ""),
            fields.get("fact_unit", ""),
            fields.get("fact_unit_detail", ""),
            fields.get("fact_move_in", ""),
            fields.get("fact_move_in_detail", ""),
            fields.get("hero_image", ""),
            gallery_json,
            slug,
        ),
    )


def set_landing_hero_image(conn: sqlite3.Connection, slug: str, path: str) -> None:
    conn.execute(
        """
        UPDATE landing_pages
        SET hero_image = ?, updated_at = datetime('now','localtime')
        WHERE slug = ?
        """,
        (path, slug),
    )


def set_landing_gallery(conn: sqlite3.Connection, slug: str, gallery: list[str]) -> None:
    conn.execute(
        """
        UPDATE landing_pages
        SET gallery_json = ?, updated_at = datetime('now','localtime')
        WHERE slug = ?
        """,
        (json.dumps(gallery, ensure_ascii=False), slug),
    )
