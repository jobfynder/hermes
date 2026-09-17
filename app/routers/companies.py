from uuid import UUID
from typing import Literal
from pydantic import BaseModel, Field
from app.companies.imports import import_companies
from fastapi import APIRouter, Depends, HTTPException, Query
from app.security.rbac import require_permission
from app.companies.service import list_companies, get_company

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

@router.get('/{company_id}')
def company(company_id:UUID,_user:dict=Depends(require_permission('drafts:read'))):
    result=get_company(company_id)
    if result is None:
        raise HTTPException(404,'Company not found')
    return result
