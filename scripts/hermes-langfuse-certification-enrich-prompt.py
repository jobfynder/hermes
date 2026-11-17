"""Publish the Langfuse prompt `jf.resume.certification.enrich` (certification catalogue enrichment).

Prompt ownership lives here, in Hermes. The Nest API (Core) only calls the prompt through /prompts/run and degrades
cleanly when it is missing: badges stay generated and nothing is enriched.

Run it inside the Hermes API container, which already holds the Langfuse keys. Dry run first (prints, writes nothing):

    docker exec -i hermes-api python - --dry-run < scripts/hermes-langfuse-certification-enrich-prompt.py
    docker exec -i hermes-api python - < scripts/hermes-langfuse-certification-enrich-prompt.py

Each run adds a new prompt version, so run it once per intentional change. Hermes caches prompt versions for a few
minutes before the new one is served.

Config notes:
  * metadata.owner must be "certifications". Hermes derives the safety domain from the owner, and an owner of
    "resume" makes it demand resume source text (`resume_source_text_required`).
  * The config is explicit on purpose; it is not copied from another prompt.
"""
from __future__ import annotations

import json
import sys
import urllib.request

from app.prompt_runtime.langfuse_prompts import _auth_header, _base_url

NAME = "jf.resume.certification.enrich"
MODEL_ALIAS = "generate-small"
LABELS = ["production", "hermes-llm", "latest"]
COMMIT_MESSAGE = "Certification catalogue enrichment (canonical name, issuer, abbreviation, badge colour)"

SYSTEM = (
    "ROLE: Professional certification librarian.\n"
    "TASK: Identify the professional certification the user typed and return its canonical facts.\n"
    "RULES: Only describe real, publicly offered professional certifications. If you do not recognise it with "
    "confidence, set recognised to false and leave every other field null. Never invent an issuer, an abbreviation or "
    "an exam code. badge_text is the short mark people use for it (at most 5 letters or digits, for example AWS, PMP, "
    "CKA). badge_tone must be exactly one of the palette keys given. aliases are common ways people write it (at most "
    "6). Do not include logos, URLs or marketing text.\n"
    "OUTPUT: Valid JSON only, with exactly these keys: "
    '{"recognised":true,"canonical_name":"string","issuer":"string","abbreviation":"string or null",'
    '"category":"string or null","badge_text":"string","badge_tone":"palette key","aliases":["string"]}'
)
USER = "certification={{certification_name}}\nissuer_hint={{issuer_hint}}\npalette={{badge_tones}}"

CONFIG = {
    "model": MODEL_ALIAS,
    "temperature": 0.1,
    "max_tokens": 400,
    "response_format": {"type": "json_object"},
    "litellm": {"router_alias": MODEL_ALIAS},
    "metadata": {
        "variables": ["certification_name", "issuer_hint", "badge_tones"],
        "source_prompt_id": NAME,
        "domain": "Certification Catalog",
        "owner": "certifications",
        "risk": "low",
    },
}


def build_body() -> dict:
    return {
        "type": "chat",
        "name": NAME,
        "prompt": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}],
        "config": CONFIG,
        "labels": LABELS,
        "tags": [],
        "commitMessage": COMMIT_MESSAGE,
    }


def main(argv: list[str]) -> int:
    body = build_body()
    if "--dry-run" in argv:
        print(json.dumps(body, indent=2))
        return 0
    req = urllib.request.Request(
        _base_url() + "/api/public/v2/prompts",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": _auth_header(),
            "Content-Type": "application/json",
            "User-Agent": "Hermes-PromptRuntime/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        out = json.loads(resp.read().decode())
    print("created", NAME, "v%s" % out.get("version"), out.get("labels"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
