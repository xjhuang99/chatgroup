from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from actr.deps import templates
from admin_auth import check_auth, get_auth_principal, is_super_admin

router = APIRouter(tags=["pages"])


def _login_redirect(next_path: str) -> RedirectResponse:
    safe = quote(next_path or "/", safe="/?=&")
    return RedirectResponse(url=f"/login?redirect={safe}", status_code=302)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if check_auth(request):
        target = (request.query_params.get("redirect") or "/").strip()
        if not target.startswith("/"):
            target = "/"
        return RedirectResponse(url=target, status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/home", response_class=HTMLResponse)
async def home_page(request: Request):
    """Public profile / CV-style intro (no login required)."""
    return templates.TemplateResponse("home.html", {"request": request})


@router.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if not check_auth(request):
        return _login_redirect("/")
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/wait", response_class=HTMLResponse)
async def wait_page(request: Request):
    return templates.TemplateResponse("wait.html", {"request": request})


@router.get("/chat/{session_id}/{group_id}", response_class=HTMLResponse)
async def chat_page(request: Request, session_id: str, group_id: str):
    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "session_id": session_id, "group_id": group_id},
    )


@router.get("/embed.html", response_class=HTMLResponse)
async def embed_page(request: Request):
    return templates.TemplateResponse("embed.html", {"request": request})


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    if not check_auth(request):
        return _login_redirect("/admin")
    return templates.TemplateResponse("admin.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    if not check_auth(request):
        return _login_redirect("/")
    return RedirectResponse(url="/", status_code=302)


@router.get("/manual", response_class=HTMLResponse)
async def manual_page(request: Request):
    if not check_auth(request):
        return _login_redirect("/manual")
    return templates.TemplateResponse("manual.html", {"request": request})


@router.get("/join", response_class=HTMLResponse)
async def join_page(request: Request):
    return templates.TemplateResponse("join.html", {"request": request})


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@router.get("/admin/accounts", response_class=HTMLResponse)
async def admin_accounts_page(request: Request):
    principal = get_auth_principal(request)
    if not is_super_admin(principal):
        if not check_auth(request):
            return _login_redirect("/admin/accounts")
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("admin_accounts.html", {"request": request})


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    if not check_auth(request):
        return _login_redirect("/account")
    return templates.TemplateResponse("account.html", {"request": request})
