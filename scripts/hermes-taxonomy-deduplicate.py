"""Consolidate deterministic spelling duplicates; dry-run unless --apply."""
import argparse
import collections
import json
from datetime import datetime, timezone
from pathlib import Path
from app.runtime.db import cursor
from app.understanding.taxonomy.candidates import candidate_identity, _lock_candidate_identity
from app.understanding.taxonomy.loader import (
    _writable_taxonomy_path, _write_json_atomic, clear_taxonomy_cache,
    _SKILLS_WRITE_LOCK_KEY, _TITLES_WRITE_LOCK_KEY,
)

def run(apply=False):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    audit_dir = _writable_taxonomy_path('canonical_skills.json').parent / ('dedup-backup-' + stamp)
    counts = {'canonical_entries_merged': 0, 'pending_rows_merged': 0}
    if apply:
        audit_dir.mkdir()
    for filename, field, collection, lock in (
        ('canonical_skills.json', 'name', 'skills', _SKILLS_WRITE_LOCK_KEY),
        ('job_titles.json', 'title', 'titles', _TITLES_WRITE_LOCK_KEY),
    ):
        with cursor() as cur:
            cur.execute('SELECT pg_advisory_xact_lock(%s)', (lock,))
            path = _writable_taxonomy_path(filename)
            original = path.read_text()
            data = json.loads(original)
            keep = []
            seen = {}
            for entry in data[collection]:
                key = candidate_identity(entry.get(field, ''))
                if not key or key not in seen:
                    keep.append(entry)
                    if key:
                        seen[key] = entry
                    continue
                winner = seen[key]
                aliases = set(winner.get('aliases') or []) | set(entry.get('aliases') or []) | {entry[field]}
                aliases.discard(winner[field])
                winner['aliases'] = sorted(aliases)
                for name, value in entry.items():
                    if name not in (field, 'aliases') and not winner.get(name):
                        winner[name] = value
                counts['canonical_entries_merged'] += 1
            if apply and len(keep) != len(data[collection]):
                (audit_dir / filename).write_text(original)
                data[collection] = keep
                _write_json_atomic(path, data)
                clear_taxonomy_cache()

    with cursor() as cur:
        cur.execute("""SELECT signal_type, regexp_replace(normalized_term,'[^a-z0-9+#]','','g') AS identity
            FROM taxonomy_candidates
            WHERE coalesce(reviewed_by,'') NOT LIKE 'hermes-dedup:%%'
            GROUP BY 1,2 HAVING count(*)>1 AND bool_or(status='pending')""")
        groups = cur.fetchall()
    for group in groups:
        with cursor() as cur:
            _lock_candidate_identity(cur, group['signal_type'], group['identity'])
            cur.execute("""SELECT * FROM taxonomy_candidates WHERE signal_type=%s
                AND regexp_replace(normalized_term,'[^a-z0-9+#]','','g')=%s
                AND coalesce(reviewed_by,'') NOT LIKE 'hermes-dedup:%%'
                ORDER BY CASE status WHEN 'approved' THEN 0 WHEN 'rejected' THEN 1 ELSE 2 END,id FOR UPDATE""",
                (group['signal_type'],group['identity']))
            rows = cur.fetchall()
            if len(rows)<2:
                continue
            winner = rows[0]
            losers = [row for row in rows[1:] if row['status']=='pending']
            counts['pending_rows_merged'] += len(losers)
            if not apply or not losers:
                continue
            # Preserve full original rows on the server before mutation.
            with (audit_dir / 'candidate-merges.jsonl').open('a') as audit:
                audit.write(json.dumps({'winner':winner,'merged':losers}, default=str)+'\n')
                audit.flush()
            senders = set(winner['distinct_senders'] or [])
            samples = list(winner['sample_draft_ids'] or [])
            occurrences = winner['occurrence_count']
            for row in losers:
                senders.update(row['distinct_senders'] or [])
                samples.extend(x for x in row['sample_draft_ids'] or [] if x not in samples)
                occurrences += row['occurrence_count']
                cur.execute("UPDATE taxonomy_candidates SET status='rejected',reviewed_at=now(),reviewed_by=%s WHERE id=%s",
                            ('hermes-dedup:'+str(winner['id']),row['id']))
            cur.execute('''UPDATE taxonomy_candidates SET occurrence_count=%s,distinct_senders=%s,sample_draft_ids=%s,
                first_seen_at=%s,last_seen_at=%s WHERE id=%s''',
                (occurrences,json.dumps(sorted(senders)),json.dumps(samples[:10]),
                 min(row['first_seen_at'] for row in [winner]+losers),max(row['last_seen_at'] for row in [winner]+losers),winner['id']))
    print(json.dumps({'applied':apply,**counts,'backup':str(audit_dir) if apply else None}))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    run(parser.parse_args().apply)
