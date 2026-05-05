from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 12:
        return "*" * len(value)
    return value[:6] + "..." + value[-4:]


def main() -> int:
    print(f"ROOT={ROOT}")
    print(f"ENV_PATH={ENV_PATH}")
    if not ENV_PATH.exists():
        print("❌ .env 파일이 없습니다. .env.example을 복사해서 .env를 만드세요.")
        return 1

    values = dotenv_values(ENV_PATH)
    print("dotenv keys=", ", ".join(values.keys()))
    load_dotenv(ENV_PATH, override=True)

    token = (os.getenv("HF_TOKEN") or "").strip().strip('"').strip("'")
    engine = (os.getenv("LLM_ENGINE") or "").strip()
    model = (os.getenv("HF_ROUTER_MODEL") or os.getenv("HF_MODEL_ID") or "").strip()
    candidates = (os.getenv("HF_MODEL_CANDIDATES") or "").strip()

    print("LLM_ENGINE=", engine)
    print("HF_TOKEN=", mask(token))
    print("HF_ROUTER_MODEL=", model)
    print("HF_MODEL_CANDIDATES count=", len([x for x in candidates.split(",") if x.strip()]))

    if not token.startswith("hf_"):
        print("❌ HF_TOKEN 형식이 올바르지 않습니다.")
        return 2
    if not model:
        print("❌ HF_ROUTER_MODEL 또는 HF_MODEL_ID가 없습니다.")
        return 3

    print("✅ 환경 변수 로드 성공")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
