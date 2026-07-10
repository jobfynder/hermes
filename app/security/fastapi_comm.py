from fastapi import HTTPException, Request

from app.security.comm_signature import verify_comm_signature


async def require_comm_signature(request: Request) -> bytes:
    body = await request.body()

    valid, reason = verify_comm_signature(
        timestamp=request.headers.get("X-Jobfynder-Timestamp"),
        signature=request.headers.get("X-Jobfynder-Signature"),
        body=body,
    )

    if not valid:
        raise HTTPException(
            status_code=403,
            detail=reason or "comm_signature_rejected",
        )

    return body
