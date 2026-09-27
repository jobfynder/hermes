"""Deterministic-first category selection for reviewed skill candidates."""

from __future__ import annotations

import json
import re

from app.prompt_runtime.extraction_fallback import run_llm_fallback


_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("AI", (" ai ", "llm", "language model", "machine learning", "mlops", "agentic", "embedding", "vector model", "neural")),
    ("Cloud", ("cloud", "aws", "azure", "gcp", "serverless", "lambda")),
    ("Security", ("security", "identity", "oauth", "saml", "iam", "siem", "firewall", "zero trust")),
    ("Database", ("database", " db ", "sql", "nosql", "postgres", "mongo", "redis", "warehouse")),
    ("Data Engineering", ("etl", "data pipeline", "data lake", "spark", "hadoop", "stream processing")),
    ("DevOps", ("devops", "ci/cd", " cicd ", "container", "kubernetes", "terraform", "observability")),
    ("Testing", ("test", "qa ", "quality assurance", "selenium", "cypress")),
    ("Frontend", ("frontend", "front end", " ui ", "css", "web component")),
    ("Backend", ("backend", "back end", "server framework", "web framework")),
    ("Mobile", ("mobile", "android", "ios", "flutter")),
    ("API", (" api ", "graphql", "grpc", "restful")),
    ("Integration", ("integration", "middleware", "ipaas", "connector")),
    ("Messaging", ("message queue", "messaging", "event streaming", "pub/sub")),
    ("ERP", (" erp ", "sap", "oracle fusion", "peoplesoft")),
    ("CRM", (" crm ", "salesforce", "dynamics 365")),
    ("HCM", (" hcm ", "hris", "workday", "payroll")),
    ("ITSM", ("itsm", "service desk", "incident management")),
    ("Networking", ("network", "dns", "tcp/ip", "load balancer")),
    ("BI", ("business intelligence", "dashboard", "visualization", "reporting")),
    ("Search", ("search engine", "full text search")),
    ("Methodology", ("methodology", "agile", "scrum", "kanban")),
]


def classify_skill_category_deterministically(term: str) -> str | None:
    normalized = f" {re.sub(r'[^a-z0-9+#/.]+', ' ', term.lower()).strip()} "
    for category, signals in _CATEGORY_RULES:
        if any(signal in normalized for signal in signals):
            return category
    return None


def classify_skill_category(term: str, known_categories: list[str]) -> tuple[str, str]:
    deterministic = classify_skill_category_deterministically(term)
    if deterministic and deterministic in known_categories:
        return deterministic, "deterministic"

    outcome = run_llm_fallback(
        prompt_id="jf.taxonomy.skill-candidate.classify",
        variables={
            "candidate_term": term,
            "known_categories_json": json.dumps(sorted(set(known_categories))),
        },
        source="taxonomy_candidate_review",
        cache_ttl_seconds=86_400,
    )
    extracted = outcome.get("extracted") if outcome.get("used") else None
    proposed = str((extracted or {}).get("category") or "").strip()
    by_key = {category.casefold(): category for category in known_categories}
    resolved = by_key.get(proposed.casefold())
    return (resolved, "llm") if resolved else ("Tool/Technology", "fallback")
