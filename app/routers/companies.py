from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from app.security.rbac import require_permission
from app.companies.service import list_companies, get_company

router=APIRouter(prefix='/companies',tags=['Companies'])

@router.get('')
def companies(q: str=Query('',max_length=120),page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=100),
              _user:dict=Depends(require_permission('drafts:read'))):
    return list_companies(q,page,page_size)

@router.get('/{company_id}')
def company(company_id:UUID,_user:dict=Depends(require_permission('drafts:read'))):
    result=get_company(company_id)
    if result is None:
        raise HTTPException(404,'Company not found')
    return result
