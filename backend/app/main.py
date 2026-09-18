from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import seed
from app.errors import ApiError
from app.routers import api

app = FastAPI(title="Ladderbill", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.message, "detail": exc.extra},
    )


@app.on_event("startup")
def _startup():
    seed.init_db()


app.include_router(api)


@app.get("/api/health")
def health():
    return {"ok": True, "project": "ladderbill"}
