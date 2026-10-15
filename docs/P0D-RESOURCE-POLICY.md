# P0-D resource policy

All application defaults live in `app/security/resource_policy.py`, overridable by the corresponding `HERMES_` variable. Invalid/nonpositive settings fail configuration loading. Overrides require operational review; the static Nginx thresholds must remain compatible.

| Setting | Default | Rationale |
|---|---:|---|
| MAX_JSON_BODY_BYTES | 2 MiB | Bounded ordinary API payload |
| MAX_PARSE_TEXT_BYTES / CHARS | 1 MiB / 1,000,000 | Staffing text ceiling |
| MAX_FILE_BYTES | 10 MiB | Retains existing attachment ceiling |
| MAX_MULTIPART_BODY_BYTES | 12 MiB | File plus bounded form overhead |
| MAX_WEBHOOK_BODY_BYTES | 2 MiB | Preserve COMM notification bursts/payloads |
| MAX_SMALL_WEBHOOK_BODY_BYTES | 256 KiB | Telegram and future Gmail envelopes |
| MAX_MODEL_INPUT_BYTES / CHARS | 1 MiB / 200,000 | Final deterministic guard before registry/rendering/network |
| MAX_MESSAGES / MAX_MESSAGE_CHARS / MAX_TOTAL_HISTORY_CHARS | 50 / 20,000 / 100,000 | Bounded conversational context |
| MAX_SKILLS / MAX_PREFERRED_SKILLS / MAX_REQUIREMENTS / MAX_BULLETS | 500 each | Staffing collections, no silent truncation |
| MAX_JOBS / MAX_CANDIDATES / MAX_ACTIONS / MAX_EXPERIENCES / MAX_EDUCATION | 100 each | Batch/profile collection ceilings |
| MAX_CERTIFICATIONS / MAX_JOB_TITLES | 200 / 500 | Profile/taxonomy inputs |
| Other nested collections / mapping keys | 1,000 each | Catch unnamed collection bypasses |
| Nested depth / traversed nodes | 20 / 20,000 | Reject pathological JSON structures |
| MAX_PDF_PAGES | 100 | Staffing documents, not books |
| MAX_DOCX_ENTRIES | 1,000 | OpenXML package metadata ceiling |
| MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES | 40 MiB | Bounded aggregate decompression |
| MAX_DOCX_SINGLE_ENTRY_BYTES | 8 MiB | Bounded individual part |
| MAX_DOCX_COMPRESSION_RATIO | 100 | Reject high amplification |
| MAX_EXTRACTED_TEXT_CHARS | 1,000,000 | Before taxonomy/semantic understanding |
| DOCUMENT_PARSE_TIMEOUT_SECONDS | 45 | Enforceable local converter deadline |
| MAX_DOCUMENT_MEMORY_BYTES | 768 MiB | Isolated process address-space ceiling |
| BODY_TIMEOUT_SECONDS | 30 | Absolute application receive deadline |
| MAX_DOCUMENT_CONCURRENCY / MAX_MODEL_CONCURRENCY | 2 / 2 | Process-local scarce-resource capacity |
| MAX_EXPENSIVE_CONCURRENCY | 4 | Bound high-cost HTTP requests, including uploads |
| MAX_EXPENSIVE_REQUESTS_PER_MINUTE | 10 | Upload bucket per verified principal |
| MAX_MODEL_REQUESTS_PER_MINUTE | 20 | Retained aggregate model-route peak was 14/minute; avoids rejecting that observed burst |
| MAX_PARSE_REQUESTS_PER_MINUTE / MAX_ADMIN_REQUESTS_PER_MINUTE | 60 / 30 | Separate parse/admin buckets preserve ordinary service/bulk workflows |

The deployment is one Uvicorn process. Semaphores and rate buckets are intentionally process-local; a future multi-worker/replica deployment must account for multiplied aggregate capacity. Lightweight GETs and webhook deliveries are not rate limited. No Redis or global IP throttle is introduced.

## Boundaries

ASGI middleware counts actual bytes, including chunked requests, before forwarding any body to handlers. It rejects oversized Content-Length without reading the body. Expensive routes reuse the existing bearer parser/principal; upload permission checks occur before body reads. Authentication remains enforced by existing endpoint dependencies. JSON collection guards apply to all mutating routes, including legacy parse, context, resume, assistant, taxonomy and extraction paths. Disabled Gmail push bypasses body handling and retains its existing 410 rejection. COMM's bytes are replayed unchanged for HMAC verification.

Uploaded files are read in 64 KiB chunks with a 10 MiB ceiling and always closed. Only UTF-8 TXT/Markdown, structurally valid unencrypted PDF and ZIP/OpenXML DOCX are supported. Client MIME is checked but never treated as proof of format. Archive paths, duplicates, encryption, symlinks, nested archives, malformed central directory/CRC, entity declarations and excessive metadata sizes/ratios are rejected. Archive entries are never extracted to disk.

PDF preflight and existing MarkItDown/pdfplumber/python-docx extraction run in a dedicated subprocess. The parent kills and reaps only that process group at the deadline. Linux CPU/address-space/output-file limits add defense in depth. The worker disables networking and bounds BLAS threads. Temporary directories are generated and deleted on success/failure/timeout. Existing converters/semantic parsers are retained; no OCR/cloud fallback is added. Invalid or timed-out file extraction happens before durable intake/attachment/draft writes. Successful attachment retention follows the existing business contract.

The extracted-text guard precedes taxonomy, cache construction and semantic parsing. Prompt/fallback guards precede registry access and rendering; rendered-message checks and a final low-level LiteLLM guard cover assistant and direct taxonomy helpers without changing model selection. Lists, string totals and encoded bytes are rejected rather than truncated.

## Errors/logging

Safe JSON `detail.code`: 413 `PAYLOAD_TOO_LARGE`; 415 `UNSUPPORTED_MEDIA_TYPE`; 422 `INVALID_DOCUMENT` or `DOCUMENT_RESOURCE_LIMIT`; 408 `DOCUMENT_PARSE_TIMEOUT` or `REQUEST_TIMEOUT`; 429 `RESOURCE_BUSY` or `RATE_LIMITED`. Rejection logs contain reason/limit/route/verified principal metadata only. No document/body/credential/temp-path content is logged.

## Nginx persistence

`deploy/nginx/hermes-resource-limits.conf` must be copied to `/data/nginx/custom/hermes-resource-limits.conf` and referenced ONLY by Hermes proxy host ID 1's persistent NPM Advanced configuration:

```nginx
include /data/nginx/custom/hermes-resource-limits.conf;
```

Hermes gets 2 MiB default, 12 MiB on its two upload routes, and 256 KiB on Telegram. Header/body receive timeouts are 30 seconds; connect timeout 10 seconds; upstream send/read retain the existing 90-second normal proxy bound. Request/response buffering remains enabled. Other proxy hosts retain their existing configuration. Nginx syntax must pass before every reload; retain the NPM record, custom include and generated host file for rollback. NPM regeneration retains the Advanced-config include, so enforcement does not depend solely on manually editing a generated file.
