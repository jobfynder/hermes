"""Bounded server-side listing for the review dashboard."""
import math
from app.runtime.db import cursor

RECORDS = "payload->'structured_data'->'email_parsing'->'records'"
TITLE = f"""CASE
    WHEN draft_type='draft_job_requirement' THEN COALESCE(NULLIF({RECORDS}->0->>'job_title',''),title,'(untitled)')
    WHEN draft_type='draft_hotlist' AND jsonb_typeof({RECORDS})='array' AND jsonb_array_length({RECORDS})>1
        THEN 'Hotlist — ' || jsonb_array_length({RECORDS}) || ' consultants'
    WHEN draft_type='draft_hotlist' THEN COALESCE(NULLIF({RECORDS}->0->>'candidate_name',''),title,'(untitled)')
    ELSE COALESCE(title,'(untitled)') END"""


def list_draft_page(page=1, page_size=50, status=None, draft_type=None, search='', include_duplicates=False):
    if page < 1 or not 1 <= page_size <= 200:
        raise ValueError('Invalid pagination')
    base = 'TRUE' if include_duplicates else "COALESCE(metadata->>'exact_content_duplicate_of','')=''"
    conditions = [base]
    params = []
    if status:
        conditions.append('status=%s')
        params.append(status)
    if draft_type:
        conditions.append('draft_type=%s')
        params.append(draft_type)
    search = search.strip()
    if search:
        literal = search.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        conditions.append(f"concat_ws(' ',({TITLE}),metadata->'sender'->>'email',metadata->'original_sender_candidate'->>'email',source_message_id) ILIKE %s")
        params.append('%'+literal+'%')
    where = ' AND '.join(conditions)
    with cursor() as cur:
        cur.execute(f"SELECT count(*) AS total,count(*) FILTER(WHERE status='needs_review') AS review,count(*) FILTER(WHERE status='spam') AS spam FROM drafts WHERE {base}")
        counts = cur.fetchone()
        if len(conditions) == 1:
            total = counts['total']
        else:
            cur.execute(f'SELECT count(*) AS total FROM drafts WHERE {where}',params)
            total = cur.fetchone()['total']
        page = min(page, max(1, math.ceil(total/page_size)))
        cur.execute(f"""WITH selected AS MATERIALIZED (
            SELECT draft_id,draft_type,status,confidence,created_at,metadata,source_message_id,title,payload
            FROM drafts WHERE {where} ORDER BY created_at DESC,draft_id DESC LIMIT %s OFFSET %s
        ) SELECT draft_id,draft_type,status,confidence,created_at,source_message_id,
            ({TITLE}) AS display_title,
            jsonb_build_object('sender',jsonb_build_object('email',metadata->'sender'->>'email'),
                'original_sender_candidate',jsonb_build_object('email',metadata->'original_sender_candidate'->>'email')) AS metadata,
            COALESCE(metadata->>'exact_content_duplicate_of','')<>'' AS is_duplicate
            FROM selected ORDER BY created_at DESC,draft_id DESC""", [*params,page_size,(page-1)*page_size])
        items = cur.fetchall()
    for item in items:
        item['draft_id'] = str(item['draft_id'])
        item['created_at'] = item['created_at'].isoformat() if item['created_at'] else None
    return {'items':items,'page':page,'page_size':page_size,'total_count':total,
            'counts':{'total':counts['total'],'needsReview':counts['review'],'spam':counts['spam']}}
