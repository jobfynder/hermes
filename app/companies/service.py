"""Deterministic, source-backed company discovery. Never publishes to CORE."""
import hashlib
import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from app.runtime.db import cursor
from app.email_parsing.signature_learning import FREEMAIL_DOMAINS
from app.email_parsing.signature import JOB_BOARD_RELAY_URL_RE

SHARED_DOMAINS = set(FREEMAIL_DOMAINS) | {
    'jobfynder.com', 'groups.google.com', 'googlegroups.com', 'google.com',
    'nvoids.com', 'jobs.nvoids.com', 'prohirespowerhouse.com', 'techmail001.email',
    'linkedin.com', 'indeed.com', 'dice.com', 'yahoogroups.com',
}

def corporate_domain(value):
    value = (value or '').strip().lower().rstrip('.')
    if value.startswith('www.'):
        value = value[4:]
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}',value):
        return None
    if any(value == domain or value.endswith('.'+domain) for domain in SHARED_DOMAINS):
        return None
    if JOB_BOARD_RELAY_URL_RE.search('https://'+value):
        return None
    return value

def _text(value):
    return re.sub(r'\s+',' ',str(value or '')).strip()

PROJECTION_VERSION = 'company_directory_v3'

def normalize_company_name(value):
    name = _text(value)
    if re.search(r"(?i)^(?:keywords?|subject|from|to|location|job title|required skills|disclaimer|confidentiality|please|dear|hello|regards|thanks)\b", name):
        return None
    if re.search(r"(?i)unsubscribe|years of experience|we are looking|click here|all rights reserved", name):
        return None
    name = name.split('|', 1)[0].strip(' ,;:-')
    name = re.split(r",\s*\d{1,6}\s", name, maxsplit=1)[0].strip()
    if not 2 <= len(name) <= 100 or len(name.split()) > 12 or '@' in name or 'http' in name.lower():
        return None
    if name.lower() in {'unknown','confidential','client','company','n/a','na'}:
        return None
    return name

def extract_company(row):
    if row.get('status') in ('spam','rejected'):
        return None, 'excluded_status'
    metadata = row.get('metadata') or {}
    if metadata.get('exact_content_duplicate_of'):
        return None, 'duplicate_source'
    structured = (row.get('payload') or {}).get('structured_data') or {}
    signature = structured.get('signature') or {}
    contact = signature.get('contact') or {}
    def field(name):
        item=contact.get(name)
        return _text(item.get('value')) if isinstance(item,dict) else ''
    name = normalize_company_name(field('company_name'))
    if not name or not field('email'):
        # Recheck historical stored text with the current deterministic signature parser.
        # Never substitute the relay/transport sender for a signature contact.
        from app.email_parsing.signature import parse_email_signature
        recovered = parse_email_signature(text=(row.get('payload') or {}).get('text') or '', sender_email=None)
        recovered_contact = recovered.get('contact') or {}
        recovered_name = normalize_company_name((recovered_contact.get('company_name') or {}).get('value'))
        if recovered_name:
            contact = recovered_contact
            name = recovered_name
    if not name:
        return None, 'company_name_missing_or_ambiguous'
    # Only a signature contact is company evidence; relay transport senders
    # and job-record company fields can identify a different end client.
    email=field('email').lower()
    domain=corporate_domain(email.rsplit('@',1)[-1]) if re.fullmatch(r'[^\s@]+@[^\s@]+',email) else None
    website=field('website')
    try:
        parsed=urlsplit(website)
        website_domain=corporate_domain(parsed.hostname) if parsed.scheme in ('http','https') else None
    except ValueError:
        website_domain=None
    if not domain:
        if website_domain:
            domain = website_domain
            email = None  # A website does not establish a freemail contact's affiliation.
        else:
            return None, 'corporate_signature_email_missing'
    if website_domain and website_domain != domain:
        website=None
    elif not website_domain:
        website=None
    jobs=[]
    for record in (structured.get('email_parsing') or {}).get('records') or []:
        if record.get('record_type') != 'job_requirement' or not record.get('job_title'):
            continue
        title=_text(record.get('job_title'))
        description=_text(record.get('job_description'))
        identity=[domain,title.lower(),_text(record.get('company')).lower(),_text(record.get('location')).lower(),_text(record.get('employment_type')).lower(),description.lower()]
        # Insufficient text must not collapse unrelated same-title jobs.
        if len(description)<40:
            identity.extend([str(row['draft_id']),str(record.get('source_section',len(jobs)))])
        jobs.append({'key':hashlib.sha256(json.dumps(identity).encode()).hexdigest(),
                     'title':title,'location':_text(record.get('location')),
                     'named_client':_text(record.get('company')),
                     'requires_review':bool(record.get('requires_review'))})
    company_field=contact.get('company_name') or {}
    return {'domain':domain,'name':name,'contact_email':email,'contact_name':field('full_name') or None,
            'website':website,'phone':field('phone') or field('mobile') or None,
            'location':', '.join(filter(None,[field('city'),field('state')])) or None,
            'confidence':float(company_field.get('confidence') or 0),
            'method':str(company_field.get('method') or 'signature_observation'),'jobs':jobs}, 'linked'

def sync_company_batch(limit=100):
    """Resumable projection; one bounded transaction, no network or LLM.

    Source-version comparison also picks up human corrections. Row locks
    protect against a concurrent source edit while projecting this batch.
    """
    with cursor() as cur:
        cur.execute('SELECT pg_try_advisory_xact_lock(892310490) AS acquired')
        if not cur.fetchone()['acquired']:
            return 0
        cur.execute('''SELECT d.* FROM drafts d LEFT JOIN company_projection_state p USING(draft_id)
            WHERE p.source_updated_at IS DISTINCT FROM d.updated_at OR p.projection_version IS DISTINCT FROM %s
            ORDER BY d.created_at,d.draft_id LIMIT %s FOR UPDATE OF d SKIP LOCKED''',(PROJECTION_VERSION,min(max(limit,1),200)))
        rows=cur.fetchall()
        affected = set()
        for row in rows:
            cur.execute('SELECT company_id FROM company_observations WHERE draft_id=%s',(row['draft_id'],))
            previous=cur.fetchone()
            if previous:
                affected.add(previous['company_id'])
            try:
                observation,reason=extract_company(row)
            except (TypeError,ValueError,AttributeError):
                observation,reason=None,'invalid_source_structure'
            if observation:
                cur.execute('''INSERT INTO hermes_companies(company_id,identity_domain,canonical_name)
                    VALUES (%s,%s,%s) ON CONFLICT(identity_domain) DO UPDATE
                    SET identity_domain=EXCLUDED.identity_domain RETURNING company_id''',
                    (uuid4(),observation['domain'],observation['name']))
                company_id=cur.fetchone()['company_id']
                affected.add(company_id)
                cur.execute('''INSERT INTO company_observations(draft_id,company_id,company_label,contact_email,
                    contact_name,website,phone,location,confidence,method,channel,observed_at,jobs)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(draft_id) DO UPDATE SET company_id=EXCLUDED.company_id,
                    company_label=EXCLUDED.company_label,contact_email=EXCLUDED.contact_email,
                    contact_name=EXCLUDED.contact_name,website=EXCLUDED.website,phone=EXCLUDED.phone,
                    location=EXCLUDED.location,confidence=EXCLUDED.confidence,method=EXCLUDED.method,
                    channel=EXCLUDED.channel,observed_at=EXCLUDED.observed_at,jobs=EXCLUDED.jobs''',
                    (row['draft_id'],company_id,observation['name'],observation['contact_email'],
                     observation['contact_name'],observation['website'],observation['phone'],observation['location'],
                     observation['confidence'],observation['method'],row['channel'] or 'unknown',row['created_at'],json.dumps(observation['jobs'])))
            else:
                cur.execute('DELETE FROM company_observations WHERE draft_id=%s',(row['draft_id'],))
            cur.execute('''INSERT INTO company_projection_state(draft_id,source_updated_at,reason,projection_version)
                VALUES (%s,%s,%s,%s) ON CONFLICT(draft_id) DO UPDATE SET
                source_updated_at=EXCLUDED.source_updated_at,reason=EXCLUDED.reason,projection_version=EXCLUDED.projection_version,processed_at=now()''',
                (row['draft_id'],row['updated_at'],reason,PROJECTION_VERSION))
        if affected:
            cur.execute("""UPDATE hermes_companies c SET canonical_name=(
                SELECT company_label FROM company_observations o WHERE o.company_id=c.company_id
                GROUP BY company_label
                ORDER BY bool_or(method IN ('human_edited','reviewer_correction','recruiter_correction')) DESC,
                    count(*) DESC,max(observed_at) DESC,company_label LIMIT 1)
                WHERE c.company_id=ANY(%s) AND c.verification_status='unverified'
                AND EXISTS(SELECT 1 FROM company_observations o WHERE o.company_id=c.company_id)""",(list(affected),))
        return len(rows)

def list_companies(query='',page=1,page_size=25,verification='all',origin='all',activity='all',location='',source='',sort='recent'):
    page=max(1,page);page_size=min(max(1,page_size),100)
    def like(value):
        return '%'+value.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
    conditions=["(c.canonical_name ILIKE %(q)s OR c.identity_domain ILIKE %(q)s OR EXISTS(SELECT 1 FROM company_observations o WHERE o.company_id=c.company_id AND o.company_label ILIKE %(q)s))",
                "(s.source_count>0 OR EXISTS(SELECT 1 FROM company_import_sources i WHERE i.company_id=c.company_id))"]
    args={'q':like(query),'location':like(location),'source':like(source),'verification':verification}
    if verification!='all': conditions.append('c.verification_status=%(verification)s')
    if origin=='email': conditions.append('s.source_count>0')
    if origin=='import': conditions.append('EXISTS(SELECT 1 FROM company_import_sources i WHERE i.company_id=c.company_id)')
    if activity=='active': conditions.append("s.last_seen>=now()-interval '30 days'")
    if activity=='inactive': conditions.append("s.last_seen<now()-interval '30 days'")
    if activity=='none': conditions.append('s.source_count=0')
    if location: conditions.append("(EXISTS(SELECT 1 FROM company_observations o WHERE o.company_id=c.company_id AND o.location ILIKE %(location)s) OR EXISTS(SELECT 1 FROM company_import_sources i WHERE i.company_id=c.company_id AND i.location ILIKE %(location)s))")
    if source: conditions.append("(EXISTS(SELECT 1 FROM company_observations o WHERE o.company_id=c.company_id AND o.channel ILIKE %(source)s) OR EXISTS(SELECT 1 FROM company_import_sources i WHERE i.company_id=c.company_id AND i.source ILIKE %(source)s))")
    order={'recent':'s.last_seen DESC NULLS LAST','name':'lower(c.canonical_name)','contacts':'s.contact_count DESC','sources':'s.source_count DESC'}.get(sort,'s.last_seen DESC NULLS LAST')
    base=""" FROM hermes_companies c JOIN LATERAL (
        SELECT count(*) AS source_count,count(DISTINCT contact_email) AS contact_count,
        max(observed_at) AS last_seen,avg(confidence) AS avg_confidence
        FROM company_observations WHERE company_id=c.company_id) s ON true WHERE """+' AND '.join(conditions)
    with cursor() as cur:
        cur.execute('SELECT count(*) AS total'+base,args);total=cur.fetchone()['total']
        page=min(page,max(1,(total+page_size-1)//page_size));args.update(limit=page_size,offset=(page-1)*page_size)
        cur.execute('SELECT c.*,s.*'+base+' ORDER BY '+order+',c.company_id LIMIT %(limit)s OFFSET %(offset)s',args)
        items=cur.fetchall()
        cur.execute("""SELECT count(*) FILTER(WHERE p.projection_version=%s AND p.source_updated_at=d.updated_at) AS processed,
            max(p.processed_at) AS last_synced,count(*) FILTER(WHERE p.reason='linked') AS linked,count(*) AS total
            FROM drafts d LEFT JOIN company_projection_state p USING(draft_id)""",(PROJECTION_VERSION,))
        sync=cur.fetchone()
        cur.execute('SELECT reason,count(*) AS count FROM company_projection_state GROUP BY reason ORDER BY count(*) DESC')
        sync['reasons']=cur.fetchall()
    return {'items':items,'total_count':total,'page':page,'page_size':page_size,'sync':sync}


def get_company(company_id):
    with cursor() as cur:
        cur.execute('SELECT * FROM hermes_companies WHERE company_id=%s',(company_id,))
        company=cur.fetchone()
        if not company:
            return None
        cur.execute('''SELECT company_label,count(*) AS sources FROM company_observations
            WHERE company_id=%s GROUP BY company_label ORDER BY sources DESC,company_label''',(company_id,))
        company['observed_names']=cur.fetchall()
        cur.execute('SELECT source,source_url,imported_name,location,careers_url,imported_at FROM company_import_sources WHERE company_id=%s ORDER BY imported_at DESC',(company_id,))
        company['imports']=cur.fetchall()
        cur.execute('''SELECT contact_email AS email,max(contact_name) AS name,count(*) AS source_count,
            max(observed_at) AS last_seen FROM company_observations WHERE company_id=%s
            GROUP BY contact_email ORDER BY last_seen DESC LIMIT 100''',(company_id,))
        company['contacts']=cur.fetchall()
        cur.execute('''SELECT draft_id,company_label,contact_email,website,phone,location,confidence,
            method,channel,observed_at,jobs FROM company_observations
            WHERE company_id=%s ORDER BY observed_at DESC,draft_id LIMIT 50''',(company_id,))
        company['sources']=cur.fetchall()
        cur.execute('''SELECT count(*) AS source_count,count(DISTINCT contact_email) AS contact_count,
            max(observed_at) AS last_seen FROM company_observations WHERE company_id=%s''',(company_id,))
        company.update(cur.fetchone())
        cur.execute('''SELECT count(DISTINCT job->>'key') AS job_requirements
            FROM company_observations o CROSS JOIN LATERAL jsonb_array_elements(o.jobs) job
            WHERE company_id=%s''',(company_id,))
        company.update(cur.fetchone())
        cur.execute('''SELECT count(*) AS n FROM (SELECT DISTINCT job->>'key' FROM company_observations o
            CROSS JOIN LATERAL jsonb_array_elements(o.jobs) job WHERE company_id=%s
            AND observed_at>=now()-interval '30 days') jobs''',(company_id,))
        recent_jobs=cur.fetchone()['n']
        cur.execute('''SELECT count(DISTINCT contact_email) AS n,count(*) AS sources FROM company_observations
            WHERE company_id=%s AND observed_at>=now()-interval '30 days' ''',(company_id,))
        recent=cur.fetchone()
        company['activity']={'score':min(60,recent_jobs*3)+min(25,recent['n']*5)+(15 if recent['sources'] else 0),
                             'recent_unique_requirements':recent_jobs,'recent_contacts':recent['n'],
                             'recent_sources':recent['sources'],'window_days':30,'version':'observed_activity_v1'}
    return company
