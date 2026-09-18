"""Materialize stable skill IDs and reviewed glossary enrichment.

Safe to run repeatedly. Existing IDs and human-authored enrichment always win.
The runtime taxonomy can be passed explicitly; the checked-in seed is the
default so new deployments begin with stable identities.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.understanding.taxonomy.identity import stable_skill_id


ENRICHMENT = {
    "Kubernetes": {
        "subcategory": "Container Orchestration",
        "short_definition": "Container orchestration platform for deploying, scaling, and operating containerized applications.",
        "recruiter_explanation": "Common in DevOps, SRE, cloud, and platform roles; often requested with Docker, Helm, Terraform, and a cloud provider.",
        "related_roles": ["DevOps Engineer", "Site Reliability Engineer", "Platform Engineer", "Cloud Engineer"],
        "relationships": [
            {"type": "commonly_used_with", "skill": "Docker"},
            {"type": "commonly_used_with", "skill": "Helm"},
            {"type": "commonly_used_with", "skill": "Terraform"},
        ],
    },
    "Spring Boot": {
        "subcategory": "Backend Framework",
        "short_definition": "Java framework for building production-ready web services and applications.",
        "recruiter_explanation": "A core backend skill for Java developers, commonly paired with microservices, REST APIs, SQL databases, and cloud platforms.",
        "related_roles": ["Java Developer", "Backend Engineer", "Software Engineer"],
        "relationships": [{"type": "framework_for", "skill": "Java"}],
    },
    "PostgreSQL": {
        "subcategory": "Relational Database",
        "short_definition": "Open-source relational database known for standards compliance and extensibility.",
        "recruiter_explanation": "Requested across backend, data, and platform roles where production SQL and relational data modeling matter.",
        "related_roles": ["Backend Engineer", "Data Engineer", "Database Administrator"],
    },
    "React": {
        "subcategory": "Web UI Library",
        "short_definition": "JavaScript library for building component-based user interfaces.",
        "recruiter_explanation": "A common frontend requirement, frequently paired with JavaScript or TypeScript, state management, and modern web tooling.",
        "related_roles": ["Frontend Developer", "Full Stack Developer", "UI Engineer"],
    },
    "Node.js": {
        "subcategory": "JavaScript Runtime",
        "short_definition": "Server-side JavaScript runtime built on the V8 engine.",
        "recruiter_explanation": "Common for backend and full-stack JavaScript roles, often paired with TypeScript, REST APIs, and cloud services.",
        "related_roles": ["Backend Engineer", "Full Stack Developer", "JavaScript Developer"],
    },
    "AWS": {
        "subcategory": "Cloud Platform",
        "short_definition": "Amazon Web Services cloud platform for compute, storage, networking, data, and managed services.",
        "recruiter_explanation": "Broad cloud experience signal; confirm which AWS services and whether the role expects architecture, development, operations, or security depth.",
        "related_roles": ["Cloud Engineer", "DevOps Engineer", "Solutions Architect"],
    },
    "Docker": {
        "subcategory": "Containers",
        "short_definition": "Platform and tooling for packaging and running applications in containers.",
        "recruiter_explanation": "Common across software, DevOps, and platform roles and frequently paired with Kubernetes and CI/CD.",
        "related_roles": ["DevOps Engineer", "Platform Engineer", "Software Engineer"],
    },
    "Kafka": {
        "subcategory": "Event Streaming",
        "short_definition": "Distributed event-streaming platform for high-throughput data pipelines and real-time applications.",
        "recruiter_explanation": "Often required in backend and data roles involving event-driven architecture, messaging, and streaming systems.",
        "related_roles": ["Backend Engineer", "Data Engineer", "Streaming Engineer"],
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app/understanding/taxonomy/canonical_skills.json",
    )
    args = parser.parse_args()
    raw = args.path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    data = json.loads(raw.decode("utf-8"))
    for skill in data.get("skills", []):
        skill.setdefault("skill_id", stable_skill_id(skill["name"]))
        for key, value in ENRICHMENT.get(skill["name"], {}).items():
            if not skill.get(key):
                skill[key] = value
        skill.setdefault("status", "active")
    payload = json.dumps(data, indent=2, ensure_ascii=False).replace("\n", newline) + newline
    args.path.write_bytes(payload.encode("utf-8"))


if __name__ == "__main__":
    main()
