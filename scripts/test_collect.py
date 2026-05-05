"""
scripts/test_collect.py
VOC 수집 테스트 (모델 없이 실행 가능)
python scripts/test_collect.py [--live]
"""
import sys, argparse, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.voc_collector import get_demo_voc, build_stats, collect_naver_kin, collect_dcinside

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="실제 크롤링 실행")
    args = parser.parse_args()

    print("="*50)
    print("  VOC 수집 모듈 테스트")
    print("="*50)

    # 데모 데이터
    demo  = get_demo_voc()
    stats = build_stats(demo)
    print(f"\n[데모 데이터] {len(demo)}건")
    for cat, cnt in stats["by_category"].items():
        bar = "█" * int(cnt / max(stats["by_category"].values()) * 20)
        print(f"  {cat:<16} {bar:<20} {cnt}건")

    if args.live:
        print("\n[실제 크롤링]")
        tasks = [
            ("네이버 지식인", lambda: collect_naver_kin("갤럭시 불편", 5)),
            ("DC인사이드",    lambda: collect_dcinside("galaxys24", "갤럭시S24", 5)),
        ]
        for name, fn in tasks:
            print(f"  {name}…", end="", flush=True)
            try:
                items = fn()
                print(f" {len(items)}건")
                for it in items[:2]:
                    print(f"    · {it.title[:50]}")
            except Exception as e:
                print(f" ❌ {e}")
            time.sleep(1.5)
    else:
        print("\n💡 실제 크롤링: python scripts/test_collect.py --live")

    print("\n✅ 완료!")

if __name__ == "__main__":
    main()
