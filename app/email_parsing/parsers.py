import re
from typing import Any

from app.services.consultant_service import parse_consultant_text
from app.understanding.models import RawDocument
from app.understanding.service import understand_document


PARSER_METADATA = {
    "name": "hermes_email_deterministic_parser",
    "version": "hermes_email_parser_v1",
    "uses_llm": False,
}


HEADER_ALIASES = {
    "name": "candidate_name",
    "candidate": "candidate_name",
    "candidate name": "candidate_name",
    "consultant": "candidate_name",
    "consultant name": "candidate_name",
    "resource": "candidate_name",
    "resource name": "candidate_name",
    "title": "primary_job_title",
    "job title": "primary_job_title",
    "role": "primary_job_title",
    "technology": "primary_job_title",
    "skill": "primary_skills",
    "skills": "primary_skills",
    "primary skill": "primary_skills",
    "primary skills": "primary_skills",
    "experience": "years_of_experience",
    "exp": "years_of_experience",
    "years": "years_of_experience",
    "total experience": "years_of_experience",
    "location": "current_location",
    "current location": "current_location",
    "visa": "work_authorization",
    "visa status": "work_authorization",
    "work authorization": "work_authorization",
    "work auth": "work_authorization",
    "availability": "availability",
    "available": "availability",
    "available from": "availability",
    "rate": "expected_rate",
    "bill rate": "expected_rate",
    "expected rate": "expected_rate",
    "email": "candidate_email",
    "candidate email": "candidate_email",
    "phone": "candidate_phone",
    "mobile": "candidate_phone",
}


def _clean_email_text(text: str) -> str:
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()

    if lines and lines[0].strip().lower().startswith("subject:"):
        lines = lines[1:]

    return "\n".join(lines).strip()


def _normalize_header(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _split_list(value: str | None) -> list[str]:
    if not value:
        return []

    return [
        item.strip()
        for item in re.split(r"[,;]", value)
        if item.strip()
    ]


def _extract_integer(value: str | None) -> int | None:
    if not value:
        return None

    match = re.search(r"\b(\d{1,2})\b", value)

    if not match:
        return None

    number = int(match.group(1))

    if number > 60:
        return None

    return number


def _extract_labeled_value(text: str, labels: list[str]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)

    match = re.search(
        rf"(?im)^\s*(?:{label_pattern})\s*[:\-]\s*(.+?)\s*$",
        text or "",
    )

    if not match:
        return None

    return match.group(1).strip()


def _hotlist_record_confidence(record: dict[str, Any]) -> float:
    has_name = bool(record.get("candidate_name"))
    has_role = bool(
        record.get("primary_job_title")
        or record.get("primary_skills")
    )

    if has_name and has_role:
        return 0.92

    if has_name or has_role:
        return 0.62

    return 0.30


def _build_table_hotlist_records(text: str) -> list[dict[str, Any]]:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for delimiter in ("|", "\t"):
        for header_index, line in enumerate(lines):
            if delimiter not in line:
                continue

            raw_headers = [
                item.strip()
                for item in line.split(delimiter)
            ]

            mapped_headers = [
                HEADER_ALIASES.get(_normalize_header(item))
                for item in raw_headers
            ]

            recognized_count = sum(
                1
                for item in mapped_headers
                if item is not None
            )

            if recognized_count < 2:
                continue

            records: list[dict[str, Any]] = []

            for row_number, row in enumerate(
                lines[header_index + 1:],
                start=header_index + 2,
            ):
                if delimiter not in row:
                    continue

                values = [
                    item.strip()
                    for item in row.split(delimiter)
                ]

                if len(values) < 2:
                    continue

                raw_record: dict[str, str] = {}

                for index, canonical_header in enumerate(mapped_headers):
                    if not canonical_header:
                        continue

                    if index < len(values):
                        raw_record[canonical_header] = values[index]

                if not raw_record:
                    continue

                record = {
                    "record_type": "consultant_hotlist",
                    "candidate_name": raw_record.get("candidate_name"),
                    "candidate_email": raw_record.get("candidate_email"),
                    "candidate_phone": raw_record.get("candidate_phone"),
                    "primary_job_title": raw_record.get("primary_job_title"),
                    "primary_skills": _split_list(
                        raw_record.get("primary_skills")
                    ),
                    "years_of_experience": _extract_integer(
                        raw_record.get("years_of_experience")
                    ),
                    "current_location": raw_record.get("current_location"),
                    "work_authorization": raw_record.get("work_authorization"),
                    "availability": raw_record.get("availability"),
                    "expected_rate": raw_record.get("expected_rate"),
                    "source_row": row_number,
                    "warnings": [],
                }

                confidence = _hotlist_record_confidence(record)
                record["parse_confidence"] = confidence
                record["requires_review"] = confidence < 0.70

                if not record.get("candidate_name"):
                    record["warnings"].append("candidate_name_missing")

                if not (
                    record.get("primary_job_title")
                    or record.get("primary_skills")
                ):
                    record["warnings"].append(
                        "candidate_title_or_skills_missing"
                    )

                records.append(record)

            if records:
                return records

    return []


def _build_fallback_hotlist_records(text: str) -> list[dict[str, Any]]:
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n", text)
        if block.strip()
    ]

    candidate_blocks = [
        block
        for block in blocks
        if re.search(
            r"(?im)^\s*(?:name|candidate|consultant)\s*[:\-]",
            block,
        )
    ]

    if not candidate_blocks:
        candidate_blocks = [text]

    records: list[dict[str, Any]] = []

    for index, block in enumerate(candidate_blocks, start=1):
        parsed = parse_consultant_text(block)

        candidate_name = (
            _extract_labeled_value(
                block,
                ["Name", "Candidate", "Candidate Name", "Consultant"],
            )
            or parsed.get("name")
        )

        record = {
            "record_type": "consultant_hotlist",
            "candidate_name": candidate_name,
            "candidate_email": _extract_labeled_value(
                block,
                ["Email", "Candidate Email"],
            ),
            "candidate_phone": _extract_labeled_value(
                block,
                ["Phone", "Mobile"],
            ),
            "primary_job_title": (
                _extract_labeled_value(
                    block,
                    ["Title", "Job Title", "Role", "Technology"],
                )
                or parsed.get("title")
            ),
            "primary_skills": parsed.get("skills") or [],
            "years_of_experience": parsed.get("experience_years"),
            "current_location": parsed.get("location"),
            "work_authorization": parsed.get("work_authorization"),
            "availability": parsed.get("availability"),
            "expected_rate": parsed.get("rate"),
            "source_block": index,
            "warnings": [],
        }

        confidence = _hotlist_record_confidence(record)
        record["parse_confidence"] = confidence
        record["requires_review"] = confidence < 0.70

        if not record.get("candidate_name"):
            record["warnings"].append("candidate_name_missing")

        if not (
            record.get("primary_job_title")
            or record.get("primary_skills")
        ):
            record["warnings"].append(
                "candidate_title_or_skills_missing"
            )

        records.append(record)

    return records


def parse_hotlist_email(text: str) -> dict[str, Any]:
    clean_text = _clean_email_text(text)

    records = _build_table_hotlist_records(clean_text)

    if not records:
        records = _build_fallback_hotlist_records(clean_text)

    confidence = min(
        (
            float(record.get("parse_confidence", 0.0))
            for record in records
        ),
        default=0.0,
    )

    warnings: list[str] = []

    if not records:
        warnings.append("no_consultants_detected")

    if any(record.get("requires_review") for record in records):
        warnings.append("one_or_more_consultants_require_review")

    return {
        "parser": PARSER_METADATA,
        "document_kind": "hotlist",
        "records": records,
        "record_count": len(records),
        "confidence": confidence,
        "requires_review": (
            not records
            or any(record.get("requires_review") for record in records)
        ),
        "warnings": warnings,
    }


def _split_requirement_sections(text: str) -> list[str]:
    matches = list(
        re.finditer(
            r"(?im)^\s*(?:job title|position|role)\s*[:\-]",
            text,
        )
    )

    if len(matches) <= 1:
        return [text]

    sections: list[str] = []

    for index, match in enumerate(matches):
        start = match.start()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )

        section = text[start:end].strip()

        if section:
            sections.append(section)

    return sections or [text]


def parse_requirement_email(text: str) -> dict[str, Any]:
    clean_text = _clean_email_text(text)
    sections = _split_requirement_sections(clean_text)
    records: list[dict[str, Any]] = []

    for index, section in enumerate(sections, start=1):
        understanding = understand_document(
            RawDocument(
                content=section,
                filename=None,
                content_type="text/plain",
                document_kind="job_description",
            )
        )

        structured = understanding.structured_data
        required_skills = [
            item.get("name")
            for item in structured.get("required_skills", [])
            if isinstance(item, dict) and item.get("name")
        ]
        preferred_skills = [
            item.get("name")
            for item in structured.get("preferred_skills", [])
            if isinstance(item, dict) and item.get("name")
        ]

        job_title = (
            _extract_labeled_value(
                section,
                ["Job Title", "Position", "Role"],
            )
            or structured.get("job_title")
        )

        has_title = bool(job_title)
        has_content = bool(required_skills or section.strip())

        confidence = 0.92 if has_title and has_content else (
            0.62 if has_title or required_skills else 0.35
        )

        warnings: list[str] = []

        if not has_title:
            warnings.append("job_title_missing")

        if not required_skills:
            warnings.append("required_skills_not_identified")

        records.append(
            {
                "record_type": "job_requirement",
                "job_title": job_title,
                "job_description": section,
                "required_skills": required_skills,
                "preferred_skills": preferred_skills,
                "years_of_experience": structured.get(
                    "years_experience"
                ),
                "location": structured.get("location"),
                "work_authorization": structured.get(
                    "work_authorization"
                ),
                "employment_type": structured.get(
                    "employment_type"
                ),
                "rate_or_salary": structured.get(
                    "rate_or_salary"
                ),
                "source_section": index,
                "parse_confidence": confidence,
                "requires_review": confidence < 0.70,
                "warnings": warnings,
            }
        )

    confidence = min(
        (
            float(record.get("parse_confidence", 0.0))
            for record in records
        ),
        default=0.0,
    )

    return {
        "parser": PARSER_METADATA,
        "document_kind": "job_description",
        "records": records,
        "record_count": len(records),
        "confidence": confidence,
        "requires_review": (
            not records
            or any(record.get("requires_review") for record in records)
        ),
        "warnings": (
            ["one_or_more_requirements_require_review"]
            if any(record.get("requires_review") for record in records)
            else []
        ),
    }


def parse_email_business_records(
    text: str,
    document_kind: str,
) -> dict[str, Any]:
    if document_kind == "hotlist":
        return parse_hotlist_email(text)

    if document_kind == "job_description":
        return parse_requirement_email(text)

    return {
        "parser": PARSER_METADATA,
        "document_kind": document_kind,
        "records": [],
        "record_count": 0,
        "confidence": 0.0,
        "requires_review": True,
        "warnings": ["unsupported_email_document_kind"],
    }
