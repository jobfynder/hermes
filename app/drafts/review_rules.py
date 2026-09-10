"""Conservative repair of review flags that contradict validated parser output."""
import json
from datetime import datetime,timezone
from app.runtime.db import cursor


def parser_is_ready(row):
    parsing=row.get('parsing') or {}
    records=parsing.get('records') or []
    expected={'draft_job_requirement':'job_description','draft_hotlist':'hotlist'}.get(row['draft_type'])
    return bool(expected and parsing.get('document_kind')==expected and records
        and row['confidence']>=0.7 and not row.get('errors')
        and parsing.get('requires_review') is False and not parsing.get('warnings')
        and float(parsing.get('confidence',0))>=0.7
        and all(record.get('requires_review') is False and not record.get('warnings')
            and float(record.get('parse_confidence',0))>=0.7 for record in records))


def reconcile_review_status(*,dry_run=True,limit=100):
    if not 1<=limit<=200:
        raise ValueError('limit must be between 1 and 200')
    resolved=[]
    with cursor() as cur:
        cur.execute("""SELECT d.draft_id,d.draft_type,d.confidence,d.errors,
            d.payload->'structured_data'->'email_parsing' AS parsing
            FROM drafts d WHERE d.status='needs_review' AND d.confidence>=0.7
            AND d.draft_type IN ('draft_job_requirement','draft_hotlist')
            AND NOT EXISTS(SELECT 1 FROM field_provenance f WHERE f.parse_run_id=d.draft_id::text
                AND f.extractor IN ('reviewer_correction','recruiter_correction'))
            ORDER BY d.created_at,d.draft_id LIMIT %s FOR UPDATE OF d""",(limit,))
        rows=cur.fetchall()
        for row in rows:
            if not parser_is_ready(row): continue
            resolved.append(str(row['draft_id']))
            if dry_run: continue
            audit={'review_resolution':{'rule':'parser_ready_status_reconciliation_v1',
                'previous_status':'needs_review','resolved_at':datetime.now(timezone.utc).isoformat()}}
            cur.execute("""UPDATE drafts SET status='draft',requires_review=false,updated_at=now(),
                metadata=metadata || %s::jsonb WHERE draft_id=%s""",(json.dumps(audit),row['draft_id']))
    return {'dry_run':dry_run,'checked_count':len(rows),'resolved_count':len(resolved),'draft_ids':resolved}
