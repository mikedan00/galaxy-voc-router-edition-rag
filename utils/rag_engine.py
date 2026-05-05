"""
utils/rag_engine.py

외부 벡터DB 없이 동작하는 경량 RAG 엔진.
- Streamlit Cloud 배포 안정성을 위해 torch/faiss/chroma/sentence-transformers 미사용
- 문서를 토큰화한 뒤 TF-IDF 코사인 유사도로 top-k 검색
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List

from utils.file_ingestor import DocumentChunk

TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")


@dataclass
class SearchHit:
    rank: int
    score: float
    source: str
    title: str
    text: str
    chunk_id: str
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "score": round(self.score, 4),
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "chunk_id": self.chunk_id,
            "metadata": self.metadata,
        }


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


class SimpleRAGIndex:
    def __init__(self, chunks: Iterable[DocumentChunk] | None = None):
        self.chunks: list[DocumentChunk] = []
        self.doc_tf: list[Counter] = []
        self.doc_norms: list[float] = []
        self.idf: dict[str, float] = {}
        if chunks:
            self.build(list(chunks))

    def build(self, chunks: list[DocumentChunk]) -> None:
        self.chunks = [c for c in chunks if (c.text or "").strip()]
        self.doc_tf = [Counter(tokenize(c.text)) for c in self.chunks]
        df = Counter()
        for tf in self.doc_tf:
            for token in tf.keys():
                df[token] += 1
        n = max(len(self.doc_tf), 1)
        self.idf = {tok: math.log((n + 1) / (freq + 1)) + 1.0 for tok, freq in df.items()}
        self.doc_norms = [self._norm(tf) for tf in self.doc_tf]

    def _norm(self, tf: Counter) -> float:
        value = 0.0
        for tok, freq in tf.items():
            weight = (1 + math.log(freq)) * self.idf.get(tok, 0.0)
            value += weight * weight
        return math.sqrt(value) or 1.0

    def _score(self, query_tf: Counter, doc_tf: Counter, doc_norm: float) -> float:
        numerator = 0.0
        q_norm_val = 0.0
        for tok, qfreq in query_tf.items():
            q_weight = (1 + math.log(qfreq)) * self.idf.get(tok, 0.0)
            q_norm_val += q_weight * q_weight
            if tok in doc_tf:
                d_weight = (1 + math.log(doc_tf[tok])) * self.idf.get(tok, 0.0)
                numerator += q_weight * d_weight
        q_norm = math.sqrt(q_norm_val) or 1.0
        return numerator / (q_norm * doc_norm)

    def search(self, query: str, top_k: int = 6, min_score: float = 0.0) -> list[SearchHit]:
        if not self.chunks:
            return []
        query_tf = Counter(tokenize(query))
        if not query_tf:
            return []
        scored = []
        for idx, tf in enumerate(self.doc_tf):
            score = self._score(query_tf, tf, self.doc_norms[idx])
            if score > min_score:
                scored.append((score, idx))
        scored.sort(reverse=True, key=lambda x: x[0])
        hits = []
        for rank, (score, idx) in enumerate(scored[:top_k], start=1):
            c = self.chunks[idx]
            hits.append(SearchHit(rank, score, c.source, c.title, c.text, c.chunk_id, c.metadata))
        return hits


def chunks_from_voc(voc_items: Iterable) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for i, item in enumerate(voc_items):
        if hasattr(item, "to_dict"):
            d = item.to_dict()
        else:
            d = dict(item)
        text = f"제목: {d.get('title','')}\n내용: {d.get('content','')}\n카테고리: {d.get('category','')}\n감성: {d.get('sentiment','')}"
        chunks.append(DocumentChunk(
            source=d.get("source", "VOC"),
            title=d.get("title", f"VOC {i}"),
            text=text,
            chunk_id=f"voc-{i}",
            metadata={"url": d.get("url", ""), "category": d.get("category", ""), "sentiment": d.get("sentiment", "")},
        ))
    return chunks


def build_context(hits: list[SearchHit], max_chars: int = 3500) -> str:
    parts = []
    used = 0
    for h in hits:
        block = f"[근거 {h.rank}] source={h.source} | title={h.title} | score={h.score:.3f}\n{h.text.strip()}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts)
