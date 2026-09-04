from __future__ import annotations

import logging
from typing import Any

from agenticu.classification.mast_taxonomy import match_patterns
from agenticu.classification.signature_db import SignatureDB
from agenticu.models import ClassificationResult, FailureMode, Span

logger = logging.getLogger(__name__)


class Classifier:
    """Two-tier failure classifier.

    Fast path:  rule-based pattern matching against span text.
    Slow path:  embedding cosine similarity against known failure signatures.
    """

    def __init__(self, signature_db: SignatureDB | None = None, fast_path_only: bool = False):
        self.signature_db = signature_db or SignatureDB()
        self.fast_path_only = fast_path_only
        self._embedder: Any = None

    def _lazy_load_embedder(self) -> Any:
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                model_name = self.signature_db.config.get(
                    "model_name", "sentence-transformers/all-MiniLM-L6-v2"
                )
                self._embedder = SentenceTransformer(model_name)
                logger.info("Loaded sentence-transformer model: %s", model_name)
            except ImportError:
                logger.warning("sentence-transformers not installed; fast-path only")
                self.fast_path_only = True
        return self._embedder

    def classify(self, span: Span, trace_text: str | None = None) -> ClassificationResult:
        text = trace_text or self._span_to_text(span)

        # Fast path: pattern matching
        mode, matched = match_patterns(text)
        if mode is not None:
            return ClassificationResult(
                failure_mode=mode,
                confidence=0.8,
                method="pattern",
                matched_pattern=matched,
                trace_snippet=text[:500],
            )

        if self.fast_path_only:
            return ClassificationResult(confidence=0.0)

        # Slow path: embedding similarity
        return self._classify_with_embeddings(text)

    def _classify_with_embeddings(self, text: str) -> ClassificationResult:
        embedder = self._lazy_load_embedder()
        if embedder is None:
            return ClassificationResult(confidence=0.0)

        input_emb = embedder.encode(text, normalize_embeddings=True)

        best_mode: FailureMode | None = None
        best_score = 0.0

        for mode, sig_text in self.signature_db.get_all():
            sig_emb = embedder.encode(sig_text, normalize_embeddings=True)
            score = float(input_emb @ sig_emb)
            if score > best_score:
                best_score = score
                best_mode = mode

        threshold = self.signature_db.config.get("similarity_threshold", 0.75)
        if best_score >= threshold and best_mode is not None:
            return ClassificationResult(
                failure_mode=best_mode,
                confidence=best_score,
                method="embedding",
            )

        return ClassificationResult(confidence=best_score)

    @staticmethod
    def _span_to_text(span: Span) -> str:
        parts = []
        if span.input:
            parts.append(str(span.input))
        if span.output:
            parts.append(str(span.output))
        if span.error_message:
            parts.append(str(span.error_message))
        for attr_val in span.attributes.values():
            if isinstance(attr_val, str):
                parts.append(attr_val)
        return " ".join(parts)
