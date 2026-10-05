from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field
from app.companies.imports import import_companies
from fastapi import APIRouter, Depends, HTTPException, Query
from app.security.rbac import require_permission
from app.companies.service import delete_companies, get_company, list_companies, update_company
from app.email_parsing.blocklist import add_block

router=APIRouter(prefix='/companies',tags=['Companies'])

@router.get('')
def companies(q: str=Query('',max_length=120),page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),
              verification:Literal['all','unverified','verified']='all',origin:Literal['all','email','import']='all',
              activity:Literal['all','active','inactive','none']='all',location:str=Query('',max_length=120),
              source:str=Query('',max_length=100),sort:Literal['recent','name','contacts','sources']='recent',
              _user:dict=Depends(require_permission('drafts:read'))):
    return list_companies(q,page,page_size,verification,origin,activity,location,source,sort)

class CompanyImportRequest(BaseModel):
    csv_text:str=Field(min_length=1,max_length=500000)
    dry_run:bool=True

@router.post('/import')
def import_directory(request:CompanyImportRequest,_user:dict=Depends(require_permission('drafts:publish'))):
    try: return import_companies(request.csv_text,request.dry_run,_user.get('id'))
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc

class CompanyUpdateRequest(BaseModel):
    canonical_name: str | None = Field(default=None,max_length=100)
    identity_domain: str | None = Field(default=None,max_length=253)
    verification_status: Literal['unverified','verified'] | None = None
    claim_status: Literal['unclaimed','claimed'] | None = None

class CompanyBulkDeleteRequest(BaseModel):
    company_ids: list[UUID] = Field(min_length=1,max_length=100)
    block_domains: bool = True

@router.post('/bulk-delete')
def bulk_delete_companies(request:CompanyBulkDeleteRequest,user:dict=Depends(require_permission('drafts:publish'))):
    rows=delete_companies(request.company_ids)
    if request.block_domains:
        for row in rows:
            add_block('domain',row['identity_domain'],f"Company removed as spam by {user.get('id') or 'reviewer'}")
    return {'deleted_count':len(rows),'deleted_company_ids':[str(row['company_id']) for row in rows],
            'blocked_domains':[row['identity_domain'] for row in rows] if request.block_domains else []}

@router.patch('/{company_id}')
def edit_company(company_id:UUID,request:CompanyUpdateRequest,_user:dict=Depends(require_permission('drafts:publish'))):
    try:
        row=update_company(company_id,**request.model_dump())
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    if row is None:
        raise HTTPException(404,'Company not found')
    return row

@router.delete('/{company_id}')
def remove_company(company_id:UUID,block_domain:bool=True,user:dict=Depends(require_permission('drafts:publish'))):
    rows=delete_companies([company_id])
    if not rows:
        raise HTTPException(404,'Company not found')
    if block_domain:
        add_block('domain',rows[0]['identity_domain'],f"Company removed as spam by {user.get('id') or 'reviewer'}")
    return {'deleted':True,'blocked_domain':rows[0]['identity_domain'] if block_domain else None}

@router.get('/{company_id}')
def company(company_id:UUID,_user:dict=Depends(require_permission('drafts:read'))):
    result=get_company(company_id)
    if result is None:
        raise HTTPException(404,'Company not found')
    return result
