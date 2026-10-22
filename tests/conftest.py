import shutil
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.assistant import Assistant
from app.config import PROJECT_ROOT, Settings
from app.main import create_app
from app.rag.store import VectorStore

CORPUS = PROJECT_ROOT / "data" / "corpus"


def make_pdf(pages: list[str], title: str = "Test doc", path: Path | None = None) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    doc.set_metadata({"title": title})
    data = doc.tobytes()
    doc.close()
    if path:
        path.write_bytes(data)
    return data


@pytest.fixture(scope="session")
def session_dirs(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("ipa")


@pytest.fixture(scope="session")
def settings(session_dirs) -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="",
        chroma_dir=session_dirs / "chroma",
        upload_dir=session_dirs / "uploads",
        corpus_dir=CORPUS,
        rate_limit_per_minute=10000,
    )


@pytest.fixture(scope="session")
def store(settings) -> VectorStore:
    return VectorStore(settings.chroma_dir, "test_docs")


@pytest.fixture(scope="session")
def assistant(settings, store) -> Assistant:
    a = Assistant(settings, store=store, llm=None)
    if store.count() == 0:
        a.ingest_directory(CORPUS)
    return a


@pytest.fixture(scope="session")
def client(settings, assistant):
    app = create_app(settings, assistant=assistant)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def isolated_settings(tmp_path) -> Settings:
    """Fresh, empty store for tests that mutate documents."""
    return Settings(
        _env_file=None,
        llm_api_key="",
        chroma_dir=tmp_path / "chroma",
        upload_dir=tmp_path / "uploads",
        corpus_dir=tmp_path / "corpus-none",
        rate_limit_per_minute=10000,
    )


@pytest.fixture
def isolated_client(isolated_settings):
    store = VectorStore(isolated_settings.chroma_dir, "iso")
    a = Assistant(isolated_settings, store=store, llm=None)
    with TestClient(create_app(isolated_settings, assistant=a)) as c:
        yield c
    shutil.rmtree(isolated_settings.chroma_dir, ignore_errors=True)
