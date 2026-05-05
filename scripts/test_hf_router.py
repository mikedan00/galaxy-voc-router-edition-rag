from __future__ import annotations

from models.config import load_config
from models.hf_api_engine import api_engine


def main() -> int:
    cfg = load_config()
    token = cfg["hf_token"]
    if not token:
        print("❌ HF_TOKEN missing")
        return 1

    result = api_engine.setup(
        hf_token=token,
        model_id=cfg["hf_router_model"],
        max_tokens=cfg["max_tokens"],
        temperature=cfg["temperature"],
        auto_fallback=True,
        candidates=cfg["hf_model_candidates"],
    )
    print(result["message"])
    for item in result.get("attempts", []):
        print("-", item.get("model"), item.get("status_code"), item.get("error_type"), item.get("message"))
    if not result["ok"]:
        return 2

    text = api_engine.generate("갤럭시 배터리 VOC 3가지를 한 줄씩 요약해줘.", max_tokens=160, temperature=0.1)
    print("\n[response]\n", text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
