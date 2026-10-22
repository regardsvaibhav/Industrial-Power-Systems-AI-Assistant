# Build log

| Stage | Result | Verified by |
|---|---|---|
| 1. Skeleton + health endpoint | FastAPI app, settings, `/api/health` | pytest, live `curl` |
| 2. Sample corpus | 7 original notes (21 pages) rendered to PDF; worked examples checked numerically | `scripts/build_corpus.py` |
| 3. Calculation tools | 7 validated tools + whitelist registry | 39 unit tests with hand-worked values |
| 4. RAG | Safe PDF parsing, page-aware chunking, Chroma + BM25, relevance gate, extractive and LLM answerers, citation validation, grounding check, injection stripping | `tests/test_rag.py`, `tests/test_llm.py` (mocked endpoint), `tests/test_security.py` |
| 5. Evaluation | 57-item benchmark; baseline run found 4 bugs (cross-page sentences, two parser gaps, eval gold-page bug); fixed and re-run | `reports/` |
| 6. Frontend | Chat, clickable citations with page images, upload, document filter, calculator forms with field errors, examples | Headless Chromium at 1440 px and 390 px, no horizontal overflow, no JS errors |
| 7. Docker + CI + security | Image bakes model and index; CI runs lint, tests (coverage floor 80%), eval thresholds, pip-audit, Docker smoke test | Local image build + `deploy/verify.py` against the container: 6/6 pass |
| 8. Deployment | Cloud Run script and Render blueprint ready | Not deployed yet: needs cloud credentials |

Not yet done:
- LLM-mode evaluation (needs an API key).
- CI has not run on GitHub yet (no repository yet).
- No cloud deployment yet.
