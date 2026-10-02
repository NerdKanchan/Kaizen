"""L4: semantic similarity with a pluggable embedding function. Optional and offline-capable: pass any callable
that maps texts to vectors (e.g. a locally installed sentence-transformers model). Yields POTENTIAL at most."""

import math
from collections.abc import Callable, Sequence

from kaizen.matching.ladder import MatchContext, MatchOutcome
from kaizen.matching.normalize import NormalizedText
from kaizen.models import MatchLevel

Embedder = Callable[[Sequence[str]], Sequence[Sequence[float]]]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticMatcher:
    name = "L4_semantic"

    def __init__(self, embed: Embedder, threshold: float = 0.85, model_name: str = "custom-embedder"):
        self.embed = embed
        self.threshold = threshold
        self.model_name = model_name
        self._cache: dict[str, Sequence[float]] = {}

    def _vec(self, text: str) -> Sequence[float]:
        if text not in self._cache:
            self._cache[text] = list(self.embed([text])[0])
        return self._cache[text]

    def try_match(self, a: NormalizedText, b: NormalizedText, ctx: MatchContext) -> MatchOutcome | None:
        sim = cosine(self._vec(a.normalized), self._vec(b.normalized))
        if sim < self.threshold:
            return None
        reason = f'POTENTIAL: "{a.raw}" ↔ "{b.raw}"; semantic similarity {sim:.2f} ({self.model_name}, threshold {self.threshold:.2f}); no approved terminology relationship — reviewer to confirm'
        return MatchOutcome(MatchLevel.SEMANTIC, round(sim, 4), reason)


def sentence_transformer_embedder(model_name: str = "all-MiniLM-L6-v2") -> Embedder:
    """Builds an embedder from a locally installed sentence-transformers model (optional dependency; the model
    must already be available locally — nothing is downloaded by the engine)."""
    from sentence_transformers import SentenceTransformer  # optional

    model = SentenceTransformer(model_name, local_files_only=True)

    def embed(texts: Sequence[str]):
        return model.encode(list(texts), normalize_embeddings=True).tolist()

    return embed
