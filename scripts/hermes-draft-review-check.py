from pathlib import Path


root = Path(__file__).resolve().parents[1]
html = (root / "app" / "static" / "draft-review.html").read_text(encoding="utf-8")
router = (root / "app" / "routers" / "draft_review.py").read_text(encoding="utf-8")
main = (root / "app" / "main.py").read_text(encoding="utf-8")

assert "Hermes Draft Review" in html
assert "sessionStorage" in html
assert "localStorage" not in html
assert 'type="password"' in html
assert "Authorization:`Bearer ${token}`" in html
assert "@router.get(\"/review\"" in router
assert "include_in_schema=False" in router
assert "app.include_router(draft_review_router)" in main

print("PASS: draft review page is served and keeps credentials session-scoped")
