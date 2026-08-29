from pathlib import Path

from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope

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


class _ReviewStaticFiles(StaticFiles):
    """Vite fingerprints every file under assets/ with a content hash, so
    those are safe to cache forever -- but index.html itself keeps a
    stable name across deploys and references that day's hashed
    filenames. Left to the default caching, browsers hold onto a stale
    index.html and keep loading an old JS bundle after a deploy with no
    visible sign anything is wrong (this bit us verifying the CTA/filter
    fixes: the server was serving the new build correctly the whole
    time). Force index.html to revalidate on every load; the fingerprinted
    assets underneath keep their normal long-lived caching.

    Matched by content-type rather than the requested path: with
    html=True, StaticFiles serves index.html both for the exact root and
    for any unmatched SPA route (client-side routing fallback), and
    text/html is the only content-type this directory ever returns for
    index.html either way.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


router = APIRouter(tags=["Draft Review"])
router.mount("/review", _ReviewStaticFiles(directory=_REVIEW_DIST, html=True), name="review")
