"""Central deterministic resource ceilings; no content is included in errors/logs."""
import json
import logging
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException

def setting(name, default):
    value = int(os.getenv('HERMES_' + name, default))
    if value <= 0:
        raise ValueError('Resource limits must be positive')
    return value

MAX_JSON_BODY_BYTES = setting('MAX_JSON_BODY_BYTES', 2 * 1024**2)
MAX_PARSE_TEXT_BYTES = setting('MAX_PARSE_TEXT_BYTES', 1024**2)
MAX_PARSE_TEXT_CHARS = setting('MAX_PARSE_TEXT_CHARS', 1_000_000)
MAX_FILE_BYTES = setting('MAX_FILE_BYTES', 10 * 1024**2)
MAX_MULTIPART_BODY_BYTES = setting('MAX_MULTIPART_BODY_BYTES', 12 * 1024**2)
MAX_WEBHOOK_BODY_BYTES = setting('MAX_WEBHOOK_BODY_BYTES', 2 * 1024**2)
MAX_SMALL_WEBHOOK_BODY_BYTES = setting('MAX_SMALL_WEBHOOK_BODY_BYTES', 256 * 1024)
MAX_MODEL_INPUT_BYTES = setting('MAX_MODEL_INPUT_BYTES', 1024**2)
MAX_MODEL_INPUT_CHARS = setting('MAX_MODEL_INPUT_CHARS', 200_000)
MAX_MESSAGES = setting('MAX_MESSAGES', 50)
MAX_MESSAGE_CHARS = setting('MAX_MESSAGE_CHARS', 20_000)
MAX_TOTAL_HISTORY_CHARS = setting('MAX_TOTAL_HISTORY_CHARS', 100_000)
MAX_PDF_PAGES = setting('MAX_PDF_PAGES', 100)
MAX_DOCX_ENTRIES = setting('MAX_DOCX_ENTRIES', 1000)
MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES = setting('MAX_DOCX_TOTAL_UNCOMPRESSED_BYTES', 40 * 1024**2)
MAX_DOCX_SINGLE_ENTRY_BYTES = setting('MAX_DOCX_SINGLE_ENTRY_BYTES', 8 * 1024**2)
MAX_DOCX_COMPRESSION_RATIO = setting('MAX_DOCX_COMPRESSION_RATIO', 100)
MAX_EXTRACTED_TEXT_CHARS = setting('MAX_EXTRACTED_TEXT_CHARS', 1_000_000)
DOCUMENT_PARSE_TIMEOUT_SECONDS = setting('DOCUMENT_PARSE_TIMEOUT_SECONDS', 45)
DOCUMENT_MEMORY_BYTES = setting('MAX_DOCUMENT_MEMORY_BYTES', 768 * 1024**2)
BODY_TIMEOUT_SECONDS = setting('BODY_TIMEOUT_SECONDS', 30)
MAX_DOCUMENT_CONCURRENCY = setting('MAX_DOCUMENT_CONCURRENCY', 2)
MAX_MODEL_CONCURRENCY = setting('MAX_MODEL_CONCURRENCY', 2)
MAX_EXPENSIVE_CONCURRENCY = setting('MAX_EXPENSIVE_CONCURRENCY', 4)
MAX_EXPENSIVE_REQUESTS_PER_MINUTE = setting('MAX_EXPENSIVE_REQUESTS_PER_MINUTE', 10)
MAX_MODEL_REQUESTS_PER_MINUTE = setting('MAX_MODEL_REQUESTS_PER_MINUTE', 20)
MAX_PARSE_REQUESTS_PER_MINUTE = setting('MAX_PARSE_REQUESTS_PER_MINUTE', 60)
MAX_ADMIN_REQUESTS_PER_MINUTE = setting('MAX_ADMIN_REQUESTS_PER_MINUTE', 30)
MAX_MODEL_CALLS_PER_REQUEST = setting('MAX_MODEL_CALLS_PER_REQUEST', 4)
MODEL_REQUEST_BUDGET = ContextVar('hermes_model_request_budget', default=None)
_budget_lock = threading.Lock()
LIST_LIMITS = {k: setting('MAX_' + k.upper(), n) for k, n in {
    'skills': 500, 'preferred_skills': 500, 'requirements': 500, 'bullets': 500,
    'jobs': 100, 'candidates': 100, 'actions': 100, 'experiences': 100,
    'education': 100, 'certifications': 200, 'messages': MAX_MESSAGES,
    'history': MAX_MESSAGES, 'job_titles': 500, 'candidate_ids': 100,
    'job_ids': 100, 'allowed_actions': 100, 'experience': 100,
}.items()}
_documents = threading.BoundedSemaphore(MAX_DOCUMENT_CONCURRENCY)
_models = threading.BoundedSemaphore(MAX_MODEL_CONCURRENCY)
logger = logging.getLogger('hermes.resource_safety')

def consume_model_attempt():
    budget = MODEL_REQUEST_BUDGET.get()
    if budget is not None:
        with _budget_lock:
            if budget['calls'] >= MAX_MODEL_CALLS_PER_REQUEST:
                reject('RESOURCE_BUSY', 429, resource='model_attempts')
            budget['calls'] += 1

def reject(code, status=413, **metadata):
    logger.warning('resource_rejected code=%s metadata=%s', code, metadata)
    raise HTTPException(status_code=status, detail={'code': code})

@contextmanager
def capacity(kind):
    semaphore = _documents if kind == 'document' else _models
    if not semaphore.acquire(blocking=False):
        reject('RESOURCE_BUSY', 429, resource=kind)
    try:
        yield
    finally:
        semaphore.release()

def guard_text(text, *, extracted=False):
    limit = MAX_EXTRACTED_TEXT_CHARS if extracted else MAX_PARSE_TEXT_CHARS
    if len(text) > limit or (not extracted and len(text.encode('utf-8')) > MAX_PARSE_TEXT_BYTES):
        reject('DOCUMENT_RESOURCE_LIMIT' if extracted else 'PAYLOAD_TOO_LARGE',
               422 if extracted else 413, limit=limit)

def guard_structure(value, *, model=False):
    """Bound all nested collections, depth and aggregate strings; never truncate."""
    total = 0
    nodes = 0
    def walk(v, key='', depth=0):
        nonlocal total, nodes
        nodes += 1
        if depth > 20 or nodes > 20_000:
            reject('PAYLOAD_TOO_LARGE')
        if hasattr(v, 'model_dump'):
            v = v.model_dump()
        if isinstance(v, str):
            total += len(v)
            if len(v) > (MAX_MODEL_INPUT_CHARS if model else MAX_PARSE_TEXT_CHARS):
                reject('PAYLOAD_TOO_LARGE')
        elif isinstance(v, dict):
            if len(v) > 1000:
                reject('PAYLOAD_TOO_LARGE')
            for k, item in v.items():
                walk(str(k), '', depth + 1)
                walk(item, str(k).lower(), depth + 1)
        elif isinstance(v, (list, tuple)):
            if len(v) > LIST_LIMITS.get(key, 1000):
                reject('PAYLOAD_TOO_LARGE', limit=LIST_LIMITS.get(key, 1000))
            if key in {'messages', 'history'}:
                history_size = 0
                for item in v:
                    s = item if isinstance(item, str) else json.dumps(item.model_dump() if hasattr(item, 'model_dump') else item, ensure_ascii=False)
                    if len(s) > MAX_MESSAGE_CHARS:
                        reject('PAYLOAD_TOO_LARGE')
                    history_size += len(s)
                if history_size > MAX_TOTAL_HISTORY_CHARS:
                    reject('PAYLOAD_TOO_LARGE')
            for item in v:
                walk(item, '', depth + 1)
    walk(value)
    if model:
        if total > MAX_MODEL_INPUT_CHARS:
            reject('PAYLOAD_TOO_LARGE', limit=MAX_MODEL_INPUT_CHARS)
        serialized = json.dumps(value, ensure_ascii=False, default=lambda x: x.model_dump()).encode('utf-8')
        if len(serialized) > MAX_MODEL_INPUT_BYTES:
            reject('PAYLOAD_TOO_LARGE', limit=MAX_MODEL_INPUT_BYTES)
