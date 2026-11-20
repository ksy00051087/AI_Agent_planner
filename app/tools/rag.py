"""RAG 검색 툴 (F3022) — 로컬 서버 API 툴. 이 서비스가 가진 Vector DB(Chroma)를 검색한다.

외부 API 로 계산하는 값(시험일 · 응시료)이 아니라, 문서로만 있는 정보(시험과목 · 검정방법 · 합격기준 ·
응시자격 안내 · 출제경향 · 시행기관 · 소관부처)를 근거 문서와 출처째 돌려준다. 문장을 지어내지 않고 원문 조각을 준다.
색인이 없으면 NO_INDEX — '아직 모으지 못했다'. 색인은 scripts/build_index.py 로 만든다.
"""

from __future__ import annotations

from app.rag import store

from .base import BAD_ARGUMENT, INVALID_KEY, NO_DATA, UPSTREAM_ERROR, fail, ok

NO_INDEX = "NO_INDEX"
MAX_DISTANCE = 0.75   # 코사인 거리. 이보다 멀면 관련 없는 문서로 본다


def search_documents(query: str, qualification_name: str | None = None, limit: int = 4):
    if not query or not str(query).strip():
        return fail(BAD_ARGUMENT, "query(질문)는 필수입니다.")
    if not isinstance(limit, int) or not 1 <= limit <= 10:
        return fail(BAD_ARGUMENT, "limit 는 1~10 사이 정수여야 합니다.")
    try:
        col = store.collection()
    except Exception:
        return fail(UPSTREAM_ERROR, "문서 색인을 열지 못했습니다.")
    if col is None:
        return fail(NO_INDEX, "자격 정보 문서 색인이 아직 없습니다 (scripts/build_index.py 로 만듭니다).")
    try:
        vec = store.embed([f"{qualification_name or ''} {query}".strip()])[0]
    except store.EmbeddingUnavailable as e:
        code = INVALID_KEY if "키" in str(e) or "KEY" in str(e) else UPSTREAM_ERROR
        return fail(code, "질문을 검색용 벡터로 바꾸지 못했습니다.")

    def run(where):
        res = col.query(query_embeddings=[vec], n_results=limit, where=where)
        return [{"text": doc, "qual_name": meta.get("qual_name") or None, "kind": meta.get("kind") or None,
                 "source": meta.get("source"), "url": meta.get("url") or None, "distance": round(dist, 3)}
                for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
                if dist <= MAX_DISTANCE]

    items, scoped = [], False
    if qualification_name:
        items = run({"qual_name": qualification_name})   # 자격명을 정확히 알면 그 자격 문서만
        scoped = bool(items)
    if not items:
        items = run(None)
    if not items:
        return fail(NO_DATA, "질문과 관련된 문서를 찾지 못했습니다.")
    return ok({"query": query, "qualification_name": qualification_name, "scoped_to_qualification": scoped,
               "basis": "자격 정보 문서 원문 조각 (요약 · 생성 아님). 거리가 작을수록 질문과 가깝다.", "items": items})
