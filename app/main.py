"""FastAPI application: REST API + static frontend."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import pymupdf
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app import __version__
from app.assistant import Assistant
from app.config import Settings, get_settings
from app.rag.pdf import PDFError
from app.schemas import CalcRequest, ChatRequest, ChatResponse, DocumentInfo, IngestResponse
from app.tools.models import CalcResult
from app.tools.registry import TOOLS, UnknownToolError, run_tool

log = logging.getLogger("app")
STATIC_DIR = Path(__file__).parent / "static"

EXAMPLES = [
    {"category": "Documents", "question": "Why do lightly loaded induction motors cause low power factor?"},
    {"category": "Documents", "question": "What conditions must be met to operate transformers in parallel?"},
    {"category": "Documents", "question": "How should loads be restored after a load-shedding event?"},
    {
        "category": "Documents",
        "question": "Why is the infinite-source fault current estimate not conservative for arc flash studies?",
    },
    {
        "category": "Calculation",
        "question": "Calculate the real and reactive power of a 400 V three-phase motor drawing 100 A at 0.85 power factor.",
    },
    {
        "category": "Calculation",
        "question": "How many kvar of capacitors are needed to correct 500 kW from 0.75 to 0.95 power factor?",
    },
    {
        "category": "Calculation",
        "question": "A 1000 kVA transformer supplies 720 kW at 0.8 power factor. What is its loading?",
    },
    {
        "category": "Calculation",
        "question": "What is the fault current at the secondary of a 1000 kVA, 400 V transformer with 6% impedance?",
    },
]


class RateLimiter:
    """Sliding-window limiter per client IP (in-memory; per process)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False
        q.append(now)
        return True


def create_app(settings: Settings | None = None, assistant: Assistant | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        a = assistant or Assistant(settings)
        if settings.auto_ingest_corpus and a.store.count() == 0 and settings.corpus_dir.is_dir():
            results = await run_in_threadpool(a.ingest_directory, settings.corpus_dir)
            log.info("Indexed %d sample documents", len(results))
        app.state.assistant = a
        log.info("Ready: mode=%s chunks=%d", a.mode, a.store.count())
        yield

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    limiter = RateLimiter(settings.rate_limit_per_minute)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def security_and_limits(request: Request, call_next):
        rid = uuid.uuid4().hex[:12]
        if request.method in ("POST", "DELETE") and request.url.path.startswith("/api/"):
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(client):
                return JSONResponse({"detail": "Rate limit exceeded. Try again in a minute."}, status_code=429)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > (settings.max_upload_mb + 1) * 1024 * 1024:
            return JSONResponse({"detail": f"Request body exceeds {settings.max_upload_mb} MB"}, status_code=413)
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        log.info(
            "%s %s %s %.0fms rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - t0) * 1000,
            rid,
        )
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    def get_assistant(request: Request) -> Assistant:
        return request.app.state.assistant

    def require_admin(authorization: str | None = Header(None)) -> None:
        token = settings.admin_token.get_secret_value()
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "Admin token required for this operation")

    # ------------------------------------------------------------------ routes
    @app.get("/api/health")
    def health(a: Assistant = Depends(get_assistant)) -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "mode": a.mode,
            "llm_model": a.llm.model if a.llm else None,
            "chunks_indexed": a.store.count(),
            "uploads_protected": bool(settings.admin_token.get_secret_value()),
            "max_upload_mb": settings.max_upload_mb,
        }

    @app.get("/api/examples")
    def examples() -> list[dict]:
        return EXAMPLES

    @app.get("/api/documents", response_model=list[DocumentInfo])
    def list_documents(a: Assistant = Depends(get_assistant)):
        return a.store.list_documents()

    @app.post("/api/documents", response_model=IngestResponse, dependencies=[Depends(require_admin)])
    async def upload_document(file: UploadFile = File(...), a: Assistant = Depends(get_assistant)):
        name = Path(file.filename or "upload.pdf").name
        name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:120] or "upload.pdf"
        if not name.lower().endswith(".pdf"):
            raise HTTPException(415, "Only PDF files are accepted")
        limit = settings.max_upload_mb * 1024 * 1024
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB")
        try:
            return await asyncio.wait_for(
                run_in_threadpool(a.ingest_bytes, data, name), timeout=settings.request_timeout_s
            )
        except PDFError as exc:
            raise HTTPException(422, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(504, "Document processing timed out") from exc

    @app.delete("/api/documents/{doc_id}", dependencies=[Depends(require_admin)])
    def delete_document(doc_id: str, a: Assistant = Depends(get_assistant)) -> dict:
        if not re.fullmatch(r"[0-9a-f]{16}", doc_id):
            raise HTTPException(400, "Invalid document id")
        n = a.delete_document(doc_id)
        if not n:
            raise HTTPException(404, "Document not found")
        return {"deleted_chunks": n}

    @app.get("/api/documents/{doc_id}/pages/{page}.png")
    def page_image(doc_id: str, page: int, a: Assistant = Depends(get_assistant)):
        path = a.pdf_path(doc_id)
        if path is None:
            raise HTTPException(404, "Document not found")
        with pymupdf.open(path) as doc:
            if not 1 <= page <= doc.page_count:
                raise HTTPException(404, "Page out of range")
            png = doc[page - 1].get_pixmap(dpi=110).tobytes("png")
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/chunks/{chunk_id}")
    def get_chunk(chunk_id: str, a: Assistant = Depends(get_assistant)) -> dict:
        if not re.fullmatch(r"[0-9a-f]{16}:p\d{1,4}:c\d{1,4}", chunk_id):
            raise HTTPException(400, "Invalid chunk id")
        hit = a.store.get_chunk(chunk_id)
        if hit is None:
            raise HTTPException(404, "Chunk not found")
        return {"chunk_id": hit.chunk_id, "text": hit.text, "metadata": hit.metadata}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest, a: Assistant = Depends(get_assistant)):
        try:
            return await asyncio.wait_for(
                run_in_threadpool(a.ask, req.question, req.doc_ids, req.top_k), timeout=settings.request_timeout_s
            )
        except TimeoutError as exc:
            raise HTTPException(504, "The request timed out. Please try again.") from exc

    @app.get("/api/tools")
    def list_tools() -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "schema": t.input_model.model_json_schema()}
            for t in TOOLS.values()
        ]

    @app.post("/api/calculate", response_model=CalcResult)
    def calculate(req: CalcRequest):
        try:
            return run_tool(req.tool, req.args)
        except UnknownToolError as exc:
            raise HTTPException(404, f"Unknown tool: {req.tool}") from exc
        except ValidationError as exc:
            errors = [{"field": ".".join(map(str, e["loc"])), "message": e["msg"]} for e in exc.errors()]
            raise HTTPException(422, {"message": "Invalid inputs", "errors": errors}) from exc

    # ------------------------------------------------------------------ frontend
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
