from app.context.models import RelationshipCardBuildRequest, RelationshipCardV1


def build_relationship_card(request: RelationshipCardBuildRequest) -> RelationshipCardV1:
    """Builds a compact Relationship Card from already-summarized interaction records.

    This does not summarize raw message text itself (that is conversation
    compression's job) - it packs pre-existing interaction summaries into a bounded
    card so a full interaction history is never passed to an LLM prompt.
    """
    interactions = sorted(
        request.interactions,
        key=lambda interaction: interaction.get("date") or "",
        reverse=True,
    )

    last_summary = None
    if interactions:
        last_summary = interactions[0].get("summary")

    return RelationshipCardV1(
        contact_name=request.contact_name,
        relationship_type=request.relationship_type,
        shared_context=request.shared_context[:10],
        last_interaction_summary=last_summary,
        interaction_count=len(request.interactions),
        metadata=request.metadata,
    )
