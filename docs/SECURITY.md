# Security notes

## Threat model (what this app defends against)

| Threat | Mitigation | Where |
|---|---|---|
| Prompt injection in the user's question | Pattern screen; matching questions are refused before retrieval | `app/security.py`, `Assistant.ask` |
| Prompt injection hidden in an uploaded document | Instruction-like sentences are stripped from retrieved text before it reaches the LLM; the citation is flagged in the UI; sources are escaped and wrapped in delimiters; the system prompt says source text is data | `strip_injected_sentences`, `build_user_prompt` |
| Invented citations | Only source ids that were actually supplied survive; an answer with no valid citation becomes an abstention | `llm_answer` |
| Hallucinated numbers | Grounding check flags numbers that are not in the cited sources; the LLM is told not to do arithmetic; all calculations run in tested Python | `app/rag/grounding.py`, `app/tools/` |
| Arbitrary code / tool abuse via the LLM | Tool calls are limited to a whitelist and every argument is validated by a Pydantic schema before any computation; there is no code execution path | `app/tools/registry.py` |
| Malicious or oversized PDFs | Magic-byte check, size limit (body size is also checked before reading), page limit, encrypted PDFs rejected, parsing from memory, server-generated storage names (content hash), control characters removed | `app/rag/pdf.py`, `/api/documents` |
| XSS through answers or document text | Frontend inserts all dynamic text with `textContent`; strict Content-Security-Policy (`script-src 'self'`, no inline script) | `app/static/app.js`, middleware in `app/main.py` |
| Secret leakage | `SecretStr` settings, never logged or returned; `.env` is git- and docker-ignored; LLM error text is redacted; deployment uses a secret manager | `app/config.py`, `deploy/cloudrun.sh` |
| Abuse / cost blow-up | Per-IP rate limit on write and chat endpoints, request timeouts, LLM timeout and bounded retries, `max_tokens` cap | `app/main.py`, `app/llm/client.py` |
| Unauthorised document changes | Optional `ADMIN_TOKEN` bearer token on upload/delete | `require_admin` |

Heuristic injection detection cannot be complete. The layers above are designed so that
a missed injection still cannot run tools with invalid inputs, invent sources, or exfiltrate
secrets (the model never sees them).

## Dependency audit

`pip-audit` (CI job `security`) reports advisories against `chromadb` 1.5.9 with no fixed
release at the time of writing:

- PYSEC-2026-311 / CVE-2026-45829 and PYSEC-2026-3814 / CVE-2026-45833: code injection
  through the Chroma **server** collections HTTP endpoints (`trust_remote_code`).
- PYSEC-2026-3813 / CVE-2026-45830 and PYSEC-2026-3815 / CVE-2026-45831: tenant
  authorisation flaws in the Chroma **server** RBAC.

This application uses Chroma only as an embedded library (`PersistentClient`). It never
starts the Chroma HTTP server, never exposes Chroma endpoints, and never passes
`trust_remote_code`. The advisories are therefore not reachable, and they are ignored by ID
in CI so that any *new* advisory still fails the build. Re-check when Chroma publishes a
fix, and do not run `chroma run` on this deployment.

## Operational guidance

- Set `ADMIN_TOKEN` on any public deployment, otherwise anyone can upload documents.
- Store `LLM_API_KEY` and `ADMIN_TOKEN` in the platform's secret manager.
- Do not upload confidential documents to a deployment that uses a third-party LLM API:
  retrieved passages are sent to that API.
- The rate limiter is in-memory per instance; put a gateway or Cloud Armor in front for
  stronger protection.
