"""Recruiter-facing skill definitions (HERMES-950), in the spirit of
GlossaryTech: one clear, jargon-free sentence per skill so a non-
technical recruiter reading "SAP BTP" or "TIBCO BusinessWorks" on a
resume understands what it is without leaving the page.

Descriptions are resolved deterministically first, against a small
curated glossary of the tech terms recruiters see constantly (AWS,
Docker, Salesforce, SAP, ...) -- instant, free, and consistent every
time the same term comes up. The LLM is only a fallback for terms the
glossary doesn't cover, so the API is only hit for the long tail.

Goes through the same LiteLLM gateway every other Hermes AI capability
uses (app/prompt_runtime/service.py) -- no direct provider calls. Not
routed through a registered Langfuse prompt, unlike the live parsing
pipeline's LLM fallback: this only ever runs from an admin action
(approving a taxonomy candidate, or the one-time backfill script), never
in the request path of a real email being parsed, so the tracing/cost-
attribution a registered prompt gives isn't needed the same way. Kept
strictly best-effort -- a description is a nice-to-have annotation, not
something any parsing decision depends on, so a failure here must never
break the caller.
"""

from __future__ import annotations

import os

from app.prompt_runtime.models import PromptRenderedMessage
from app.prompt_runtime.service import _call_litellm_with_model, litellm_configured
from app.understanding.taxonomy.loader import normalize_taxonomy_key

# Hand-written, reviewed once and reused forever -- the most common terms
# recruiters run into on tech resumes and job postings. Keyed by raw name;
# looked up via normalize_taxonomy_key so "AWS", "aws", "A.W.S" all hit the
# same entry. Extend this over time as recurring candidates show up in the
# review queue, instead of paying for an LLM call on every approval.
_DETERMINISTIC_GLOSSARY: dict[str, str] = {
    "AWS": "Amazon's cloud platform for hosting apps, storage, and databases online instead of on physical servers.",
    "Azure": "Microsoft's cloud platform, an alternative to AWS, used to host and run applications online.",
    "GCP": "Google's cloud platform for hosting apps, storage, and data online, similar to AWS and Azure.",
    "Docker": "A tool that packages an app with everything it needs so it runs the same way on any computer.",
    "Kubernetes": "A tool that automatically manages and scales many Docker containers running an application.",
    "SQL": "The standard language used to store, search, and update data in a database.",
    "Python": "A widely used programming language known for being easy to read, used in web apps, data, and automation.",
    "Java": "A widely used programming language for building business applications, especially on servers.",
    "JavaScript": "The programming language that makes websites interactive; runs in every web browser.",
    "React": "A popular JavaScript toolkit for building the interactive parts of websites.",
    "Angular": "A JavaScript framework used to build large, interactive websites and web apps.",
    "Node.js": "A tool that lets JavaScript run on a server, not just in a browser, to build backend applications.",
    ".NET": "Microsoft's software framework for building Windows and web applications, mainly in C#.",
    "C#": "A programming language made by Microsoft, commonly used to build Windows and .NET applications.",
    "C++": "A fast, low-level programming language used for system software, games, and performance-critical apps.",
    "Salesforce": "A widely used cloud platform for managing customer relationships, sales, and support.",
    "SAP": "A major enterprise software suite companies use to run finance, supply chain, and HR operations.",
    "ServiceNow": "A cloud platform companies use to manage IT support requests and internal workflows.",
    "Git": "A tool developers use to track and manage changes to code over time.",
    "Jenkins": "A tool that automatically builds, tests, and deploys code whenever developers make changes.",
    "Terraform": "A tool for setting up cloud infrastructure (servers, networks) using written configuration files.",
    "Ansible": "A tool that automates setting up and configuring servers, so it doesn't have to be done by hand.",
    "Kafka": "A system for moving large volumes of real-time data between different parts of an application.",
    "MongoDB": "A database that stores data in a flexible, document-like format instead of rigid tables.",
    "PostgreSQL": "A free, widely used database system for storing and querying structured data.",
    "MySQL": "A free, widely used database system, common in web applications.",
    "Oracle": "A major commercial database system used by large companies to store business data.",
    "Redis": "A very fast, in-memory database often used for caching to speed up applications.",
    "Linux": "A free, widely used operating system that powers most servers and cloud infrastructure.",
    "REST API": "A common way for software systems to exchange data over the internet.",
    "Machine Learning": "A field of AI where software learns patterns from data instead of following fixed rules.",
    "Tableau": "A tool for turning raw data into interactive charts and dashboards.",
    "Power BI": "Microsoft's tool for turning business data into interactive reports and dashboards.",
    "JIRA": "A widely used tool for tracking software development tasks and bugs.",
    "Agile": "A way of running projects in short cycles with frequent check-ins, instead of one long plan.",
    "Scrum": "A specific, popular way of running Agile projects using short sprints and daily check-ins.",
    "Selenium": "A tool used to automatically test websites by simulating a user clicking through them.",
    "CI/CD": "The practice of automatically testing and deploying code changes as soon as they're made.",
    "PowerShell": "A command-line tool from Microsoft used to automate tasks on Windows systems.",
    "Splunk": "A tool for searching through and analyzing large volumes of system and application logs.",
    "Snowflake": "A cloud-based platform for storing and analyzing very large amounts of business data.",
    "Workday": "A cloud platform companies use to manage HR, payroll, and finance.",
    "Active Directory": "Microsoft's system for managing user accounts and permissions across a company's network.",
    "GitHub": "A website where developers store and collaborate on code using Git.",
    "GitLab": "A platform similar to GitHub for storing code and automating its testing and deployment.",
}

_DETERMINISTIC_GLOSSARY_BY_KEY = {
    normalize_taxonomy_key(name): description for name, description in _DETERMINISTIC_GLOSSARY.items()
}


def _deterministic_description(name: str) -> str | None:
    return _DETERMINISTIC_GLOSSARY_BY_KEY.get(normalize_taxonomy_key(name))


_SYSTEM_PROMPT = (
    "You write entries for a technical skills glossary aimed at IT recruiters "
    "who are not engineers. For the given term, write exactly one sentence "
    "(maximum 25 words) explaining what it is and what it is used for, in "
    "plain language a non-technical recruiter can understand instantly while "
    "reading a candidate's resume. Do not use other jargon to define the "
    "term. Do not start the sentence by repeating the term's name. Return "
    "only the sentence, no preamble, no quotation marks."
)


def generate_skill_description(name: str, category: str | None = None) -> str | None:
    deterministic = _deterministic_description(name)
    if deterministic:
        return deterministic

    if not litellm_configured():
        return None

    user_prompt = f"Term: {name}"
    if category:
        user_prompt += f"\nCategory: {category}"

    messages = [
        PromptRenderedMessage(role="system", content=_SYSTEM_PROMPT),
        PromptRenderedMessage(role="user", content=user_prompt),
    ]

    try:
        output, _usage = _call_litellm_with_model(
            messages, model=os.getenv("HERMES_PROMPT_DEFAULT_MODEL", "anthropic/claude-haiku-4-5")
        )
    except Exception:  # noqa: BLE001
        return None

    description = (output or "").strip().strip('"')

    return description or None
