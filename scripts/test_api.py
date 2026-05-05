"""
scripts/test_api.py
HuggingFace Inference API 연결 및 모델 테스트
python scripts/test_api.py
"""
import sys, os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from models.config import SUPPORTED_MODELS, load_config
from models.hf_api_engine import api_engine

def main():
    cfg = load_config()
    token = cfg["hf_token"]

    print("="*55)
    print("  HuggingFace Inference API 연결 테스트")
    print("="*55)

    if not token or token == "hf_본인토큰을_여기에_입력":
        print("❌ .env 파일에 HF_TOKEN을 설정하세요.")
        sys.exit(1)

    print(f"✅ HF_TOKEN: {token[:8]}…")
    print(f"   기본 모델: {cfg['hf_model_id']}")
    print(f"   Max Tokens: {cfg['max_tokens']}")
    print(f"   Temperature: {cfg['temperature']}")

    # 모든 지원 모델 probe
    print("\n[지원 모델 접근 가능 여부 확인]")
    import requests
    API_BASE = "https://api-inference.huggingface.co/models"
    headers  = {"Authorization": f"Bearer {token}"}

    for m in SUPPORTED_MODELS:
        url = f"{API_BASE}/{m.model_id}"
        try:
            r = requests.post(url, headers=headers,
                json={"inputs":"안녕","parameters":{"max_new_tokens":3},"options":{"wait_for_model":False}},
                timeout=15)
            if r.status_code == 200:
                print(f"  ✅  {m.label:<35} → 정상")
            elif r.status_code == 503:
                print(f"  ⏳  {m.label:<35} → 로딩 중")
            elif r.status_code in (401,403):
                print(f"  🔒  {m.label:<35} → 권한 없음 (라이선스 동의 필요)")
            else:
                print(f"  ❓  {m.label:<35} → HTTP {r.status_code}")
        except Exception as e:
            print(f"  ❌  {m.label:<35} → {e}")

    # 선택 모델로 setup & 추론 테스트
    print(f"\n[{cfg['hf_model_id']} 추론 테스트]")
    result = api_engine.setup(
        hf_token=token, model_id=cfg["hf_model_id"],
        max_tokens=cfg["max_tokens"], temperature=cfg["temperature"],
    )

    if not result["ok"]:
        print(f"❌ 연결 실패: {result['message']}")
        sys.exit(1)

    print(f"✅ 연결 모델: {result['model_id']}")
    if result["message"].startswith("⚠️"):
        print(f"   {result['message']}")

    print("\n추론 테스트 중…")
    import time
    t0  = time.time()
    out = api_engine.generate(
        "갤럭시 스마트폰 배터리 문제 해결 방법 3가지를 간단히 알려주세요.",
        max_tokens=200, temperature=0.2,
    )
    print(f"응답 시간: {time.time()-t0:.1f}초")
    print(f"출력:\n{out[:300]}")
    print("\n✅ 모든 테스트 완료!")

if __name__ == "__main__":
    main()
