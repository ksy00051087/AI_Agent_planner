"""Vector DB (F3022) — Chroma 영구 저장 + GMS 임베딩(text-embedding-3-small).

Chroma 기본 임베딩(영어 모델)은 쓰지 않는다. 문서 · 질의 모두 같은 GMS 임베딩으로 벡터를 만들어 넘긴다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
CHROMA_DIR = ROOT / "data" / "rag" / "chroma"
COLLECTION = "qual_docs"
EMBED_MODEL = "text-embedding-3-small"
BATCH = 64

load_dotenv(ROOT / ".env")


class EmbeddingUnavailable(Exception):
    pass


def embed(texts: list[str]) -> list[list[float]]:
    key = (os.getenv("GMS_API_KEY") or "").strip()
    if not key:
        raise EmbeddingUnavailable("GMS_API_KEY 없음")
    base = (os.getenv("GMS_BASE_URL") or "https://gms.ssafy.io/gmsapi/api.openai.com/v1").rstrip("/")
    res = requests.post(f"{base}/embeddings", headers={"Authorization": f"Bearer {key}"},
                        json={"model": os.getenv("EMBED_MODEL") or EMBED_MODEL, "input": texts}, timeout=60)
    if res.status_code != 200:
        raise EmbeddingUnavailable(f"HTTP {res.status_code}")
    return [d["embedding"] for d in sorted(res.json()["data"], key=lambda d: d["index"])]


def _client(path: Path | None = None):
    import chromadb  # 무거운 import 는 필요할 때만

    return chromadb.PersistentClient(path=str(path or CHROMA_DIR))


def collection(path: Path | None = None, create: bool = False):
    """색인이 없으면 None (create=False 일 때)."""
    client = _client(path)
    if create:
        return client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    try:
        col = client.get_collection(COLLECTION)
    except Exception:
        return None
    return col if col.count() > 0 else None


def rebuild(docs: list[dict], path: Path | None = None,
            embedder: Callable[[list[str]], list[list[float]]] = embed,
            progress: Callable[[int, int], None] | None = None) -> int:
    client = _client(path)
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(docs), BATCH):
        part = docs[i:i + BATCH]
        col.add(ids=[d["id"] for d in part], documents=[d["text"] for d in part],
                embeddings=embedder([d["text"] for d in part]),
                metadatas=[{k: (d.get(k) or "") for k in ("qual_id", "qual_name", "kind", "source", "url")} for d in part])
        if progress:
            progress(min(i + BATCH, len(docs)), len(docs))
    return col.count()
