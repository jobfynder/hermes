from pathlib import Path

from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles

# Built by the frontend-build Docker stage (see Dockerfile) from frontend/
# -- a real React app, not a hand-authored static page. This directory
# only exists inside the built image; created empty here so importing
# this module never crashes app startup in a context that hasn't run
# that build stage (e.g. the regression test containers, which mount the
# raw source tree directly and never build the frontend -- they have no
# reason to exercise this router's static assets, only the /drafts and
# /claim APIs it's a client of).
_REVIEW_DIST = Path(__file__).resolve().parent.parent / "static" / "review"
_REVIEW_DIST.mkdir(parents=True, exist_ok=True)

router = APIRouter(tags=["Draft Review"])
router.mount("/review", StaticFiles(directory=_REVIEW_DIST, html=True), name="review")
