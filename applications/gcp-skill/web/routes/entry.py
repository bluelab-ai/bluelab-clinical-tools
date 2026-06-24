"""Entry route: login/register → real name → role → experience → learning."""
from fastapi import APIRouter, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from web.config import ROLES
from web.user_manager import create_user, verify_login, load_account, set_real_name, add_role
from web.record_manager import find_records, create_record, load_record, get_progress_summary

router = APIRouter()

# Clean display labels (Chinese-first, English key appended) — frontend only
ROLE_DISPLAY = {
    "PI": "主要研究者/医生 (PI)",
    "CRA": "临床监查员 (CRA)",
    "CRC": "临床研究协调员 (CRC)",
    "student": "其他学员 (Student)",
}


# ============================================================
# Step 1: Login / Register
# ============================================================

@router.get("/", response_class=HTMLResponse)
async def entry_page(request: Request):
    """Login/Register page."""
    return request.app.state.templates.TemplateResponse("entry.html", {
        "request": request,
        "step": "login",
    })


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request,
                username: str = Form(...),
                password: str = Form(...)):
    """Verify credentials and redirect."""
    account = verify_login(username, password)
    if not account:
        return request.app.state.templates.TemplateResponse("entry.html", {
            "request": request,
            "step": "login",
            "error": "用户名或密码错误，请重试。",
        })

    # New user without real name → ask for name
    if not account.get("real_name"):
        resp = RedirectResponse(url="/entry/name", status_code=303)
        resp.set_cookie("username", username)
        return resp

    # Returning user with real name → go to dashboard
    resp = RedirectResponse(url="/entry/dashboard", status_code=303)
    resp.set_cookie("username", username)
    return resp


@router.post("/register", response_class=HTMLResponse)
async def register(request: Request,
                   username: str = Form(...),
                   password: str = Form(...),
                   org_type: str = Form(...),
                   job_role: str = Form(...)):
    """Create a new user account."""
    try:
        create_user(username, password, org_type=org_type, job_role=job_role)
    except ValueError as e:
        return request.app.state.templates.TemplateResponse("entry.html", {
            "request": request,
            "step": "login",
            "error": str(e),
        })

    resp = RedirectResponse(url="/entry/name", status_code=303)
    resp.set_cookie("username", username)
    return resp


# ============================================================
# Step 2: Real name input (only for new users)
# ============================================================

@router.get("/entry/name", response_class=HTMLResponse)
async def entry_name_page(request: Request,
                          username: str = Cookie(None)):
    """Ask for real name (printed on certificate)."""
    if not username:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    if account and account.get("real_name"):
        return RedirectResponse(url="/entry/dashboard", status_code=303)

    return request.app.state.templates.TemplateResponse("entry.html", {
        "request": request,
        "step": "real_name",
        "username": username,
    })


@router.post("/entry/name", response_class=HTMLResponse)
async def entry_name_submit(request: Request,
                            real_name: str = Form(...),
                            username: str = Cookie(None)):
    """Save real name, proceed to role selection."""
    if not username:
        return RedirectResponse(url="/", status_code=303)

    set_real_name(username, real_name)
    return RedirectResponse(url="/entry/role", status_code=303)


# ============================================================
# Step 3: Role selection (dashboard for returning users)
# ============================================================

@router.get("/entry/dashboard", response_class=HTMLResponse)
async def entry_dashboard(request: Request,
                          username: str = Cookie(None)):
    """Show existing records or role selection."""
    if not username:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    if not account:
        return RedirectResponse(url="/", status_code=303)

    records = find_records(username)
    real_name = account.get("real_name", username)

    # Add progress summaries
    for rec in records:
        rec["progress_summary"] = get_progress_summary(rec["data"])

    return request.app.state.templates.TemplateResponse("entry.html", {
        "request": request,
        "step": "dashboard",
        "username": username,
        "learner_name": real_name,
        "records": records,
        "roles": ROLES,
        "role_display": ROLE_DISPLAY,
        "rec_count": len(records),
    })


@router.get("/entry/role", response_class=HTMLResponse)
async def entry_role_page(request: Request,
                          username: str = Cookie(None)):
    """Role + experience selection (for new and returning users)."""
    if not username:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    if not account:
        return RedirectResponse(url="/", status_code=303)

    return request.app.state.templates.TemplateResponse("entry.html", {
        "request": request,
        "step": "role_select",
        "username": username,
        "learner_name": account.get("real_name", username),
        "roles": ROLES,
        "role_display": ROLE_DISPLAY,
    })


@router.post("/entry/role", response_class=HTMLResponse)
async def entry_role_submit(request: Request,
                            role: str = Form(...),
                            has_basis: str = Form("no"),
                            username: str = Cookie(None)):
    """Create record from role selection and redirect to learning."""
    if not username:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)
    real_name = account.get("real_name", username) if account else username
    role_info = ROLES.get(role, ROLES["student"])
    has_old = has_basis == "yes"

    add_role(username, role, role_info["label"], has_old)
    create_record(username, real_name, role, role_info["label"], has_old)

    resp = RedirectResponse(
        url="/learn/start" if not has_old else "/learn/diff",
        status_code=303
    )
    resp.set_cookie("learner_role", role)
    return resp


# ============================================================
# Step 4: Resume / New role from dashboard
# ============================================================

@router.post("/entry/resume", response_class=HTMLResponse)
async def entry_resume(request: Request,
                       role: str = Form(...),
                       username: str = Cookie(None)):
    """Resume an existing record, or go to new-role form."""
    if not username:
        return RedirectResponse(url="/", status_code=303)

    account = load_account(username)

    # "New role" option
    if role == "__new__":
        return request.app.state.templates.TemplateResponse("entry.html", {
            "request": request,
            "step": "role_select",
            "username": username,
            "learner_name": account.get("real_name", username) if account else username,
            "roles": ROLES,
            "role_display": ROLE_DISPLAY,
        })

    # Resume existing record
    record = load_record(username, role)
    if not record:
        return RedirectResponse(url="/entry/dashboard", status_code=303)

    # Redirect based on track
    track = record.get("learner_track", "novice")
    if track == "experienced":
        next_url = "/learn/diff"
    else:
        next_url = "/learn/start"

    resp = RedirectResponse(url=next_url, status_code=303)
    resp.set_cookie("learner_role", role)
    return resp
