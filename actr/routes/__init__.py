from fastapi import FastAPI

from actr.routes import admin, auth, export, groups, matching, pages, sessions, usage, websocket


def register_routes(app: FastAPI) -> None:
    for module in (
        auth,
        pages,
        groups,
        sessions,
        admin,
        usage,
        export,
        matching,
        websocket,
    ):
        app.include_router(module.router)
