import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import auth, employees, ingress, ops, outpero, platform, voice_ws, webhooks, workspaces

settings = get_settings()

logging.basicConfig(level=logging.INFO)
logging.getLogger("app.services.voice").setLevel(logging.INFO)

app = FastAPI(title="Karyuk API", version="0.1.0")


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "Unexpected server error",
            "request_id": getattr(request.state, "request_id", "unknown"),
        },
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, str | list[str]]:
    settings = get_settings()
    base = settings.public_api_base_url.rstrip("/")
    return {
        "service": "Karyuk API",
        "health": "/health",
        "docs": "/docs",
        "public_base_configured": base,
        "exotel_voice_example": f"{base}/v1/webhooks/exotel/voice/{{call_id}}",
        "exotel_status_example": f"{base}/v1/webhooks/exotel/status/{{call_id}}",
        "outpero_webhook_example": f"{base}/v1/webhooks/outpero/{{workspace_id}}",
        "outpero_inbound_webhook_example": (
            f"{base}/v1/webhooks/outpero/inbound/{{connection_key}}"
        ),
        "hint": "Open /health to verify the tunnel. Restart API after changing PUBLIC_API_BASE_URL in .env.",
    }


def _voice_build_sha() -> str:
    return (os.getenv("KARYUK_VOICE_BUILD_SHA") or "unknown").strip()[:64]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "modules": "m01-m15", "voice_build_sha": _voice_build_sha()}


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "voice_build_sha": _voice_build_sha()}


@app.on_event("startup")
def bootstrap_outpero_agent() -> None:
    """Register default voice agent from OUTPERO_DEFAULT_* env when present."""
    from app.database import SessionLocal
    from app.services.outpero.agents import ensure_env_agent
    from app.services.outpero.inbound_bootstrap import ensure_inbound_connection

    db = SessionLocal()
    try:
        agent = ensure_env_agent(db)
        if agent:
            logging.getLogger(__name__).info(
                "Voice agent ready slug=%s workspace=%s", agent.slug, agent.workspace_id
            )
        conn = ensure_inbound_connection(db)
        if conn:
            logging.getLogger(__name__).info(
                "Outpero inbound connection ready key=%s", conn.connection_key
            )
    except Exception:
        logging.getLogger(__name__).exception("Voice agent env bootstrap failed")
    finally:
        db.close()


app.include_router(auth.router)
app.include_router(workspaces.router)
app.include_router(employees.router)
app.include_router(platform.router)
app.include_router(ingress.router)
app.include_router(webhooks.router)
app.include_router(outpero.router)
app.include_router(voice_ws.router)
app.include_router(ops.router)