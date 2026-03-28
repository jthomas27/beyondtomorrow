"""
embeddings.py — Local embedding module using BAAI/bge-small-en-v1.5

Provides a simple interface for generating 384-dim embeddings locally
on Railway compute using the sentence-transformers library. No API calls,
no API keys, zero cost.

Usage:
    from pipeline.embeddings import embed, embed_batch, similarity

    vector = embed("some text")                    # → list[float] (384 dims)
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

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
DIMENSIONS = 384  # bge-small-en-v1.5 output size (same as MiniLM)
MAX_INPUT_TOKENS = 512  # model max input (word pieces, ~350 words)


# ---------------------------------------------------------------------------
# Model loading (singleton — loaded once, stays in memory)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_model():
    """Load the sentence-transformers model. Cached — only runs once."""
    from sentence_transformers import SentenceTransformer

    print(f"[embeddings] Loading model: {MODEL_NAME} ({DIMENSIONS} dims)...")
    model = SentenceTransformer(MODEL_NAME)
    print(f"[embeddings] Model loaded successfully.")
    return model


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed(text: str) -> list[float]:
    """Generate a 384-dim embedding for a single text string.

    Args:
        text: The text to embed. Texts longer than ~200 words are truncated
              by the model automatically.

    Returns:
        A list of 384 floats representing the text's semantic meaning.
    """
    model = _get_model()
    vector = model.encode(text, show_progress_bar=False)
    return vector.tolist()


def embed_batch(texts: list[str], batch_size: int = 64) -> list[list[float]]:
    """Generate embeddings for multiple texts efficiently.

    Args:
        texts: List of text strings to embed.
        batch_size: Number of texts to process at once (default 64).

    Returns:
        A list of 384-dim vectors, one per input text.
    """
    if not texts:
        return []

    model = _get_model()
    vectors = model.encode(texts, batch_size=batch_size, show_progress_bar=False)
    return vectors.tolist()


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
        Dict with model name, dimensions, and load status.
    """
    is_loaded = _get_model.cache_info().hits > 0 or _get_model.cache_info().currsize > 0
    return {
        "model": MODEL_NAME,
        "dimensions": DIMENSIONS,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "loaded": is_loaded,
        "cost_per_call": 0.0,  # free — runs locally
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
