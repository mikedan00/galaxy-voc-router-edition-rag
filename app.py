"""
app.py — Galaxy VOC Collector Router/RAG Edition

기능
1. 기본 VOC 데모/실시간 수집
2. 사용자 URL 직접 추가 수집
3. CSV/XLSX/TXT/DOCX 업로드 → VOC 변환 + 경량 임베딩 청크 생성
4. TF-IDF 기반 경량 RAG 검색/질의응답
5. Hugging Face Router AI 분석
6. SRS Markdown/DOCX/ZIP 산출

실행:
  streamlit run app.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from html import escape

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from models.config import DEFAULT_ROUTER_CANDIDATES, SUPPORTED_MODELS, clean_value, load_config
from utils.file_ingestor import parse_uploaded_file
from utils.rag_engine import SimpleRAGIndex, build_context, chunks_from_voc
from utils.voc_collector import build_stats, collect_all, collect_custom_urls, deduplicate, get_demo_voc

st.set_page_config(page_title="Galaxy VOC Collector", page_icon="📱", layout="wide")

st.markdown(
    """
<style>
html, body, [class*="css"] {font-family: 'Noto Sans KR', sans-serif;}
.hero {background: linear-gradient(135deg,#07101f,#1428A0); color:white; padding:22px 26px; border-radius:18px; margin-bottom:20px;}
.hero h1 {margin:0; font-size:28px;} .hero p {margin:6px 0 0 0; opacity:.78;}
.badge {display:inline-block; padding:4px 10px; border-radius:999px; background:#eef2ff; color:#1428A0; font-size:12px; font-weight:700; margin-right:4px; margin-bottom:4px;}
.card {border:1px solid #e5e7eb; border-radius:14px; padding:14px; background:#fff; margin-bottom:10px;}
.small {font-size:12px; color:#6b7280;}
.voc {border-bottom:1px solid #eee; padding:9px 0;} .voc-title {font-weight:650;} .voc-meta {font-size:12px; color:#6b7280;}
pre {white-space:pre-wrap;}
</style>
""",
    unsafe_allow_html=True,
)


def mask_token(token: str) -> str:
    token = clean_value(token)
    if not token:
        return "(empty)"
    if len(token) < 12:
        return "*" * len(token)
    return token[:6] + "..." + token[-4:]


def as_dict(item) -> dict:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if isinstance(item, dict):
        return item
    return dict(item)


def chunk_as_dict(item) -> dict:
    if hasattr(item, "to_dict"):
        return item.to_dict()
    return dict(item)


def merge_voc(existing: list, new_items: list) -> list:
    return deduplicate(list(existing or []) + list(new_items or []))


def parse_search_keywords(raw: str, max_keywords: int = 30) -> list[str]:
    """검색어 입력값을 여러 줄/쉼표 단위로 분리하고 중복을 제거한다.

    - 한 줄에 하나씩 입력 가능
    - 한 줄 안에서 쉼표(,) 또는 세미콜론(;)로도 분리 가능
    - 너무 긴 검색어는 외부 검색 URL 오류를 줄이기 위해 120자로 잘라 사용
    """
    import re

    raw = raw or ""
    parts: list[str] = []
    for line in raw.splitlines():
        for part in re.split(r"[,;]+", line):
            q = re.sub(r"\s+", " ", part).strip()
            if q:
                parts.append(q[:120])

    seen: set[str] = set()
    out: list[str] = []
    for q in parts:
        key = q.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(q)
        if len(out) >= max_keywords:
            break
    return out


def build_result_zip(docx_path: str | None, analysis_json: bytes, srs_markdown: bytes, rag_json: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("analysis.json", analysis_json)
        zf.writestr("srs.md", srs_markdown)
        zf.writestr("rag_context.json", rag_json)
        if docx_path and Path(docx_path).exists():
            zf.write(docx_path, arcname=Path(docx_path).name)
    buf.seek(0)
    return buf.getvalue()


def build_all_chunks() -> list:
    voc_chunks = chunks_from_voc(st.session_state.get("voc_list", []))
    uploaded = st.session_state.get("uploaded_chunks", []) or []
    return voc_chunks + uploaded


def run_rag_search(query: str, top_k: int = 8) -> tuple[list[dict], str]:
    all_chunks = build_all_chunks()
    if not all_chunks:
        return [], ""
    index = SimpleRAGIndex(all_chunks)
    hits = index.search(query, top_k=top_k)
    hit_dicts = [h.to_dict() for h in hits]
    context = build_context(hits, max_chars=4500)
    return hit_dicts, context


def render_voc(items: list, limit: int = 150) -> None:
    if not items:
        st.info("VOC가 없습니다. 왼쪽에서 데모/수집/URL/파일 업로드를 실행하세요.")
        return
    for item in items[:limit]:
        d = as_dict(item)
        st.markdown(
            f"""
<div class="voc">
  <div class="voc-title">{escape(d.get('title',''))}</div>
  <div class="voc-meta">{escape(d.get('source',''))} · {escape(d.get('category',''))} · {escape(d.get('sentiment',''))}</div>
  <div class="small">{escape((d.get('content','') or '')[:260])}</div>
</div>
""",
            unsafe_allow_html=True,
        )
    if len(items) > limit:
        st.caption(f"처음 {limit}건만 표시했습니다. 전체 {len(items)}건")


def render_stats(stats: dict) -> None:
    if not stats:
        st.info("통계가 없습니다.")
        return
    c1, c2, c3, c4 = st.columns(4)
    total = max(stats.get("total", 0), 1)
    snt = stats.get("by_sentiment", {})
    c1.metric("총 VOC", stats.get("total", 0))
    c2.metric("부정", f"{snt.get('negative', 0)}건", f"{round(snt.get('negative', 0)/total*100)}%")
    c3.metric("긍정", f"{snt.get('positive', 0)}건", f"{round(snt.get('positive', 0)/total*100)}%")
    c4.metric("수집/업로드 채널", len(stats.get("by_source", {})))

    left, right = st.columns(2)
    with left:
        st.markdown("#### 카테고리별")
        st.dataframe(pd.DataFrame(list(stats.get("by_category", {}).items()), columns=["카테고리", "건수"]), use_container_width=True)
    with right:
        st.markdown("#### 채널별")
        st.dataframe(pd.DataFrame(list(stats.get("by_source", {}).items()), columns=["채널", "건수"]), use_container_width=True)


def ensure_engine_ready() -> bool:
    return bool(st.session_state.get("engine_ready"))


cfg = load_config()

_defaults = {
    "voc_list": [],
    "stats": None,
    "analysis": None,
    "srs_text": "",
    "engine_ready": False,
    "engine_model": "",
    "engine_label": "",
    "engine_msg": "",
    "router_attempts": [],
    "hf_token_val": cfg["hf_token"],
    "hf_router_model": cfg["hf_router_model"],
    "hf_model_candidates_text": "\n".join(cfg["hf_model_candidates"]),
    "max_tokens": cfg["max_tokens"],
    "temperature": cfg["temperature"],
    "last_docx_path": "",
    "custom_url_text": "",
    "search_keywords_text": "갤럭시\n갤럭시 배터리\n갤럭시 카메라\n갤럭시 발열",
    "max_search_keywords": 20,
    "uploaded_chunks": [],
    "upload_logs": [],
    "rag_query": "갤럭시 VOC에서 가장 중요한 불편사항과 요구사항은 무엇인가?",
    "rag_hits": [],
    "rag_context": "",
    "rag_answer": "",
    "use_rag_for_analysis": True,
}
for key, value in _defaults.items():
    st.session_state.setdefault(key, value)

st.markdown(
    """
<div class="hero">
  <h1>Galaxy VOC Collector · Router/RAG Edition</h1>
  <p>VOC 수집 · 사용자 URL 추가 · 파일 업로드 임베딩 · RAG 검색 · HF Router 분석 · SRS 산출</p>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## 1) AI 연결")
    st.caption("노출된 HF 토큰은 반드시 폐기 후 새 토큰을 사용하세요.")

    hf_token = st.text_input("HF_TOKEN", value=st.session_state["hf_token_val"], type="password", placeholder="hf_...")
    st.session_state["hf_token_val"] = clean_value(hf_token)

    model_options = [m.model_id for m in SUPPORTED_MODELS]
    default_model = st.session_state["hf_router_model"] or DEFAULT_ROUTER_CANDIDATES[0]
    if default_model not in model_options:
        model_options = [default_model] + model_options
    selected_model = st.selectbox(
        "기본 Router 모델",
        options=model_options,
        index=model_options.index(default_model) if default_model in model_options else 0,
    )
    st.session_state["hf_router_model"] = selected_model

    with st.expander("Fallback 후보 편집", expanded=False):
        st.session_state["hf_model_candidates_text"] = st.text_area(
            "한 줄에 하나씩 입력",
            value=st.session_state["hf_model_candidates_text"],
            height=170,
        )
        st.session_state["max_tokens"] = st.slider("Max Tokens", 400, 4096, int(st.session_state["max_tokens"]), 100)
        st.session_state["temperature"] = st.slider("Temperature", 0.0, 1.0, float(st.session_state["temperature"]), 0.05)

    if st.button("🔌 HF Router 연결 확인", type="primary", use_container_width=True):
        from models.hf_api_engine import api_engine

        token = clean_value(st.session_state["hf_token_val"])
        os.environ["HF_TOKEN"] = token
        os.environ["HF_ROUTER_MODEL"] = clean_value(st.session_state["hf_router_model"])
        candidates = [x.strip() for x in st.session_state["hf_model_candidates_text"].splitlines() if x.strip()]
        os.environ["HF_MODEL_CANDIDATES"] = ",".join(candidates)

        with st.spinner("Router probe 중..."):
            result = api_engine.setup(
                hf_token=token,
                model_id=os.environ["HF_ROUTER_MODEL"],
                max_tokens=int(st.session_state["max_tokens"]),
                temperature=float(st.session_state["temperature"]),
                auto_fallback=True,
                candidates=candidates,
            )
        st.session_state["engine_ready"] = bool(result["ok"])
        st.session_state["engine_model"] = result.get("model_id", "")
        st.session_state["engine_label"] = result.get("label", "")
        st.session_state["engine_msg"] = result.get("message", "")
        st.session_state["router_attempts"] = result.get("attempts", [])

        if result["ok"]:
            st.success(result["message"])
        else:
            st.error(result["message"])

    if st.session_state["engine_ready"]:
        st.success(f"연결됨: {st.session_state['engine_model']}")
    else:
        st.warning("AI 미연결")

    if st.session_state["router_attempts"]:
        with st.expander("연결 시도 로그", expanded=not st.session_state["engine_ready"]):
            st.dataframe(pd.DataFrame(st.session_state["router_attempts"]), use_container_width=True)

    st.divider()
    st.markdown("## 2) VOC 수집")
    st.caption("검색어는 여러 줄로 입력할 수 있습니다. 한 줄에 하나씩 입력하고, 한 줄 안에서는 쉼표/세미콜론으로도 구분할 수 있습니다.")
    st.session_state["search_keywords_text"] = st.text_area(
        "검색어 목록",
        value=st.session_state["search_keywords_text"],
        height=130,
        placeholder="갤럭시\n갤럭시 배터리 불만\n갤럭시 카메라 오류\n갤럭시 One UI 업데이트",
        help="한 줄에 하나씩 입력하세요. 너무 많은 검색어는 외부 사이트 요청량이 늘어나므로 10~20개 정도를 권장합니다.",
    )
    st.session_state["max_search_keywords"] = st.slider(
        "이번 수집에 사용할 최대 검색어 수",
        1,
        50,
        int(st.session_state["max_search_keywords"]),
        help="입력한 검색어가 이 개수를 넘으면 위에서부터 이 개수까지만 사용합니다.",
    )
    search_keywords = parse_search_keywords(
        st.session_state["search_keywords_text"],
        max_keywords=int(st.session_state["max_search_keywords"]),
    )
    if search_keywords:
        st.caption(f"인식된 검색어 {len(search_keywords)}개: " + ", ".join(search_keywords[:8]) + (" ..." if len(search_keywords) > 8 else ""))
    else:
        st.warning("검색어가 비어 있습니다. 기본 채널 수집을 하려면 검색어를 1개 이상 입력하세요.")
    sources = st.multiselect(
        "기본 수집 채널",
        options=["samsung", "naver_kin", "naver_cafe", "dcinside", "clien"],
        default=["samsung", "naver_kin", "naver_cafe", "dcinside", "clien"],
        format_func=lambda x: {
            "samsung": "삼성 Members",
            "naver_kin": "네이버 지식인",
            "naver_cafe": "네이버 카페",
            "dcinside": "DC인사이드",
            "clien": "클리앙",
        }.get(x, x),
    )
    max_per_source = st.slider("소스당 최대 건수", 5, 80, 25)

    with st.expander("➕ 사용자 URL 추가 수집", expanded=True):
        st.session_state["custom_url_text"] = st.text_area(
            "URL을 한 줄에 하나씩 입력",
            value=st.session_state["custom_url_text"],
            height=110,
            placeholder="https://example.com/review-page\nhttps://community.example.com/post/123",
        )
        include_urls = st.checkbox("실제 수집 버튼 실행 시 위 URL도 함께 수집", value=True)
        if st.button("🌐 URL만 수집해서 현재 VOC에 추가", use_container_width=True):
            url_list = [u.strip() for u in st.session_state["custom_url_text"].splitlines() if u.strip()]
            with st.spinner("사용자 URL 수집 중..."):
                custom_items = collect_custom_urls(url_list)
            st.session_state["voc_list"] = merge_voc(st.session_state["voc_list"], custom_items)
            st.session_state["stats"] = build_stats(st.session_state["voc_list"])
            st.session_state["analysis"] = None
            st.session_state["srs_text"] = ""
            st.success(f"URL VOC {len(custom_items)}건 추가")
            st.rerun()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🧪 데모 VOC", use_container_width=True):
            demo = get_demo_voc()
            st.session_state["voc_list"] = demo
            st.session_state["stats"] = build_stats(demo)
            st.session_state["analysis"] = None
            st.session_state["srs_text"] = ""
            st.success(f"데모 {len(demo)}건 로드")
            st.rerun()
    with c2:
        if st.button("🔍 실제 수집", type="primary", use_container_width=True):
            if sources and not search_keywords:
                st.error("기본 채널 수집을 하려면 검색어를 1개 이상 입력하세요.")
            elif not sources and not (include_urls and st.session_state["custom_url_text"].strip()):
                st.error("수집 채널 또는 사용자 URL을 입력하세요.")
            else:
                pb = st.progress(0, text="수집 준비")
                info = st.empty()

                def on_progress(step, total, name, status):
                    pb.progress(step / max(total, 1), text=f"[{step}/{total}] {name}")
                    info.caption(f"{name}: {status}")

                custom_urls = [u.strip() for u in st.session_state["custom_url_text"].splitlines() if u.strip()] if include_urls else []
                with st.spinner("VOC 수집 중..."):
                    items = collect_all(search_keywords, sources, max_per_source, on_progress, custom_urls=custom_urls)
                st.session_state["voc_list"] = items
                st.session_state["stats"] = build_stats(items)
                st.session_state["analysis"] = None
                st.session_state["srs_text"] = ""
                st.success(f"수집 완료: {len(items)}건")
                st.rerun()

    if st.button("🧹 현재 VOC/RAG 결과 초기화", use_container_width=True):
        st.session_state["voc_list"] = []
        st.session_state["stats"] = None
        st.session_state["analysis"] = None
        st.session_state["srs_text"] = ""
        st.session_state["rag_hits"] = []
        st.session_state["rag_context"] = ""
        st.session_state["rag_answer"] = ""
        st.success("초기화 완료")
        st.rerun()

    st.divider()
    st.markdown("## 3) 분석/명세서")
    product_target = st.text_input("분석 대상 제품", value="갤럭시 S25 시리즈")
    product_name = st.text_input("문서 제품명", value="삼성 갤럭시")
    doc_version = st.text_input("문서 버전", value="1.0")
    doc_author = st.text_input("작성자", value="제품기획팀")
    st.session_state["use_rag_for_analysis"] = st.checkbox(
        "AI 분석/SRS에 RAG 근거 자동 포함",
        value=bool(st.session_state["use_rag_for_analysis"]),
        help="VOC와 업로드 파일 청크에서 관련 근거를 검색해 프롬프트에 추가합니다.",
    )

    if st.button("🤖 VOC AI 분석", type="primary", use_container_width=True, disabled=not (st.session_state["voc_list"] and ensure_engine_ready())):
        from models.hf_api_engine import analyze_voc_api

        rag_context = ""
        if st.session_state["use_rag_for_analysis"]:
            query = f"{product_target} 주요 불편사항 요구사항 개선 KPI 성능 배터리 카메라 업데이트"
            hits, rag_context = run_rag_search(query, top_k=10)
            st.session_state["rag_hits"] = hits
            st.session_state["rag_context"] = rag_context
        with st.spinner("VOC 분석 중..."):
            analysis = analyze_voc_api(st.session_state["voc_list"], product_target, rag_context=rag_context)
        st.session_state["analysis"] = analysis
        st.success("분석 완료")
        st.rerun()

    if st.button("📝 SRS Markdown 생성", type="primary", use_container_width=True, disabled=not (st.session_state["analysis"] and ensure_engine_ready())):
        from models.hf_api_engine import api_engine, build_srs_prompt

        rag_context = st.session_state.get("rag_context", "")
        if st.session_state["use_rag_for_analysis"] and not rag_context:
            _, rag_context = run_rag_search(f"{product_target} 요구사항 수용기준 KPI 리스크", top_k=10)
            st.session_state["rag_context"] = rag_context
        prompt = build_srs_prompt(
            st.session_state["voc_list"],
            st.session_state["analysis"],
            product_name,
            doc_version,
            doc_author,
            rag_context=rag_context,
        )
        placeholder = st.empty()
        full = ""
        with st.spinner("SRS 생성 중..."):
            for chunk in api_engine.generate_stream(prompt, max_tokens=3600, temperature=0.15):
                full += chunk
                placeholder.caption(f"생성 중... {len(full):,}자")
        st.session_state["srs_text"] = full
        placeholder.empty()
        st.success("SRS 생성 완료")
        st.rerun()

    if st.button("📄 DOCX 생성", use_container_width=True, disabled=not st.session_state["voc_list"]):
        from utils.doc_generator import generate_docx

        with st.spinner("DOCX 생성 중..."):
            path = generate_docx(
                st.session_state["voc_list"],
                st.session_state["analysis"] or {},
                st.session_state["srs_text"],
                product_name=product_name,
                version=doc_version,
                author=doc_author,
                output_dir=str(ROOT / "output"),
                model_label=st.session_state.get("engine_model", "HF Router"),
            )
        st.session_state["last_docx_path"] = path
        st.success(f"DOCX 생성 완료: {Path(path).name}")

st.markdown(
    f"""
<div class="card">
<span class="badge">TOKEN {mask_token(st.session_state.get('hf_token_val',''))}</span>
<span class="badge">MODEL {escape(st.session_state.get('engine_model') or st.session_state.get('hf_router_model',''))}</span>
<span class="badge">VOC {len(st.session_state['voc_list'])}건</span>
<span class="badge">RAG CHUNKS {len(build_all_chunks())}개</span>
</div>
""",
    unsafe_allow_html=True,
)

main_tab, upload_tab, rag_tab, stats_tab, analysis_tab, srs_tab, export_tab = st.tabs(
    ["📥 VOC", "📎 파일 업로드", "🔎 RAG", "📊 통계", "🤖 분석", "📋 SRS", "📦 내보내기"]
)

with main_tab:
    st.markdown("### 수집/업로드 VOC")
    render_voc(st.session_state["voc_list"])

with upload_tab:
    st.markdown("### VOC 파일 업로드 + 임베딩 적용")
    st.caption("지원 형식: CSV, XLSX/XLSM, TXT, DOCX. 구형 .xls/.doc는 Streamlit Cloud 안정성을 위해 제외했습니다.")
    uploaded_files = st.file_uploader(
        "VOC 파일을 업로드하세요",
        type=["csv", "xlsx", "xlsm", "txt", "docx"],
        accept_multiple_files=True,
    )
    max_rows = st.slider("표 파일 최대 처리 행 수", 50, 3000, 500, 50)
    c_up1, c_up2 = st.columns(2)
    with c_up1:
        if st.button("📎 업로드 파일 처리/현재 VOC에 추가", type="primary", disabled=not uploaded_files, use_container_width=True):
            logs = []
            added_items = []
            added_chunks = []
            with st.spinner("파일 파싱 및 청킹 중..."):
                for uf in uploaded_files:
                    try:
                        items, chunks, msg = parse_uploaded_file(uf, max_rows=max_rows)
                        added_items.extend(items)
                        added_chunks.extend(chunks)
                        logs.append({"file": uf.name, "status": "ok", "message": msg, "voc_items": len(items), "chunks": len(chunks)})
                    except Exception as exc:
                        logs.append({"file": uf.name, "status": "error", "message": str(exc), "voc_items": 0, "chunks": 0})
            st.session_state["voc_list"] = merge_voc(st.session_state["voc_list"], added_items)
            st.session_state["uploaded_chunks"] = (st.session_state.get("uploaded_chunks", []) or []) + added_chunks
            st.session_state["upload_logs"] = logs
            st.session_state["stats"] = build_stats(st.session_state["voc_list"])
            st.session_state["analysis"] = None
            st.session_state["srs_text"] = ""
            st.success(f"파일 VOC {len(added_items)}건, RAG 청크 {len(added_chunks)}개 추가")
            st.rerun()
    with c_up2:
        if st.button("🧽 업로드 청크만 초기화", use_container_width=True):
            st.session_state["uploaded_chunks"] = []
            st.session_state["upload_logs"] = []
            st.session_state["rag_hits"] = []
            st.session_state["rag_context"] = ""
            st.session_state["rag_answer"] = ""
            st.success("업로드 청크 초기화 완료")
            st.rerun()

    if st.session_state.get("upload_logs"):
        st.markdown("#### 처리 로그")
        st.dataframe(pd.DataFrame(st.session_state["upload_logs"]), use_container_width=True)

    st.markdown("#### 업로드/RAG 청크 미리보기")
    chunks = st.session_state.get("uploaded_chunks", [])
    if chunks:
        preview = [chunk_as_dict(c) for c in chunks[:100]]
        st.dataframe(pd.DataFrame(preview), use_container_width=True)
    else:
        st.info("아직 업로드 청크가 없습니다.")

with rag_tab:
    st.markdown("### RAG 검색 및 질의응답")
    st.caption("현재 VOC와 업로드 파일 청크를 합쳐 경량 TF-IDF 임베딩 인덱스를 만들고 관련 근거를 검색합니다.")
    all_chunks = build_all_chunks()
    c_r1, c_r2, c_r3 = st.columns(3)
    c_r1.metric("전체 RAG 청크", len(all_chunks))
    c_r2.metric("VOC 기반 청크", len(st.session_state.get("voc_list", [])))
    c_r3.metric("업로드 청크", len(st.session_state.get("uploaded_chunks", []) or []))

    st.session_state["rag_query"] = st.text_area(
        "검색/질문",
        value=st.session_state["rag_query"],
        height=90,
        placeholder="예: 배터리 불만과 관련된 개선 요구사항을 찾아줘",
    )
    top_k = st.slider("검색 결과 수", 3, 20, 8)
    c_search, c_answer = st.columns(2)
    with c_search:
        if st.button("🔎 RAG 근거 검색", type="primary", disabled=not all_chunks, use_container_width=True):
            hits, context = run_rag_search(st.session_state["rag_query"], top_k=top_k)
            st.session_state["rag_hits"] = hits
            st.session_state["rag_context"] = context
            st.success(f"근거 {len(hits)}건 검색 완료")
            st.rerun()
    with c_answer:
        if st.button("💬 RAG 기반 답변 생성", disabled=not (all_chunks and ensure_engine_ready()), use_container_width=True):
            from models.hf_api_engine import api_engine

            hits, context = run_rag_search(st.session_state["rag_query"], top_k=top_k)
            st.session_state["rag_hits"] = hits
            st.session_state["rag_context"] = context
            prompt = f"""
아래 RAG 근거만 사용해서 사용자의 질문에 답변하세요.
불확실한 내용은 추정이라고 표시하세요.
답변은 한국어로, 제품기획/요구사항 관점에서 작성하세요.

[질문]
{st.session_state['rag_query']}

[RAG 근거]
{context or '검색된 근거 없음'}

[답변 형식]
1. 핵심 답변
2. 근거 요약
3. 요구사항/개선안
4. 확인 필요 사항
"""
            with st.spinner("RAG 답변 생성 중..."):
                st.session_state["rag_answer"] = api_engine.generate(prompt, max_tokens=1800, temperature=0.15)
            st.success("답변 생성 완료")
            st.rerun()

    if st.session_state.get("rag_hits"):
        st.markdown("#### 검색된 근거")
        st.dataframe(pd.DataFrame(st.session_state["rag_hits"]), use_container_width=True)
        with st.expander("LLM에 전달될 RAG Context", expanded=False):
            st.text_area("RAG Context", value=st.session_state.get("rag_context", ""), height=280)
    else:
        st.info("검색 결과가 없습니다. VOC/파일을 먼저 추가한 뒤 RAG 검색을 실행하세요.")

    if st.session_state.get("rag_answer"):
        st.markdown("#### RAG 기반 답변")
        st.markdown(st.session_state["rag_answer"])

with stats_tab:
    st.markdown("### 통계")
    render_stats(st.session_state["stats"] or build_stats(st.session_state["voc_list"]) if st.session_state["voc_list"] else {})

with analysis_tab:
    st.markdown("### AI 분석 결과")
    analysis = st.session_state.get("analysis")
    if not analysis:
        st.info("왼쪽에서 VOC AI 분석을 실행하세요.")
    else:
        if analysis.get("executive_summary"):
            st.markdown("#### 종합 요약")
            st.info(analysis["executive_summary"])
        for title, key in [
            ("문제 진술", "problem_statements"),
            ("핵심 이슈", "critical_issues"),
            ("기능 요구사항", "requirements"),
            ("비기능 요구사항", "non_functional_requirements"),
            ("로드맵", "roadmap"),
            ("KPI", "kpis"),
        ]:
            if analysis.get(key):
                st.markdown(f"#### {title}")
                st.dataframe(pd.DataFrame(analysis[key]), use_container_width=True)
        if analysis.get("key_insights"):
            st.markdown("#### 인사이트")
            for x in analysis["key_insights"]:
                st.write("-", x)

with srs_tab:
    st.markdown("### 요구사항명세서 Markdown")
    srs = st.session_state.get("srs_text", "")
    if not srs:
        st.info("왼쪽에서 SRS Markdown 생성을 실행하세요.")
    else:
        st.download_button("⬇️ SRS Markdown 다운로드", srs.encode("utf-8"), file_name="srs.md", mime="text/markdown")
        st.markdown(srs)

with export_tab:
    st.markdown("### 산출물 다운로드")
    rag_data = {
        "query": st.session_state.get("rag_query", ""),
        "hits": st.session_state.get("rag_hits", []),
        "context": st.session_state.get("rag_context", ""),
        "answer": st.session_state.get("rag_answer", ""),
        "uploaded_chunks_count": len(st.session_state.get("uploaded_chunks", []) or []),
    }
    data = {
        "metadata": {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "engine_model": st.session_state.get("engine_model", ""),
            "total_voc": len(st.session_state["voc_list"]),
            "rag_chunks": len(build_all_chunks()),
        },
        "voc_list": [as_dict(v) for v in st.session_state["voc_list"]],
        "stats": st.session_state.get("stats") or build_stats(st.session_state["voc_list"]) if st.session_state["voc_list"] else {},
        "analysis": st.session_state.get("analysis"),
        "srs_text": st.session_state.get("srs_text", ""),
        "rag": rag_data,
        "upload_logs": st.session_state.get("upload_logs", []),
    }
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    rag_bytes = json.dumps(rag_data, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button("⬇️ analysis.json 다운로드", json_bytes, file_name="analysis.json", mime="application/json")
    st.download_button("⬇️ rag_context.json 다운로드", rag_bytes, file_name="rag_context.json", mime="application/json")

    docx_path = st.session_state.get("last_docx_path") or ""
    if docx_path and Path(docx_path).exists():
        st.download_button(
            "⬇️ DOCX 다운로드",
            Path(docx_path).read_bytes(),
            file_name=Path(docx_path).name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    else:
        st.caption("DOCX 생성 버튼을 먼저 누르면 DOCX 다운로드가 표시됩니다.")

    bundle = build_result_zip(docx_path if docx_path else None, json_bytes, st.session_state.get("srs_text", "").encode("utf-8"), rag_bytes)
    st.download_button("⬇️ 결과 ZIP 다운로드", bundle, file_name=f"galaxy_voc_result_{time.strftime('%Y%m%d_%H%M%S')}.zip", mime="application/zip")
