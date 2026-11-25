import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.routes import applications, auth, jobs, outreach, system, tracker
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.ratelimit import limiter

settings = get_settings()
setup_logging(settings.log_level)
log = logging.getLogger("hirenza")

app = FastAPI(title="Hirenza AI Job Hunter", version="0.1.0",
              docs_url=None if settings.is_production else "/docs")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error", extra={"ctx": {"path": request.url.path}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(system.health)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(system.router)
app.include_router(applications.router)
app.include_router(outreach.router)
app.include_router(tracker.router)
