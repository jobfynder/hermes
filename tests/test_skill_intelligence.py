from app.skill_intelligence.service import (
    extract_requirement_intelligence,
    get_skill,
    resolve,
    resolve_batch,
    search,
)


def test_aliases_resolve_to_canonical_identity():
    cases = {
        "K8s": "Kubernetes",
        "Postgres": "PostgreSQL",
        "ReactJS": "React",
        "SpringBoot": "Spring Boot",
    }
    for alias, expected in cases.items():
        result = resolve(alias)
        assert result["matched"] is True
        assert result["canonical_name"] == expected
        assert result["skill_id"].startswith("skill_")


def test_short_ambiguous_term_is_not_fuzzy_matched():
    result = resolve("goe")
    assert result["matched"] is False
    assert result["match_type"] == "unknown"


def test_requirement_classification_and_stack_are_deterministic():
    result = extract_requirement_intelligence(
        "Must have Java, Spring Boot and AWS. Kubernetes preferred. Kafka nice to have."
    )
    required = {row["canonical_name"] for row in result["skills"]["required"]}
    preferred = {row["canonical_name"] for row in result["skills"]["preferred"]}
    assert {"Java", "Spring Boot", "AWS"} <= required
    assert {"Kubernetes", "Kafka"} <= preferred
    assert result["taxonomy_version"].startswith("skills-")
    assert list(result["stack"]) == sorted(result["stack"])


def test_relationship_is_context_not_equivalence():
    resolved = resolve("K8s")
    card = get_skill(resolved["skill_id"])
    assert card is not None
    assert any(row["name"] == "Docker" for row in card["relationships"])
    assert resolve("Docker")["skill_id"] != resolved["skill_id"]


def test_batch_and_search_contracts_are_compact_and_stable():
    batch = resolve_batch(["K8s", "K8s", "Postgres"])
    assert len(batch["results"]) == 2
    assert [row["input"] for row in batch["results"]] == ["K8s", "Postgres"]
    results = search("kuber")
    assert results[0]["canonical_name"] == "Kubernetes"
    assert "taxonomy_version" in results[0]
