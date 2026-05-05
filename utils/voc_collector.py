"""
utils/voc_collector.py

Galaxy VOC Collector용 수집 유틸리티.
- 기본 채널: 삼성 Members, 네이버 지식인/카페, DC인사이드, 클리앙
- 사용자 URL 추가 수집: URL을 직접 입력해 VOC 소스로 추가
- Streamlit Cloud 안정성을 위해 BeautifulSoup parser는 html.parser 사용
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
DELAY_SEC = 1.2
TIMEOUT_SEC = 12

CATEGORY_KW: dict[str, list[str]] = {
    "배터리/전원": ["배터리", "방전", "충전", "전원", "전력", "충전기", "발열", "절전"],
    "카메라": ["카메라", "사진", "촬영", "렌즈", "야간", "줌", "셀카", "화질", "동영상", "보정"],
    "성능/속도": ["렉", "버벅", "느림", "속도", "성능", "발열", "과열", "프리징", "강제종료", "프레임"],
    "디스플레이": ["화면", "디스플레이", "잔상", "번인", "밝기", "색상", "터치", "액정", "주사율"],
    "통신/네트워크": ["와이파이", "wifi", "블루투스", "5g", "lte", "통화", "데이터", "신호", "gps", "끊김"],
    "UI/소프트웨어": ["원ui", "oneui", "업데이트", "앱", "설정", "버그", "오류", "팝업", "광고", "알림", "빅스비"],
    "디자인/하드웨어": ["디자인", "무게", "두께", "그립", "케이스", "버튼", "외관", "힌지"],
    "음향": ["스피커", "마이크", "음질", "이어폰", "볼륨", "소리", "통화음"],
    "보안/생체인식": ["지문", "얼굴인식", "생체", "비밀번호", "보안", "잠금", "인식"],
    "AS/품질": ["as", "수리", "불량", "파손", "방수", "품질", "내구성", "고장", "센터"],
}

NEG_W = [
    "불편", "문제", "오류", "버그", "느림", "렉", "버벅", "안됨", "이상", "고장",
    "실망", "불만", "최악", "짜증", "끊김", "느려", "불량", "파손", "환불", "스트레스",
]
POS_W = ["좋음", "만족", "개선", "좋아", "빠름", "완벽", "최고", "추천", "편리", "깔끔", "괜찮"]


@dataclass
class VOCItem:
    source: str
    title: str
    content: str
    url: str = ""
    category: str = "기타"
    sentiment: str = "neutral"
    collected_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = {
            "source": self.source,
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "category": self.category,
            "sentiment": self.sentiment,
            "collected_at": self.collected_at,
        }
        if self.extra:
            data["extra"] = self.extra
        return data


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def classify_category(text: str) -> str:
    t = (text or "").lower()
    for cat, kws in CATEGORY_KW.items():
        if any(k.lower() in t for k in kws):
            return cat
    return "기타"


def classify_sentiment(text: str) -> str:
    t = (text or "").lower()
    neg = sum(1 for w in NEG_W if w.lower() in t)
    pos = sum(1 for w in POS_W if w.lower() in t)
    return "negative" if neg > pos else ("positive" if pos > neg else "neutral")


def safe_get(url: str, extra: dict | None = None) -> Optional[BeautifulSoup]:
    """웹 페이지 안전 수집. 실패는 None으로 반환하여 앱 전체 중단을 막는다."""
    try:
        r = requests.get(url, headers={**HEADERS, **(extra or {})}, timeout=TIMEOUT_SEC)
        if r.status_code == 200 and r.text:
            r.encoding = r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None
    return None


def _make(source: str, title: str, content: str, url: str = "", extra: dict | None = None) -> VOCItem:
    title = _clean_text(title)
    content = _clean_text(content or title)
    merged = f"{title} {content}"
    return VOCItem(
        source=source,
        title=title[:220] or "제목 없음",
        content=content[:1200] or title[:1200],
        url=url or "",
        category=classify_category(merged),
        sentiment=classify_sentiment(merged),
        extra=extra or {},
    )


def _domain_label(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "")
        return host or "사용자 URL"
    except Exception:
        return "사용자 URL"


def _extract_page_text(soup: BeautifulSoup, max_chars: int = 5000) -> tuple[str, str]:
    """단일 HTML 페이지에서 title/content 추출."""
    for tag in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.get_text(strip=True):
        title = soup.title.get_text(" ", strip=True)
    if not title:
        h1 = soup.find(["h1", "h2"])
        title = h1.get_text(" ", strip=True) if h1 else "제목 없음"

    meta_desc = ""
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        meta_desc = meta.get("content", "")

    candidates = []
    for selector in ["article", "main", "section", ".content", ".post", ".article", "body"]:
        for node in soup.select(selector)[:3]:
            txt = node.get_text(" ", strip=True)
            if txt and len(txt) > 80:
                candidates.append(txt)
        if candidates:
            break

    content = meta_desc + " " + " ".join(candidates[:2])
    content = _clean_text(content)[:max_chars]
    return title[:220], content


def collect_custom_urls(urls: Iterable[str], max_chars_per_url: int = 5000) -> List[VOCItem]:
    """사용자가 입력한 URL 목록을 VOC 소스로 추가한다."""
    results: list[VOCItem] = []
    seen: set[str] = set()
    for raw in urls:
        url = (raw or "").strip()
        if not url or url.startswith("#"):
            continue
        if not re.match(r"^https?://", url, flags=re.I):
            url = "https://" + url
        if url in seen:
            continue
        seen.add(url)
        soup = safe_get(url)
        if not soup:
            results.append(_make(f"사용자 URL:{_domain_label(url)}", f"수집 실패: {url}", "페이지를 가져오지 못했습니다.", url, {"status": "failed"}))
            continue
        title, content = _extract_page_text(soup, max_chars=max_chars_per_url)
        results.append(_make(f"사용자 URL:{_domain_label(url)}", title, content, url, {"status": "ok"}))
        time.sleep(0.3)
    return deduplicate(results)


# ── 기본 수집 함수 ─────────────────────────────────────────────

def collect_naver_kin(keyword: str, max_items: int = 25) -> List[VOCItem]:
    results: List[VOCItem] = []
    url = f"https://kin.naver.com/search/list.naver?query={requests.utils.quote(keyword)}"
    soup = safe_get(url, {"Referer": "https://kin.naver.com"})
    if not soup:
        return results
    for li in soup.select("ul.basic1 li")[:max_items]:
        a = li.select_one("dt a, .title a")
        if not a:
            continue
        title = a.get_text(strip=True)
        desc = (li.select_one("dd") or li).get_text(" ", strip=True)
        href = a.get("href", "")
        if len(title) < 6:
            continue
        link = href if href.startswith("http") else f"https://kin.naver.com{href}"
        results.append(_make("네이버 지식인", title, desc[:500], link))
    return results


def collect_naver_cafe(keyword: str, max_items: int = 25) -> List[VOCItem]:
    results: List[VOCItem] = []
    url = f"https://search.naver.com/search.naver?where=article&query={requests.utils.quote(keyword)}&nso=so%3Ar%2Cp%3A1w"
    soup = safe_get(url)
    if not soup:
        return results
    for item in soup.select(".cafe_item, li.bx, .api_ani_send")[:max_items]:
        a = item.select_one("a.title, .api_txt_lines, strong a")
        if not a:
            continue
        title = a.get_text(strip=True)
        desc = (item.select_one(".dsc_txt, .desc") or item).get_text(" ", strip=True)
        href = a.get("href", "")
        if len(title) < 6:
            continue
        results.append(_make("네이버 카페", title, desc[:500], href))
    return results


def collect_dcinside(gallery_id: str, gallery_name: str, max_items: int = 20) -> List[VOCItem]:
    results: List[VOCItem] = []
    url = f"https://gall.dcinside.com/board/lists/?id={gallery_id}&page=1"
    soup = safe_get(url)
    if not soup:
        return results
    for tr in soup.select("tr.ub-content")[:max_items]:
        a = tr.select_one(".gall_tit a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if len(title) < 4 or "[공지]" in title:
            continue
        link = href if href.startswith("http") else f"https://gall.dcinside.com{href}"
        results.append(_make(f"DC인사이드 {gallery_name}", title, title, link))
    return results


def collect_clien(keyword: str, max_items: int = 20) -> List[VOCItem]:
    results: List[VOCItem] = []
    url = f"https://www.clien.net/service/search?q={requests.utils.quote(keyword)}&sort=recency&page=0"
    soup = safe_get(url)
    if not soup:
        return results
    for item in soup.select(".list_item, .symph-row")[:max_items]:
        a = item.select_one(".list_subject, a.list_subject")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if len(title) < 6:
            continue
        link = href if href.startswith("http") else f"https://www.clien.net{href}"
        results.append(_make("클리앙", title, title, link))
    return results


def collect_samsung_members(keyword: str, max_items: int = 25) -> List[VOCItem]:
    results: List[VOCItem] = []
    url = f"https://r1.community.samsung.com/t5/forums/searchpage/tab/message?q={requests.utils.quote(keyword)}&include_archived=false"
    soup = safe_get(url)
    if not soup:
        return results
    for el in soup.select(".lia-message-subject a, .MessageSubject a, h3 a")[:max_items]:
        title = el.get_text(strip=True)
        href = el.get("href", "")
        if len(title) < 6:
            continue
        link = href if href.startswith("http") else f"https://r1.community.samsung.com{href}"
        results.append(_make("삼성 Members 커뮤니티", title, title, link))
    return results


def _normalize_keywords(keyword: str | Iterable[str], max_keywords: int = 50) -> list[str]:
    """단일 검색어 또는 여러 검색어를 안전한 리스트로 정규화한다."""
    if isinstance(keyword, str):
        raw_items = re.split(r"[\n,;]+", keyword)
    else:
        raw_items = []
        for item in keyword or []:
            raw_items.extend(re.split(r"[\n,;]+", str(item)))

    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        q = re.sub(r"\s+", " ", (item or "")).strip()
        if not q:
            continue
        q = q[:120]
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= max_keywords:
            break
    return out


def collect_all(
    keyword: str | Iterable[str],
    sources: List[str],
    max_per_source: int = 25,
    on_progress: Optional[Callable] = None,
    custom_urls: Optional[Iterable[str]] = None,
) -> List[VOCItem]:
    """선택된 소스와 사용자 URL에서 VOC 수집.

    keyword는 문자열 1개 또는 여러 검색어 리스트를 모두 받을 수 있다.
    여러 검색어가 들어오면 검색어별로 삼성 Members/네이버/클리앙 수집을 반복하고,
    DC인사이드처럼 키워드 검색이 아닌 게시판 최신글 수집 채널은 한 번만 실행한다.
    """
    keywords = _normalize_keywords(keyword)
    tasks = []

    for q in keywords:
        if "samsung" in sources:
            tasks.append((f"삼성 Members 커뮤니티 · {q}", lambda q=q: collect_samsung_members(q, max_per_source)))
        if "naver_kin" in sources:
            tasks.append((f"네이버 지식인 · {q}", lambda q=q: collect_naver_kin(f"갤럭시 {q} 불편", max_per_source)))
        if "naver_cafe" in sources:
            tasks.append((f"네이버 카페 · {q}", lambda q=q: collect_naver_cafe(f"갤럭시 {q} 문제", max_per_source)))
        if "clien" in sources:
            tasks.append((f"클리앙 · {q}", lambda q=q: collect_clien(q, max_per_source)))

    if "dcinside" in sources:
        tasks.append(("DC인사이드 갤럭시S24", lambda: collect_dcinside("galaxys24", "갤럭시S24", max_per_source)))
        tasks.append(("DC인사이드 삼성갤럭시", lambda: collect_dcinside("samsunggalaxy", "삼성갤럭시", max_per_source)))

    if custom_urls:
        url_list = [u for u in custom_urls if (u or "").strip()]
        if url_list:
            tasks.append(("사용자 URL", lambda: collect_custom_urls(url_list)))

    all_items: List[VOCItem] = []
    for i, (name, fn) in enumerate(tasks):
        if on_progress:
            on_progress(i + 1, len(tasks), name, "수집 중")
        try:
            items = fn()
            all_items.extend(items)
            if on_progress:
                on_progress(i + 1, len(tasks), name, f"완료 ({len(items)}건)")
        except Exception as e:
            if on_progress:
                on_progress(i + 1, len(tasks), name, f"오류: {e}")
        if i < len(tasks) - 1:
            time.sleep(DELAY_SEC)
    return deduplicate(all_items)


def _norm_key(text: str) -> str:
    text = re.sub(r"\s+", "", (text or "").lower())
    text = re.sub(r"[^0-9a-z가-힣]", "", text)
    return text[:100]


def deduplicate(items: List[VOCItem]) -> List[VOCItem]:
    """URL 우선, 없으면 제목+본문 정규화 키로 중복 제거."""
    seen, out = set(), []
    for it in items:
        url_key = (it.url or "").strip().lower()
        title_key = _norm_key(it.title)
        body_key = _norm_key(it.content)[:80]
        raw = url_key or f"{title_key}|{body_key}"
        key = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()
        if key not in seen:
            seen.add(key)
            out.append(it)
    return out


def build_stats(items: List[VOCItem]) -> dict:
    by_cat = Counter(v.category for v in items)
    by_src = Counter(v.source for v in items)
    by_snt = Counter(v.sentiment for v in items)
    total = len(items)
    return {
        "total": total,
        "by_category": dict(by_cat.most_common()),
        "by_source": dict(by_src.most_common()),
        "by_sentiment": dict(by_snt),
        "neg_pct": round(by_snt["negative"] / total * 100) if total else 0,
        "pos_pct": round(by_snt["positive"] / total * 100) if total else 0,
    }


DEMO_RAW = [
    ("삼성 Members 커뮤니티", "배터리/전원", "갤럭시 S25 배터리 소모가 너무 심합니다"),
    ("네이버 지식인", "배터리/전원", "충전 속도가 이전 모델보다 많이 느려졌어요"),
    ("네이버 카페", "배터리/전원", "게임할 때 배터리 소모가 너무 빨라요"),
    ("DC인사이드 갤럭시S24", "배터리/전원", "원UI 업데이트 후 배터리가 더 빨리 닳는 현상"),
    ("클리앙", "배터리/전원", "보조배터리 없으면 하루 못버팀"),
    ("삼성 Members 커뮤니티", "카메라", "야간 카메라 사진이 흐릿하게 나옵니다"),
    ("네이버 지식인", "카메라", "줌 배율이 올라갈수록 화질이 너무 떨어져요"),
    ("네이버 카페", "카메라", "셀피 찍을 때 피부 보정이 너무 과해요"),
    ("DC인사이드 갤럭시S24", "카메라", "카메라 업데이트 후 색감이 이상해짐"),
    ("클리앙", "카메라", "카메라 앱 실행 속도가 느립니다"),
    ("삼성 Members 커뮤니티", "성능/속도", "멀티태스킹 중 앱이 자꾸 종료됩니다"),
    ("네이버 지식인", "성능/속도", "게임하면 발열이 너무 심해요"),
    ("네이버 카페", "성능/속도", "고사양 게임할 때 프레임 드랍이 심함"),
    ("DC인사이드 갤럭시S24", "성능/속도", "업데이트 후 앱 실행 속도가 느려진 것 같아요"),
    ("삼성 Members 커뮤니티", "디스플레이", "화면 잔상이 오래 남습니다"),
    ("네이버 지식인", "디스플레이", "화면 밝기가 자동으로 너무 어두워져요"),
    ("네이버 카페", "디스플레이", "야외에서 화면이 잘 안보임"),
    ("클리앙", "디스플레이", "화면 색상이 이전 기기보다 누런 것 같아요"),
    ("삼성 Members 커뮤니티", "통신/네트워크", "와이파이 연결이 자꾸 끊깁니다"),
    ("네이버 지식인", "통신/네트워크", "5G 잡았다가 LTE로 자꾸 내려가는 현상"),
    ("DC인사이드 갤럭시S24", "통신/네트워크", "블루투스 이어폰이 자꾸 끊겨요"),
    ("클리앙", "통신/네트워크", "GPS 실내에서 너무 부정확해요"),
    ("삼성 Members 커뮤니티", "UI/소프트웨어", "원UI 업데이트 후 자꾸 팝업 광고가 떠요"),
    ("네이버 지식인", "UI/소프트웨어", "빅스비가 실수로 자꾸 켜집니다"),
    ("네이버 카페", "UI/소프트웨어", "기본 앱 삭제가 안됩니다"),
    ("DC인사이드 갤럭시S24", "UI/소프트웨어", "앱 알림이 제대로 안 오는 현상"),
    ("삼성 Members 커뮤니티", "보안/생체인식", "지문인식 인식률이 확실히 떨어졌어요"),
    ("네이버 지식인", "보안/생체인식", "얼굴인식이 어두운 곳에서 작동을 안 해요"),
    ("클리앙", "보안/생체인식", "지문인식 인식이 너무 느림"),
    ("삼성 Members 커뮤니티", "디자인/하드웨어", "폰이 너무 무거워서 손목이 아파요"),
    ("네이버 카페", "디자인/하드웨어", "케이스 끼면 너무 두꺼워짐"),
    ("클리앙", "음향", "스피커 볼륨이 이전 기기보다 작아요"),
    ("삼성 Members 커뮤니티", "AS/품질", "AS 비용이 너무 비쌉니다"),
    ("네이버 지식인", "AS/품질", "방수 성능이 광고보다 낮은 것 같아요"),
    ("클리앙", "카메라", "사진 AI 지우개 기능이 정말 편리해요"),
    ("삼성 Members 커뮤니티", "배터리/전원", "배터리 최적화 업데이트 후 확실히 좋아짐"),
    ("네이버 카페", "성능/속도", "원UI 7 업데이트 후 확실히 빨라진 것 같아요"),
    ("DC인사이드 갤럭시S24", "카메라", "야간 촬영 AI 개선이 정말 마음에 들어요"),
]


def get_demo_voc() -> List[VOCItem]:
    return [
        VOCItem(
            source=src,
            title=title,
            content=title,
            url="#",
            category=cat,
            sentiment=classify_sentiment(title),
        )
        for src, cat, title in DEMO_RAW
    ]
