"""Bounded CSV imports. Imports establish provenance, never activity or verification."""
import csv
import io
from urllib.parse import urlsplit
from uuid import uuid4
from app.runtime.db import cursor
from app.companies.service import corporate_domain, normalize_company_name

def safe_url(value):
    value=(value or '').strip()
    if not value: return ''
    try:
        parsed=urlsplit(value)
        if parsed.scheme in ('http','https') and parsed.hostname and not parsed.username and not parsed.password:
            return value[:1000]
    except ValueError: pass
    raise ValueError('URL must be an http(s) URL without credentials')

def import_companies(csv_text,dry_run=True,actor=None):
    if len(csv_text)>500000: raise ValueError('CSV limit is 500 KB')
    reader=csv.DictReader(io.StringIO(csv_text.lstrip('\ufeff')))
    if not {'company_name','domain'}.issubset(reader.fieldnames or []):
        raise ValueError('Required CSV headers: company_name,domain')
    rows=list(reader)
    if not rows or len(rows)>1000: raise ValueError('Provide 1 to 1000 rows per import')
    valid=[];errors=[];seen=set()
    for number,row in enumerate(rows,2):
        try:
            name=normalize_company_name(row.get('company_name'))
            raw=(row.get('domain') or '').strip()
            domain=corporate_domain(urlsplit(raw).hostname if '://' in raw else raw.strip('/'))
            if not name or not domain: raise ValueError('Usable company name and corporate domain required; portal domains cannot identify a company')
            source=(row.get('source') or 'manual').strip().lower()[:100]
            source_url=safe_url(row.get('source_url'));careers_url=safe_url(row.get('careers_url'))
            key=(domain,source,source_url)
            if key in seen: continue
            seen.add(key)
            valid.append((name,domain,source,source_url,(row.get('location') or '').strip()[:200],careers_url))
        except (ValueError,AttributeError) as exc: errors.append({'row':number,'error':str(exc)})
    created=0;linked=0
    with cursor() as cur:
        if not dry_run: cur.execute('SELECT pg_advisory_xact_lock(892310492)')
        for name,domain,source,url,location,careers in valid:
            cur.execute('SELECT company_id FROM hermes_companies WHERE identity_domain=%s',(domain,));found=cur.fetchone()
            if found: company_id=found['company_id'];linked+=1
            else: company_id=uuid4();created+=1
            if dry_run: continue
            cur.execute("""INSERT INTO hermes_companies(company_id,identity_domain,canonical_name) VALUES(%s,%s,%s)
                ON CONFLICT(identity_domain) DO UPDATE SET identity_domain=EXCLUDED.identity_domain RETURNING company_id""",(company_id,domain,name))
            company_id=cur.fetchone()['company_id']
            cur.execute("""INSERT INTO company_import_sources(company_id,source,source_url,imported_name,location,careers_url,imported_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(company_id,source,source_url) DO UPDATE SET
                imported_name=EXCLUDED.imported_name,location=EXCLUDED.location,careers_url=EXCLUDED.careers_url,imported_by=EXCLUDED.imported_by""",
                (company_id,source,url,name,location,careers,actor))
    return {'dry_run':dry_run,'valid_rows':len(valid),'new_companies':created,'existing_companies':linked,'errors':errors,'duplicate_rows':len(rows)-len(valid)-len(errors)}
