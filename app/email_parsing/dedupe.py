import hashlib
from datetime import UTC, datetime
from typing import Any

from app.runtime.jsonl_store import append_jsonl, read_jsonl, runtime_path


CONTENT_HASH_LOG = runtime_path('intake', 'content_hashes.jsonl')

_content_hash_index: dict[str, str] | None = None


def compute_body_hash(text: str) -> str:
    '''sha256 of the raw body text -- the exact-content duplicate key
    (spec section 12.1, layer 2). Deliberately hashes raw text, not the
    cleaned/parsed record, so two deliveries of literally the same email
    body match even before any parsing happens.
    '''
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def _load_index() -> dict[str, str]:
    global _content_hash_index

    if _content_hash_index is None:
        _content_hash_index = {}
        for item in read_jsonl(CONTENT_HASH_LOG):
            body_hash = item.get('body_hash')
            duplicate_key = item.get('duplicate_key')
            if body_hash and duplicate_key and body_hash not in _content_hash_index:
                _content_hash_index[body_hash] = duplicate_key

    return _content_hash_index


def find_exact_content_duplicate(body_hash: str) -> str | None:
    '''Returns the duplicate_key of the first message seen with this exact
    body hash, or None if this is the first time this content has arrived.
    A transport-level retry of the *same* message never reaches here (it is
    caught earlier by build_duplicate_key's channel:source_message_id
    check) -- this catches the same content arriving under a *different*
    provider_message_id, e.g. an email forwarded to two aliases, or
    re-sent by the provider with a new id.
    '''
    return _load_index().get(body_hash)


def record_content_hash(body_hash: str, duplicate_key: str) -> None:
    index = _load_index()

    if body_hash in index:
        return  # first-seen record for this hash already logged; never overwritten

    index[body_hash] = duplicate_key
    append_jsonl(
        CONTENT_HASH_LOG,
        {
            'recorded_at': datetime.now(UTC).isoformat(),
            'body_hash': body_hash,
            'duplicate_key': duplicate_key,
        },
    )


def register_and_check(text: str, duplicate_key: str) -> dict[str, Any]:
    '''One call for the common case: hash the body, check for a prior exact
    match, and register this message under the hash if it is the first.
    duplicate_group_id is the hash itself -- deterministic and requires no
    separate id allocator (spec 12.1: "link to exact duplicate group").
    '''
    body_hash = compute_body_hash(text)
    canonical_duplicate_key = find_exact_content_duplicate(body_hash)
    is_duplicate = canonical_duplicate_key is not None

    if not is_duplicate:
        record_content_hash(body_hash, duplicate_key)

    return {
        'body_hash': body_hash,
        'duplicate_group_id': body_hash,
        'is_exact_content_duplicate': is_duplicate,
        'canonical_duplicate_key': canonical_duplicate_key or duplicate_key,
    }
