"""NF3001 — git 에 올라가는 파일에 키가 들어가지 않았는지 확인한다."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_NAME = re.compile(r"^([A-Z_]*(KEY|SECRET|CLIENT_ID|TOKEN))=(.*)$", re.M)


def test_env_example_에는_키_값이_비어_있다():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    filled = [m.group(1) for m in SECRET_NAME.finditer(text) if m.group(3).strip()]
    assert filled == [], f".env.example 에 키가 들어 있습니다 (.env 로 옮기세요): {filled}"
