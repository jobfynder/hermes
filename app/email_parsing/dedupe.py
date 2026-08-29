import hashlib
from typing import Any

from app.runtime.db import cursor


def compute_body_hash(text: str) -> str:
    '''sha256 of the raw body text -- the exact-content duplicate key
    (spec section 12.1, layer 2). Deliberately hashes raw text, not the
    cleaned/parsed record, so two deliveries of literally the same email
    body match even before any parsing happens.
    '''
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def find_exact_content_duplicate(body_hash: str) -> str | None:
    '''Returns the duplicate_key of the first message seen with this exact
    body hash, or None if this is the first time this content has arrived.
    A transport-level retry of the *same* message never reaches here (it is
    caught earlier by build_duplicate_key's channel:source_message_id
    check) -- this catches the same content arriving under a *different*
    provider_message_id, e.g. an email forwarded to two aliases, or
    re-sent by the provider with a new id.

    Queried fresh from the database every call (no in-process cache) so
    this is correct across hermes-api and hermes-graph-consumer, which
    run as separate processes and would otherwise each hold a stale,
    independent view of what has already been seen.
    '''
    with cursor() as cur:
        cur.execute(
            'SELECT duplicate_key FROM content_hash_index WHERE body_hash = %s',
            (body_hash,),
        )
        row = cur.fetchone()

    return row['duplicate_key'] if row else None


def record_content_hash(body_hash: str, duplicate_key: str) -> None:
    with cursor() as cur:
        cur.execute(
            'INSERT INTO content_hash_index (body_hash, duplicate_key) VALUES (%s, %s) '
            'ON CONFLICT (body_hash) DO NOTHING',
            (body_hash, duplicate_key),
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
