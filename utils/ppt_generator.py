"""
utils/ppt_generator.py

VOC 분석 결과를 PowerPoint(.pptx)로 저장한다.
Streamlit Cloud 배포 안정성을 위해 python-pptx/lxml 없이 표준 라이브러리(zipfile/XML)만 사용한다.
"""

from __future__ import annotations

import html
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Iterable, Any

SLIDE_W = 13_333_500  # 13.333in * 914400, 16:9
SLIDE_H = 7_500_000   # 7.5in * 914400


def _get(obj: Any, key: str, default=""):
    if hasattr(obj, "to_dict"):
        return obj.to_dict().get(key, default)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _clean(text: Any, max_len: int = 900) -> str:
    text = str(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + ("..." if len(text) > max_len else "")


def _list_text(values: Any, limit: int = 6, max_each: int = 120) -> list[str]:
    if not values:
        return []
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        values = [values]
    out: list[str] = []
    for item in values[:limit]:
        if isinstance(item, dict):
            # 요구사항/이슈류 dict를 사람이 읽기 쉬운 한 줄로 압축
            title = item.get("title") or item.get("name") or item.get("requirement") or item.get("issue") or ""
            desc = item.get("description") or item.get("summary") or item.get("metric") or item.get("priority") or ""
            line = f"{title} - {desc}" if title and desc else json.dumps(item, ensure_ascii=False)
        else:
            line = str(item)
        out.append(_clean(line, max_each))
    return out


def _p_run(text: str, font_size: int = 20, bold: bool = False, color: str = "1F2937") -> str:
    bold_xml = '<a:b/>' if bold else ''
    return (
        f'<a:r><a:rPr lang="ko-KR" sz="{font_size*100}" dirty="0">{bold_xml}'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        f'<a:latin typeface="Aptos"/><a:ea typeface="Malgun Gothic"/></a:rPr>'
        f'<a:t>{_esc(text)}</a:t></a:r>'
    )


def _paragraph(text: str, font_size: int = 20, bold: bool = False, color: str = "1F2937") -> str:
    return f'<a:p>{_p_run(text, font_size, bold, color)}<a:endParaRPr lang="ko-KR"/></a:p>'


def _bullet_paragraph(text: str, font_size: int = 18, color: str = "374151") -> str:
    return (
        '<a:p><a:pPr marL="285750" indent="-171450"><a:buChar char="•"/></a:pPr>'
        f'{_p_run(text, font_size, False, color)}<a:endParaRPr lang="ko-KR"/></a:p>'
    )


def _textbox(shape_id: int, x: int, y: int, w: int, h: int, paragraphs: list[str], fill: str | None = None, line: str | None = None) -> str:
    fill_xml = '<a:noFill/>' if not fill else f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>'
    line_xml = '<a:ln><a:noFill/></a:ln>' if not line else f'<a:ln w="9525"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
    return f'''
<p:sp>
  <p:nvSpPr><p:cNvPr id="{shape_id}" name="TextBox {shape_id}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>
  <p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{fill_xml}{line_xml}</p:spPr>
  <p:txBody><a:bodyPr wrap="square" lIns="91440" tIns="91440" rIns="91440" bIns="91440"/><a:lstStyle/>{''.join(paragraphs)}</p:txBody>
</p:sp>'''


def _title_slide(title: str, subtitle: str, meta: str) -> str:
    shapes = [
        _textbox(2, 650000, 900000, 12_000_000, 1_300_000, [_paragraph(title, 36, True, "FFFFFF")], fill="1428A0", line="1428A0"),
        _textbox(3, 900000, 2_450_000, 10_800_000, 1_000_000, [_paragraph(subtitle, 23, False, "1F2937")]),
        _textbox(4, 900000, 5_950_000, 10_800_000, 500000, [_paragraph(meta, 14, False, "6B7280")]),
    ]
    return _slide_xml(shapes)


def _content_slide(title: str, left_title: str, left_items: list[str], right_title: str = "", right_items: list[str] | None = None, footer: str = "") -> str:
    right_items = right_items or []
    shapes = [
        _textbox(2, 550000, 330000, 12_200_000, 650000, [_paragraph(title, 28, True, "1428A0")]),
        _textbox(3, 700000, 1_250_000, 5_800_000, 4_850_000, [_paragraph(left_title, 20, True, "111827")] + [_bullet_paragraph(x) for x in left_items], fill="F8FAFC", line="E5E7EB"),
        _textbox(4, 6_850_000, 1_250_000, 5_800_000, 4_850_000, [_paragraph(right_title, 20, True, "111827")] + [_bullet_paragraph(x) for x in right_items], fill="FFFFFF", line="E5E7EB"),
    ]
    if footer:
        shapes.append(_textbox(5, 700000, 6_450_000, 11_800_000, 350000, [_paragraph(footer, 12, False, "6B7280")]))
    return _slide_xml(shapes)


def _metrics_slide(stats: dict, analysis: dict, rag_data: dict | None = None) -> str:
    total = stats.get("total", 0) if isinstance(stats, dict) else 0
    by_sentiment = stats.get("by_sentiment", {}) if isinstance(stats, dict) else {}
    by_category = stats.get("by_category", {}) if isinstance(stats, dict) else {}
    by_source = stats.get("by_source", {}) if isinstance(stats, dict) else {}
    top_cats = sorted(by_category.items(), key=lambda x: x[1], reverse=True)[:5]
    top_sources = sorted(by_source.items(), key=lambda x: x[1], reverse=True)[:5]
    metrics = [
        f"총 VOC: {total}건",
        f"부정 VOC: {by_sentiment.get('negative', 0)}건",
        f"긍정 VOC: {by_sentiment.get('positive', 0)}건",
        f"RAG 청크: {(rag_data or {}).get('uploaded_chunks_count', 0)}개",
    ]
    cats = [f"{k}: {v}건" for k, v in top_cats] or ["카테고리 통계 없음"]
    sources = [f"{k}: {v}건" for k, v in top_sources] or ["채널 통계 없음"]
    return _content_slide("VOC 분석 대시보드", "핵심 지표", metrics + cats[:2], "주요 채널/카테고리", sources + cats, footer="자동 생성된 요약 슬라이드입니다.")


def _sample_slide(voc_items: Iterable) -> str:
    samples = []
    for i, item in enumerate(list(voc_items)[:8], start=1):
        title = _clean(_get(item, "title", ""), 100)
        source = _get(item, "source", "")
        cat = _get(item, "category", "")
        samples.append(f"{i}. {title} ({source}/{cat})")
    if not samples:
        samples = ["VOC 샘플 없음"]
    return _content_slide("대표 VOC 샘플", "VOC 예시", samples[:4], "추가 샘플", samples[4:8], footer="원본 VOC는 analysis.json에서 확인할 수 있습니다.")


def _rag_slide(rag_data: dict | None) -> str:
    rag_data = rag_data or {}
    hits = rag_data.get("hits") or []
    answer = _clean(rag_data.get("answer", ""), 500)
    hit_lines = []
    for h in hits[:6]:
        if isinstance(h, dict):
            hit_lines.append(_clean(h.get("text") or h.get("content") or h.get("title") or json.dumps(h, ensure_ascii=False), 120))
        else:
            hit_lines.append(_clean(h, 120))
    return _content_slide("RAG 근거 및 답변", "검색된 근거", hit_lines or ["검색된 RAG 근거 없음"], "RAG 답변 요약", [answer or "RAG 답변 없음"], footer="RAG 답변은 검색된 근거 기반으로 생성됩니다.")


def _slide_xml(shapes: list[str]) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
      {''.join(shapes)}
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>'''


def _presentation_xml(slide_count: int) -> str:
    sld_ids = "\n".join([f'<p:sldId id="{255+i}" r:id="rId{i}"/>' for i in range(1, slide_count + 1)])
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{slide_count+1}"/></p:sldMasterIdLst>
  <p:sldIdLst>{sld_ids}</p:sldIdLst>
  <p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}" type="screen16x9"/>
  <p:notesSz cx="6858000" cy="9144000"/>
  <p:defaultTextStyle><a:defPPr><a:defRPr lang="ko-KR"/></a:defPPr></p:defaultTextStyle>
</p:presentation>'''


def _presentation_rels(slide_count: int) -> str:
    rels = [f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i}.xml"/>' for i in range(1, slide_count + 1)]
    rels.append(f'<Relationship Id="rId{slide_count+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>')
    rels.append(f'<Relationship Id="rId{slide_count+2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>')
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{''.join(rels)}</Relationships>'''


def _slide_rels() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>'''


def _content_types(slide_count: int) -> str:
    overrides = [
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>',
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>',
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>',
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    overrides += [f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>' for i in range(1, slide_count + 1)]
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  {''.join(overrides)}
</Types>'''


def _root_rels() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''


def _core(title: str) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{_esc(title)}</dc:title><dc:creator>Galaxy VOC Collector</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">{time.strftime('%Y-%m-%dT%H:%M:%SZ')}</dcterms:created>
</cp:coreProperties>'''


def _app(slide_count: int) -> str:
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Galaxy VOC Collector</Application><PresentationFormat>On-screen Show (16:9)</PresentationFormat><Slides>{slide_count}</Slides>
</Properties>'''


def _theme() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Galaxy VOC Theme">
  <a:themeElements>
    <a:clrScheme name="Galaxy"><a:dk1><a:srgbClr val="111827"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="1428A0"/></a:dk2><a:lt2><a:srgbClr val="F8FAFC"/></a:lt2><a:accent1><a:srgbClr val="1428A0"/></a:accent1><a:accent2><a:srgbClr val="00AEEF"/></a:accent2><a:accent3><a:srgbClr val="6B7280"/></a:accent3><a:accent4><a:srgbClr val="10B981"/></a:accent4><a:accent5><a:srgbClr val="F59E0B"/></a:accent5><a:accent6><a:srgbClr val="EF4444"/></a:accent6><a:hlink><a:srgbClr val="1428A0"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink></a:clrScheme>
    <a:fontScheme name="Galaxy Font"><a:majorFont><a:latin typeface="Aptos"/><a:ea typeface="Malgun Gothic"/></a:majorFont><a:minorFont><a:latin typeface="Aptos"/><a:ea typeface="Malgun Gothic"/></a:minorFont></a:fontScheme>
    <a:fmtScheme name="Galaxy Format"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
  </a:themeElements>
</a:theme>'''


def _slide_master() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>'''


def _slide_master_rels() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>'''


def _slide_layout() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
  <p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>'''


def _slide_layout_rels() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>'''


def build_pptx_slides(voc_items: Iterable, analysis: dict | None, srs_text: str = "", stats: dict | None = None, rag_data: dict | None = None, product_name: str = "삼성 갤럭시", version: str = "1.0", author: str = "제품기획팀", model_label: str = "HF Router") -> list[str]:
    analysis = analysis or {}
    stats = stats or {}
    meta = f"v{version} · {author} · {time.strftime('%Y-%m-%d')} · {model_label}"
    slides = [
        _title_slide(f"{product_name} VOC 분석 보고서", "VOC 수집, RAG 근거, AI 분석 기반 제품 요구사항 요약", meta),
        _metrics_slide(stats, analysis, rag_data),
        _content_slide("Executive Summary", "핵심 요약", [_clean(analysis.get("executive_summary", "분석 요약 없음"), 500)], "주요 인사이트", _list_text(analysis.get("key_insights"), 6, 130)),
        _content_slide("핵심 이슈와 문제 진술", "문제 진술", _list_text(analysis.get("problem_statements"), 6, 130), "Critical Issues", _list_text(analysis.get("critical_issues"), 6, 130)),
        _content_slide("기능 요구사항", "Functional Requirements", _list_text(analysis.get("requirements"), 7, 140), "수용 기준/메트릭 관점", ["VOC 근거와 연결된 요구사항을 우선순위화", "요구사항별 KPI/Acceptance Criteria 정의", "Quick Win과 장기 개선 로드맵 분리"]),
        _content_slide("비기능 요구사항과 KPI", "Non-functional Requirements", _list_text(analysis.get("non_functional_requirements"), 6, 130), "KPI", _list_text(analysis.get("kpis"), 6, 130)),
        _content_slide("개선 로드맵", "Roadmap", _list_text(analysis.get("roadmap"), 7, 145), "운영 제안", ["상위 VOC 테마 월간 추적", "불만 급증 키워드 알림", "릴리즈 전/후 VOC 비교", "RAG 근거 기반 요구사항 리뷰"]),
        _rag_slide(rag_data),
        _sample_slide(voc_items),
    ]
    if srs_text:
        srs_lines = [x.strip("- #") for x in srs_text.splitlines() if x.strip()][:10]
        slides.append(_content_slide("SRS 본문 요약", "SRS 주요 항목", [_clean(x, 130) for x in srs_lines[:5]], "추가 항목", [_clean(x, 130) for x in srs_lines[5:10]]))
    return slides


def generate_pptx(voc_items: Iterable, analysis: dict | None, srs_text: str = "", stats: dict | None = None, rag_data: dict | None = None, product_name: str = "삼성 갤럭시", version: str = "1.0", author: str = "제품기획팀", output_dir: str = "output", model_label: str = "HF Router") -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe_product = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", product_name).strip("_") or "Galaxy"
    path = out / f"{safe_product}_VOC_Report_v{version}_{time.strftime('%Y%m%d_%H%M%S')}.pptx"

    slides = build_pptx_slides(voc_items, analysis, srs_text, stats, rag_data, product_name, version, author, model_label)
    n = len(slides)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types(n))
        zf.writestr("_rels/.rels", _root_rels())
        zf.writestr("docProps/core.xml", _core(f"{product_name} VOC 분석 보고서"))
        zf.writestr("docProps/app.xml", _app(n))
        zf.writestr("ppt/presentation.xml", _presentation_xml(n))
        zf.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(n))
        zf.writestr("ppt/theme/theme1.xml", _theme())
        zf.writestr("ppt/slideMasters/slideMaster1.xml", _slide_master())
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _slide_master_rels())
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", _slide_layout())
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _slide_layout_rels())
        for idx, slide_xml in enumerate(slides, start=1):
            zf.writestr(f"ppt/slides/slide{idx}.xml", slide_xml)
            zf.writestr(f"ppt/slides/_rels/slide{idx}.xml.rels", _slide_rels())

    return str(path)
