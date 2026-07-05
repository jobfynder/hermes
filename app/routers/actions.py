from fastapi import APIRouter, Depends, HTTPException

from app.action_engine.models import ActionItem
from app.security.rbac import require_permission

from app.action_engine.service import (
    create_action,
    delete_action,
    get_action,
    list_actions,
    update_action,
)

router = APIRouter(
    prefix="/actions",
    tags=["Actions"],
)


@router.get("")
def actions(user: dict = Depends(require_permission("actions:read"))):
    return list_actions()


@router.get("/{action_id}")
def action(action_id: str, user: dict = Depends(require_permission("actions:read"))):
    item = get_action(action_id)

    if not item:
        raise HTTPException(status_code=404, detail="Action not found")

    return item


@router.post("")
def add_action(action_item: ActionItem, user: dict = Depends(require_permission("actions:write"))):
    try:
        return create_action(action_item)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))


@router.put("/{action_id}")
def edit_action(action_id: str, action_item: ActionItem, user: dict = Depends(require_permission("actions:write"))):
    try:
        return update_action(action_id, action_item)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.delete("/{action_id}")
def remove_action(action_id: str, user: dict = Depends(require_permission("actions:write"))):
    deleted = delete_action(action_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Action not found")

    return {"deleted": True, "id": action_id}
