from pydantic import BaseModel, Field
import tiktoken


class CompressionResult(BaseModel):
    text: str
    original_token_count: int
    compressed_token_count: int
    max_tokens: int
    compression_applied: bool = False
    strategy: str = "none"
    metadata: dict[str, int | str | bool] = Field(default_factory=dict)


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(text or ""))


def compress_to_token_budget(
    text: str,
    max_tokens: int = 1200,
    encoding_name: str = "cl100k_base",
) -> CompressionResult:
    clean_text = (text or "").strip()
    encoding = tiktoken.get_encoding(encoding_name)
    tokens = encoding.encode(clean_text)

    original_token_count = len(tokens)

    if original_token_count <= max_tokens:
        return CompressionResult(
            text=clean_text,
            original_token_count=original_token_count,
            compressed_token_count=original_token_count,
            max_tokens=max_tokens,
            compression_applied=False,
            strategy="none",
            metadata={"encoding": encoding_name},
        )

    separator = "\n\n[...compressed middle content...]\n\n"
    separator_tokens = encoding.encode(separator)

    available_tokens = max_tokens - len(separator_tokens)

    if available_tokens <= 20:
        compressed_tokens = tokens[:max_tokens]
        strategy = "hard_truncate"
    else:
        head_size = int(available_tokens * 0.65)
        tail_size = available_tokens - head_size
        compressed_tokens = tokens[:head_size] + separator_tokens + tokens[-tail_size:]
        strategy = "head_tail"

    compressed_text = encoding.decode(compressed_tokens).strip()
    compressed_token_count = len(encoding.encode(compressed_text))

    return CompressionResult(
        text=compressed_text,
        original_token_count=original_token_count,
        compressed_token_count=compressed_token_count,
        max_tokens=max_tokens,
        compression_applied=True,
        strategy=strategy,
        metadata={"encoding": encoding_name},
    )
