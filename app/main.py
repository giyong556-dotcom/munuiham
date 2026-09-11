"""문의함 — Kakao/mobile inquiry organizer MVP."""
from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import db as database

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change-me")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "munuiham-dev-secret-change-in-prod")

PHONE_RE = re.compile(r"^01[016789]-?\d{3,4}-?\d{4}$")

app = FastAPI(title="문의함", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=60 * 60 * 24 * 7)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["status_label"] = database.status_label
templates.env.globals["is_interior_slug"] = lambda slug: slug == "interior-quote"
templates.env.globals["is_zenique_slug"] = lambda slug: slug in ("dalseo-xi-zenique", "dalseo-xi")
templates.env.globals["parse_meta"] = database.parse_meta


@app.on_event("startup")
def on_startup() -> None:
    database.init_db()


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def normalize_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return phone.strip()


def form_template_name(form) -> str:
    if database.is_interior_form(form):
        return "form_interior.html"
    return "form.html"


def render_public_form(request: Request, form, settings, error=None, values=None, status_code: int = 200):
    return templates.TemplateResponse(
        form_template_name(form),
        {
            "request": request,
            "form": form,
            "settings": settings,
            "error": error,
            "values": values or {},
        },
        status_code=status_code,
    )


def validate_phone(phone: str) -> str | None:
    """Return normalized phone or None if invalid."""
    phone_norm = normalize_phone(phone)
    if PHONE_RE.match(phone_norm) or PHONE_RE.match(phone.replace(" ", "")):
        return phone_norm
    digits = re.sub(r"\D", "", phone)
    if len(digits) in (10, 11) and digits.startswith("01"):
        return normalize_phone(phone)
    return None


# ── Public form ──────────────────────────────────────────────


# Short marketing paths → form slug
LANDING_ALIASES = {
    "dalseo-xi": "dalseo-xi-zenique",
    "dalseo-xi-zenique": "dalseo-xi-zenique",
    "dalseo-prugio": "dalseo-prugio",
}


def resolve_landing_slug(slug: str) -> str:
    return LANDING_ALIASES.get(slug, slug)


def landing_template_name(form) -> str:
    if database.is_zenique_form(form):
        return "landing_zenique.html"
    return "landing.html"


def render_landing(request: Request, slug: str = "dalseo-prugio", *, values=None, error=None, status_code: int = 200):
    form_slug = resolve_landing_slug(slug)
    with database.db() as conn:
        form = database.get_form_by_slug(conn, form_slug)
        if not form:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "페이지를 찾을 수 없습니다.", "code": 404},
                status_code=404,
            )
        settings = database.get_all_settings(conn)
        landing = database.get_landing(conn, form_slug) or {}
    return templates.TemplateResponse(
        landing_template_name(form),
        {
            "request": request,
            "form": form,
            "settings": settings,
            "landing": landing,
            "values": values or {},
            "error": error,
        },
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Default home → 달서자이 제니크 랜딩. 푸르지오는 /l/dalseo-prugio."""
    return render_landing(request, "dalseo-xi-zenique")


@app.get("/l/{slug}", response_class=HTMLResponse)
async def landing_by_slug(request: Request, slug: str):
    return render_landing(request, slug)


@app.get("/f/{slug}", response_class=HTMLResponse)
async def public_form(request: Request, slug: str):
    with database.db() as conn:
        form = database.get_form_by_slug(conn, slug)
        if not form:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "폼을 찾을 수 없습니다.", "code": 404},
                status_code=404,
            )
        settings = database.get_all_settings(conn)
    return render_public_form(request, form, settings)


@app.post("/f/{slug}", response_class=HTMLResponse)
async def submit_form(
    request: Request,
    slug: str,
    name: str = Form(...),
    phone: str = Form(...),
    complex_name: str = Form(""),
    budget: str = Form(""),
    unit_size: str = Form(""),
    age_group: str = Form(""),
    move_timing: str = Form(""),
    work_type: str = Form(""),
    message: str = Form(""),
    source: str = Form(""),
    website: str = Form(""),  # honeypot
):
    is_interior = slug == "interior-quote"
    values = {
        "name": name.strip(),
        "phone": phone.strip(),
        "complex_name": complex_name.strip(),
        "budget": budget.strip(),
        "unit_size": unit_size.strip(),
        "age_group": age_group.strip(),
        "move_timing": move_timing.strip(),
        "work_type": work_type.strip(),
        "message": message.strip(),
        "source": source.strip(),
    }

    with database.db() as conn:
        form = database.get_form_by_slug(conn, slug)
        if not form:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "폼을 찾을 수 없습니다.", "code": 404},
                status_code=404,
            )
        settings = database.get_all_settings(conn)

        # Honeypot: bots fill hidden field
        if website.strip():
            return RedirectResponse(
                url=f"/f/{slug}/success", status_code=status.HTTP_303_SEE_OTHER
            )

        ip = client_ip(request)
        if not database.check_rate_limit(conn, ip, limit=5, window=600):
            return render_public_form(
                request,
                form,
                settings,
                error="잠시 후 다시 시도해 주세요. (너무 많은 요청)",
                values=values,
                status_code=429,
            )

        if not values["name"] or len(values["name"]) < 2:
            return render_public_form(
                request,
                form,
                settings,
                error="이름을 입력해 주세요.",
                values=values,
                status_code=400,
            )

        phone_norm = validate_phone(values["phone"])
        if not phone_norm:
            return render_public_form(
                request,
                form,
                settings,
                error="올바른 휴대폰 번호를 입력해 주세요. (예: 010-1234-5678)",
                values=values,
                status_code=400,
            )

        # Field mapping
        # 분양: complex_name=관심단지, unit_size=타입, move_timing=연령대(age_group)
        # 인테리어:
        #   complex_name ← 시공 지역 (empty → shop default 한빛인테리어)
        #   budget ← 예산대
        #   unit_size ← 평수
        #   move_timing ← 희망 시기
        #   meta.work_type ← 시공 유형  (+ message prefix [시공유형])
        #   source ← 유입경로
        if is_interior:
            timing = values["move_timing"]
            msg = values["message"]
            if values["work_type"]:
                prefix = f"[{values['work_type']}]"
                msg = f"{prefix} {msg}".strip() if msg else prefix
            meta = {"work_type": values["work_type"]} if values["work_type"] else {}
            lead_complex = values["complex_name"] or form["complex_name"]
        else:
            timing = values["age_group"]
            msg = values["message"]
            meta = {}
            lead_complex = values["complex_name"] or form["complex_name"]

        database.create_lead(
            conn,
            {
                "form_id": form["id"],
                "name": values["name"],
                "phone": phone_norm,
                "complex_name": lead_complex,
                "budget": values["budget"],
                "unit_size": values["unit_size"],
                "move_timing": timing,
                "message": msg,
                "source": values["source"],
                "meta": meta,
            },
        )

    return RedirectResponse(
        url=f"/f/{slug}/success", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/f/{slug}/success", response_class=HTMLResponse)
async def form_success(request: Request, slug: str):
    with database.db() as conn:
        form = database.get_form_by_slug(conn, slug)
        if not form:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "폼을 찾을 수 없습니다.", "code": 404},
                status_code=404,
            )
        settings = database.get_all_settings(conn)
    return templates.TemplateResponse(
        "success.html",
        {"request": request, "form": form, "settings": settings},
    )


# ── Admin auth ───────────────────────────────────────────────


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    if require_admin(request):
        return RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "error": None},
    )


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["admin"] = True
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "admin/login.html",
        {"request": request, "error": "비밀번호가 올바르지 않습니다."},
        status_code=401,
    )


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


# ── Admin board ──────────────────────────────────────────────


@app.get("/admin", response_class=HTMLResponse)
async def admin_list(
    request: Request,
    status_filter: str | None = None,
    unread: str | None = None,
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    with database.db() as conn:
        leads = database.list_leads(
            conn,
            status=status_filter if status_filter in database.STATUSES else None,
            unread_only=unread == "1",
        )
        unread_count = database.count_unread(conn)

    return templates.TemplateResponse(
        "admin/list.html",
        {
            "request": request,
            "leads": leads,
            "statuses": database.STATUSES,
            "status_filter": status_filter or "",
            "unread_only": unread == "1",
            "unread_count": unread_count,
            "interior_status_labels": database.INTERIOR_STATUS_LABELS,
        },
    )


@app.get("/admin/leads/{lead_id}", response_class=HTMLResponse)
async def admin_detail(request: Request, lead_id: int):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    with database.db() as conn:
        lead = database.get_lead(conn, lead_id)
        if not lead:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "문의를 찾을 수 없습니다.", "code": 404},
                status_code=404,
            )
        if not lead["is_read"]:
            database.update_lead(conn, lead_id, mark_read=True)
            lead = database.get_lead(conn, lead_id)
        unread_count = database.count_unread(conn)

    interior = database.is_interior_form(lead["form_slug"] if lead else None)
    meta = database.parse_meta(lead["meta"] if lead and "meta" in lead.keys() else "")

    return templates.TemplateResponse(
        "admin/detail.html",
        {
            "request": request,
            "lead": lead,
            "statuses": database.STATUSES,
            "unread_count": unread_count,
            "is_interior": interior,
            "meta": meta,
            "interior_status_labels": database.INTERIOR_STATUS_LABELS,
        },
    )


@app.post("/admin/leads/{lead_id}", response_class=HTMLResponse)
async def admin_update_lead(
    request: Request,
    lead_id: int,
    status_value: str = Form(..., alias="status"),
    notes: str = Form(""),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    if status_value not in database.STATUSES:
        status_value = "미연락"

    with database.db() as conn:
        lead = database.get_lead(conn, lead_id)
        if not lead:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "문의를 찾을 수 없습니다.", "code": 404},
                status_code=404,
            )
        database.update_lead(conn, lead_id, status=status_value, notes=notes.strip())

    return RedirectResponse(
        url=f"/admin/leads/{lead_id}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings_page(request: Request):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    with database.db() as conn:
        settings = database.get_all_settings(conn)
        form = database.get_default_form(conn)
        unread_count = database.count_unread(conn)

    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "settings": settings,
            "form": form,
            "unread_count": unread_count,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@app.post("/admin/settings", response_class=HTMLResponse)
async def admin_settings_save(
    request: Request,
    form_title: str = Form(...),
    welcome_text: str = Form(...),
    success_text: str = Form(...),
    default_complex: str = Form(...),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    with database.db() as conn:
        database.set_setting(conn, "form_title", form_title.strip())
        database.set_setting(conn, "welcome_text", welcome_text.strip())
        database.set_setting(conn, "success_text", success_text.strip())
        database.set_setting(conn, "default_complex", default_complex.strip())
        form = database.get_default_form(conn)
        if form:
            conn.execute(
                """
                UPDATE forms
                SET title = ?, welcome_text = ?, success_text = ?, complex_name = ?
                WHERE id = ?
                """,
                (
                    form_title.strip(),
                    welcome_text.strip(),
                    success_text.strip(),
                    default_complex.strip(),
                    form["id"],
                ),
            )

    return RedirectResponse(
        url="/admin/settings?saved=1", status_code=status.HTTP_303_SEE_OTHER
    )



# ── Admin landing editor ─────────────────────────────────────


def _safe_landing_slug(slug: str) -> str | None:
    slug = resolve_landing_slug(slug)
    if slug in database.LANDING_SLUGS:
        return slug
    return None


def _upload_dir_for(slug: str) -> Path:
    dest = UPLOADS_DIR / slug
    dest.mkdir(parents=True, exist_ok=True)
    return dest


async def _save_upload(slug: str, file: UploadFile) -> str:
    """Save image under static/uploads/{slug}/ and return public /static/... path."""
    import uuid
    from datetime import datetime

    filename = (file.filename or "image").strip()
    ext = Path(filename).suffix.lower()
    content_type = (file.content_type or "").lower()
    mime_to_ext = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    if ext not in ALLOWED_IMAGE_EXTS:
        ext = mime_to_ext.get(content_type, "")
    if ext not in ALLOWED_IMAGE_EXTS:
        raise ValueError("jpg, png, webp만 업로드할 수 있습니다.")
    if content_type and content_type not in ALLOWED_IMAGE_MIME and content_type != "application/octet-stream":
        # Some mobile browsers send odd MIME; allow if extension is valid.
        if ext not in ALLOWED_IMAGE_EXTS:
            raise ValueError("jpg, png, webp만 업로드할 수 있습니다.")

    data = await file.read()
    if not data:
        raise ValueError("빈 파일입니다.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("이미지는 5MB 이하만 가능합니다.")

    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    name = f"{stamp}_{uuid.uuid4().hex[:8]}{ext}"
    dest_dir = _upload_dir_for(slug)
    dest = dest_dir / name
    dest.write_bytes(data)
    return f"/static/uploads/{slug}/{name}"


def _delete_upload_file(public_path: str) -> None:
    if not public_path or not public_path.startswith("/static/uploads/"):
        return
    rel = public_path[len("/static/") :]
    path = STATIC_DIR / rel
    try:
        if path.is_file() and path.resolve().is_relative_to(UPLOADS_DIR.resolve()):
            path.unlink(missing_ok=True)
    except Exception:
        pass


@app.get("/admin/landing", response_class=HTMLResponse)
async def admin_landing_index(request: Request):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(
        url="/admin/landing/dalseo-xi-zenique", status_code=status.HTTP_302_FOUND
    )


@app.get("/admin/landing/{slug}", response_class=HTMLResponse)
async def admin_landing_edit(request: Request, slug: str):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    slug = _safe_landing_slug(slug)
    if not slug:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "랜딩을 찾을 수 없습니다.", "code": 404},
            status_code=404,
        )

    with database.db() as conn:
        landing = database.get_landing(conn, slug)
        if not landing:
            return templates.TemplateResponse(
                "error.html",
                {"request": request, "message": "랜딩을 찾을 수 없습니다.", "code": 404},
                status_code=404,
            )
        unread_count = database.count_unread(conn)

    return templates.TemplateResponse(
        "admin/landing.html",
        {
            "request": request,
            "landing": landing,
            "slug": slug,
            "label": database.LANDING_LABELS.get(slug, slug),
            "preview_path": database.LANDING_PREVIEW_PATHS.get(slug, f"/l/{slug}"),
            "landing_slugs": database.LANDING_SLUGS,
            "landing_labels": database.LANDING_LABELS,
            "unread_count": unread_count,
            "saved": request.query_params.get("saved") == "1",
            "error": request.query_params.get("error"),
            "info": request.query_params.get("info"),
        },
    )


@app.post("/admin/landing/{slug}", response_class=HTMLResponse)
async def admin_landing_save(request: Request, slug: str):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    slug = _safe_landing_slug(slug)
    if not slug:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "랜딩을 찾을 수 없습니다.", "code": 404},
            status_code=404,
        )

    form = await request.form()
    highlights = []
    for i in range(1, 5):
        highlights.append(
            {
                "title": str(form.get(f"hl{i}_title") or "").strip(),
                "body": str(form.get(f"hl{i}_body") or "").strip(),
            }
        )

    with database.db() as conn:
        existing = database.get_landing(conn, slug) or {}
        database.update_landing(
            conn,
            slug,
            {
                "hero_title": str(form.get("hero_title") or "").strip(),
                "hero_subtitle": str(form.get("hero_subtitle") or "").strip(),
                "hero_cta": str(form.get("hero_cta") or "").strip(),
                "hero_eyebrow": str(form.get("hero_eyebrow") or "").strip(),
                "hero_lead": str(form.get("hero_lead") or "").strip(),
                "highlights": highlights,
                "price_range": str(form.get("price_range") or "").strip(),
                "price_note": str(form.get("price_note") or "").strip(),
                "disclaimer": str(form.get("disclaimer") or "").strip(),
                "fact_location": str(form.get("fact_location") or "").strip(),
                "fact_location_detail": str(form.get("fact_location_detail") or "").strip(),
                "fact_scale": str(form.get("fact_scale") or "").strip(),
                "fact_scale_detail": str(form.get("fact_scale_detail") or "").strip(),
                "fact_unit": str(form.get("fact_unit") or "").strip(),
                "fact_unit_detail": str(form.get("fact_unit_detail") or "").strip(),
                "fact_move_in": str(form.get("fact_move_in") or "").strip(),
                "fact_move_in_detail": str(form.get("fact_move_in_detail") or "").strip(),
                "hero_image": existing.get("hero_image") or "",
                "gallery": existing.get("gallery") or [],
            },
        )

    return RedirectResponse(
        url=f"/admin/landing/{slug}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/landing/{slug}/upload-hero")
async def admin_landing_upload_hero(
    request: Request,
    slug: str,
    image: UploadFile = File(...),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    slug = _safe_landing_slug(slug)
    if not slug:
        return RedirectResponse(url="/admin/landing", status_code=status.HTTP_302_FOUND)

    try:
        public_path = await _save_upload(slug, image)
    except ValueError as e:
        from urllib.parse import quote
        return RedirectResponse(
            url=f"/admin/landing/{slug}?error={quote(str(e))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    with database.db() as conn:
        existing = database.get_landing(conn, slug) or {}
        old = existing.get("hero_image") or ""
        if old and old != public_path:
            _delete_upload_file(old)
        database.set_landing_hero_image(conn, slug, public_path)

    return RedirectResponse(
        url=f"/admin/landing/{slug}?saved=1&info=hero",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/landing/{slug}/upload-gallery")
async def admin_landing_upload_gallery(
    request: Request,
    slug: str,
    image: UploadFile = File(...),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    slug = _safe_landing_slug(slug)
    if not slug:
        return RedirectResponse(url="/admin/landing", status_code=status.HTTP_302_FOUND)

    try:
        public_path = await _save_upload(slug, image)
    except ValueError as e:
        from urllib.parse import quote
        return RedirectResponse(
            url=f"/admin/landing/{slug}?error={quote(str(e))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    with database.db() as conn:
        existing = database.get_landing(conn, slug) or {}
        gallery = list(existing.get("gallery") or [])
        gallery.append(public_path)
        database.set_landing_gallery(conn, slug, gallery)

    return RedirectResponse(
        url=f"/admin/landing/{slug}?saved=1&info=gallery",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/landing/{slug}/gallery/delete")
async def admin_landing_gallery_delete(
    request: Request,
    slug: str,
    index: int = Form(...),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    slug = _safe_landing_slug(slug)
    if not slug:
        return RedirectResponse(url="/admin/landing", status_code=status.HTTP_302_FOUND)

    with database.db() as conn:
        existing = database.get_landing(conn, slug) or {}
        gallery = list(existing.get("gallery") or [])
        if 0 <= index < len(gallery):
            removed = gallery.pop(index)
            _delete_upload_file(removed)
            database.set_landing_gallery(conn, slug, gallery)

    return RedirectResponse(
        url=f"/admin/landing/{slug}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/landing/{slug}/gallery/move")
async def admin_landing_gallery_move(
    request: Request,
    slug: str,
    index: int = Form(...),
    direction: str = Form(...),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    slug = _safe_landing_slug(slug)
    if not slug:
        return RedirectResponse(url="/admin/landing", status_code=status.HTTP_302_FOUND)

    with database.db() as conn:
        existing = database.get_landing(conn, slug) or {}
        gallery = list(existing.get("gallery") or [])
        if 0 <= index < len(gallery):
            if direction == "up" and index > 0:
                gallery[index - 1], gallery[index] = gallery[index], gallery[index - 1]
            elif direction == "down" and index < len(gallery) - 1:
                gallery[index + 1], gallery[index] = gallery[index], gallery[index + 1]
            database.set_landing_gallery(conn, slug, gallery)

    return RedirectResponse(
        url=f"/admin/landing/{slug}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.post("/admin/landing/{slug}/clear-hero")
async def admin_landing_clear_hero(request: Request, slug: str):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)

    slug = _safe_landing_slug(slug)
    if not slug:
        return RedirectResponse(url="/admin/landing", status_code=status.HTTP_302_FOUND)

    with database.db() as conn:
        existing = database.get_landing(conn, slug) or {}
        old = existing.get("hero_image") or ""
        if old:
            _delete_upload_file(old)
        database.set_landing_hero_image(conn, slug, "")

    return RedirectResponse(
        url=f"/admin/landing/{slug}?saved=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@app.get("/health")
async def health():
    return {"ok": True, "app": "문의함"}
