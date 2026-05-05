"""
utils/doc_generator.py

VOC 분석 결과와 SRS Markdown을 DOCX로 저장한다.
Streamlit Cloud 배포 안정성을 위해 python-docx/lxml 없이 표준 라이브러리(zipfile/XML)로
최소 DOCX 파일을 생성한다.
"""

from __future__ import annotations

import html
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Iterable


def _get(obj, key: str, default=""):
    if hasattr(obj, "to_dict"):
        return obj.to_dict().get(key, default)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plain_lines(markdown: str) -> list[str]:
    lines = []
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", line)
        lines.append(line)
    return lines


def _p(text: str = "") -> str:
    text = html.escape(str(text or ""))
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _heading(text: str, level: int = 1) -> str:
    size = 32 if level == 1 else 26 if level == 2 else 22
    text = html.escape(str(text or ""))
    return (
        f"<w:p><w:pPr><w:spacing w:after=\"160\"/></w:pPr>"
        f"<w:r><w:rPr><w:b/><w:sz w:val=\"{size}\"/></w:rPr>"
        f"<w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"
    )


def _bullet(text: str) -> str:
    text = html.escape(str(text or ""))
    return f"<w:p><w:r><w:t xml:space=\"preserve\">• {text}</w:t></w:r></w:p>"


def _document_xml(lines: list[str]) -> str:
    body = "\n".join(lines)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    {body}
    <w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
  </w:body>
</w:document>'''


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>'''
    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
    core = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Galaxy VOC SRS</dc:title>
  <dc:creator>Galaxy VOC Collector</dc:creator>
  <dcterms:created xsi:type="dcterms:W3CDTF">{time.strftime('%Y-%m-%dT%H:%M:%SZ')}</dcterms:created>
</cp:coreProperties>'''
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("docProps/core.xml", core)
        zf.writestr("word/document.xml", _document_xml(paragraphs))


def generate_docx(
    voc_items: Iterable,
    analysis: dict,
    srs_text: str,
    product_name: str = "삼성 갤럭시",
    version: str = "1.0",
    author: str = "제품기획팀",
    output_dir: str = "output",
    model_label: str = "HF Router",
) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{product_name.replace(' ', '_')}_VOC_SRS_v{version}_{time.strftime('%Y%m%d_%H%M%S')}.docx"

    paragraphs: list[str] = []
    paragraphs.append(_heading(f"{product_name} VOC 기반 요구사항명세서", 1))
    paragraphs.append(_p(f"버전: v{version}"))
    paragraphs.append(_p(f"작성자: {author}"))
    paragraphs.append(_p(f"생성일: {time.strftime('%Y-%m-%d %H:%M:%S')}"))
    paragraphs.append(_p(f"AI 모델: {model_label}"))
    paragraphs.append(_p(""))

    paragraphs.append(_heading("1. Executive Summary", 2))
    paragraphs.append(_p(analysis.get("executive_summary", "분석 요약 없음") if isinstance(analysis, dict) else "분석 요약 없음"))

    if isinstance(analysis, dict):
        for title, key in [
            ("2. 문제 진술", "problem_statements"),
            ("3. 핵심 이슈", "critical_issues"),
            ("4. 기능 요구사항", "requirements"),
            ("5. 비기능 요구사항", "non_functional_requirements"),
            ("6. KPI", "kpis"),
            ("7. 로드맵", "roadmap"),
        ]:
            values = analysis.get(key) or []
            if values:
                paragraphs.append(_heading(title, 2))
                for item in values:
                    if isinstance(item, dict):
                        paragraphs.append(_bullet(json.dumps(item, ensure_ascii=False)))
                    else:
                        paragraphs.append(_bullet(str(item)))

    paragraphs.append(_heading("8. VOC 샘플", 2))
    for i, item in enumerate(list(voc_items)[:80], start=1):
        title = _get(item, "title", "")
        src = _get(item, "source", "")
        cat = _get(item, "category", "")
        snt = _get(item, "sentiment", "")
        paragraphs.append(_bullet(f"[{i}] {title} / {src} / {cat} / {snt}"))

    if srs_text:
        paragraphs.append(_heading("9. SRS Markdown 본문", 2))
        for line in _plain_lines(srs_text):
            if line.startswith("- "):
                paragraphs.append(_bullet(line[2:]))
            elif line:
                paragraphs.append(_p(line))
            else:
                paragraphs.append(_p(""))

    _write_docx(path, paragraphs)
    return str(path)
