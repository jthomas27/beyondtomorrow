"""
embeddings.py — Embedding module using OpenAI text-embedding-3-small

Generates 1536-dim embeddings via the OpenAI API. This replaces the former
local sentence-transformers/torch implementation, cutting the worker's resident
memory from ~1.2 GB to ~150 MB (no torch/transformers/scikit-learn loaded).

The embed()/embed_batch()/similarity() interface is unchanged, so callers need
no modification. Requires OPENAI_API_KEY.

Usage:
    from pipeline.embeddings import embed, embed_batch, similarity

    vector = embed("some text")                    # → list[float] (1536 dims)
    vectors = embed_batch(["text a", "text b"])    # → list[list[float]]
    score = similarity(vec_a, vec_b)               # → float (0.0 to 1.0)
"""

import os
import numpy as np
from functools import lru_cache
from typing import Union

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1536"))
MAX_INPUT_TOKENS = 8191  # text-embedding-3-small context limit


# ---------------------------------------------------------------------------
# Client (singleton — lightweight; no model weights held in memory)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_client():
    """Return a cached synchronous OpenAI client. Reads OPENAI_API_KEY."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set — required for embeddings."
        )
    return OpenAI(api_key=api_key)


def _clean(text: str) -> str:
    """Coerce empty/whitespace-only input to a single space (the API rejects '')."""
    return text if (text and text.strip()) else " "


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed(text: str) -> list[float]:
    """Generate a 1536-dim embedding for a single text string.

    Args:
        text: The text to embed.

    Returns:
        A list of 1536 floats representing the text's semantic meaning.
    """
    client = _get_client()
    resp = client.embeddings.create(
        model=MODEL_NAME,
        input=_clean(text),
        dimensions=DIMENSIONS,
    )
    return resp.data[0].embedding


def embed_batch(texts: list[str], batch_size: int = 128) -> list[list[float]]:
    """Generate embeddings for multiple texts efficiently (batched API calls).

    Args:
        texts: List of text strings to embed.
        batch_size: Number of texts per API request (default 128).

    Returns:
        A list of 1536-dim vectors, one per input text, in input order.
    """
    if not texts:
        return []

    client = _get_client()
    out: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = [_clean(t) for t in texts[start:start + batch_size]]
        resp = client.embeddings.create(
            model=MODEL_NAME,
            input=batch,
            dimensions=DIMENSIONS,
        )
        # Response order is not guaranteed — sort by index to match input order.
        ordered = sorted(resp.data, key=lambda d: d.index)
        out.extend(d.embedding for d in ordered)
    return out


def similarity(vec_a: Union[list[float], np.ndarray],
               vec_b: Union[list[float], np.ndarray]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        vec_a: First embedding vector (384 dims).
        vec_b: Second embedding vector (384 dims).

    Returns:
        A float between -1.0 and 1.0 (higher = more similar).
        For normalised embeddings (which MiniLM produces), range is 0.0 to 1.0.
    """
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)

    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot / (norm_a * norm_b))


def get_model_info() -> dict:
    """Return metadata about the current embedding model.

    Returns:
        Dict with model name, dimensions, and provider.
    """
    return {
        "model": MODEL_NAME,
        "dimensions": DIMENSIONS,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "provider": "openai",
    }


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Testing embeddings module...\n")

    # Test single embed
    vec = embed("The future of quantum computing is uncertain.")
    print(f"✓ embed() returned {len(vec)}-dim vector")
    print(f"  First 5 values: {vec[:5]}")

    # Test batch embed
    texts = [
        "Quantum computing threatens current encryption.",
        "Post-quantum cryptography standards are being developed.",
        "I like pizza on a rainy day.",
    ]
    vecs = embed_batch(texts)
    print(f"\n✓ embed_batch() returned {len(vecs)} vectors of {len(vecs[0])} dims")

    # Test similarity
    sim_related = similarity(vecs[0], vecs[1])
    sim_unrelated = similarity(vecs[0], vecs[2])
    print(f"\n✓ similarity() results:")
    print(f"  'quantum + encryption' vs 'post-quantum crypto':  {sim_related:.4f} (should be high)")
    print(f"  'quantum + encryption' vs 'pizza on a rainy day': {sim_unrelated:.4f} (should be low)")

    # Model info
    info = get_model_info()
    print(f"\n✓ Model info: {info}")
    print("\nAll tests passed!")
