from app.context.models import ConversationCompressRequest, ConversationContextV1
from app.understanding.compression.token_budget import compress_to_token_budget


def compress_conversation(request: ConversationCompressRequest) -> ConversationContextV1:
    """Compresses a full message history into a bounded context object. This is
    the only form of conversation data that should reach an LLM prompt - never
    the raw message list.
    """
    full_text = "\n".join(
        f"{message.get('sender', 'unknown')}: {message.get('text', '')}"
        for message in request.messages
    )

    compressed = compress_to_token_budget(full_text, max_tokens=request.max_tokens)

    return ConversationContextV1(
        compressed_text=compressed.text,
        message_count=len(request.messages),
        original_token_count=compressed.original_token_count,
        compressed_token_count=compressed.compressed_token_count,
        compression_applied=compressed.compression_applied,
        metadata=request.metadata,
    )
