from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_fastapi_server(*, advanced_router: APIRouter | None = None) -> FastAPI:
    """Build the existing legacy application and optionally mount an enabled advanced router.

    The module-level `fastapi_server` calls this with no advanced router, preserving
    existing endpoint behavior and keeping advanced retrieval default-disabled.
    """
    from rag.api.routers import build_legacy_router

    app = FastAPI()
    app.include_router(build_legacy_router())
    if advanced_router is not None:
        app.include_router(advanced_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "accelerometer=(), camera=(), microphone=(), geolocation=()"
        return response

    @app.get("/")
    async def root():
        return {"message": "status", "status": "ok"}

    @app.get("/health")
    async def health():
        return {"message": "status", "status": "ok"}

    return app


fastapi_server = create_fastapi_server()


__all__ = ["create_fastapi_server", "fastapi_server"]
