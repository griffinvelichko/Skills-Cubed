import os

EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))


def validate_embedding(embedding: list[float], context: str = "") -> None:
    """Fail fast if embedding dimension doesn't match config."""
    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"Expected embedding dim {EMBEDDING_DIM}, got {len(embedding)}"
            + (f" ({context})" if context else "")
        )
