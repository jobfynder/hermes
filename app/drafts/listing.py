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


def list_draft_page(page=1, page_size=50, status=None, draft_type=None, search='', include_duplicates=False,
                    review_warning=None, date_window=None, channel=None, sender_domain='',
                    confidence_min=None, confidence_max=None, sort='recent'):
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
    if review_warning:
        conditions.append("EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(payload->'structured_data'->'email_parsing'->'records','[]'::jsonb)) r WHERE COALESCE(r->'warnings','[]'::jsonb) ? %s)")
        params.append(review_warning)
    if date_window == 'today':
        conditions.append("created_at >= date_trunc('day', now())")
    elif date_window in ('7d', '30d'):
        conditions.append("created_at >= now() - (%s * interval '1 day')")
        params.append(int(date_window[:-1]))
    elif date_window == 'older30':
        conditions.append("created_at < now() - interval '30 days'")
    if channel:
        conditions.append('channel=%s')
        params.append(channel)
    sender_domain = sender_domain.strip().lower()
    if sender_domain:
        conditions.append("lower(split_part(metadata->'sender'->>'email','@',2))=%s")
        params.append(sender_domain)
    if confidence_min is not None:
        conditions.append('confidence >= %s')
        params.append(confidence_min)
    if confidence_max is not None:
        conditions.append('confidence <= %s')
        params.append(confidence_max)
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
        order = {
            'recent':'created_at DESC,draft_id DESC', 'oldest':'created_at ASC,draft_id ASC',
            'confidence_low':'confidence ASC,created_at DESC', 'confidence_high':'confidence DESC,created_at DESC',
        }.get(sort, 'created_at DESC,draft_id DESC')
        cur.execute(f"""WITH selected AS MATERIALIZED (
            SELECT draft_id,draft_type,status,confidence,created_at,metadata,source_message_id,title,payload,channel
            FROM drafts WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s
        ) SELECT draft_id,draft_type,status,confidence,created_at,source_message_id,
            channel,
            ({TITLE}) AS display_title,
            jsonb_build_object('sender',jsonb_build_object('email',metadata->'sender'->>'email'),
                'original_sender_candidate',jsonb_build_object('email',metadata->'original_sender_candidate'->>'email')) AS metadata,
            COALESCE(metadata->>'exact_content_duplicate_of','')<>'' AS is_duplicate
            FROM selected ORDER BY {order}""", [*params,page_size,(page-1)*page_size])
        items = cur.fetchall()
    for item in items:
        item['draft_id'] = str(item['draft_id'])
        item['created_at'] = item['created_at'].isoformat() if item['created_at'] else None
    return {'items':items,'page':page,'page_size':page_size,'total_count':total,
            'counts':{'total':counts['total'],'needsReview':counts['review'],'spam':counts['spam']}}
