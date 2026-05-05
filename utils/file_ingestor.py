"""
utils/file_ingestor.py

업로드된 VOC 파일을 읽어 텍스트 청크와 VOCItem으로 변환한다.
지원 형식: CSV, TXT, DOCX, XLSX
- 구형 .doc, .xls는 Streamlit Cloud 안정성을 위해 기본 지원하지 않는다.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable, List

import pandas as pd
from utils.voc_collector import VOCItem, classify_category, classify_sentiment, deduplicate


@dataclass
class DocumentChunk:
    source: str
    title: str
    text: str
    chunk_id: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "text": self.text,
            "chunk_id": self.chunk_id,
            "metadata": self.metadata,
        }


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _read_csv_bytes(data: bytes) -> pd.DataFrame:
    errors = []
    for enc in ["utf-8-sig", "cp949", "euc-kr", "utf-8", "latin1"]:
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc)
        except Exception as exc:
            errors.append(f"{enc}: {exc}")
    raise ValueError("CSV 인코딩을 판별하지 못했습니다. " + " | ".join(errors[:2]))


def _read_xlsx_bytes(data: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(data), engine="openpyxl")


def _read_txt_bytes(data: bytes) -> str:
    for enc in ["utf-8-sig", "cp949", "euc-kr", "utf-8", "latin1"]:
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")


def _read_docx_bytes(data: bytes) -> str:
    """python-docx/lxml 없이 DOCX 본문 텍스트를 추출한다."""
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if n.startswith("word/") and n.endswith(".xml")]
        for name in ["word/document.xml"] + [n for n in names if n != "word/document.xml"]:
            if name not in zf.namelist():
                continue
            try:
                root = ET.fromstring(zf.read(name))
            except Exception:
                continue
            for para in root.findall(".//w:p", ns):
                texts = [t.text or "" for t in para.findall(".//w:t", ns)]
                line = clean_text("".join(texts))
                if line:
                    parts.append(line)
    return "\n".join(parts)


def dataframe_to_voc_items(df: pd.DataFrame, source_name: str, max_rows: int = 500) -> list[VOCItem]:
    """표 형식 VOC를 VOCItem 리스트로 변환한다."""
    if df is None or df.empty:
        return []
    df = df.head(max_rows).copy()
    df.columns = [str(c).strip() for c in df.columns]
    lower_map = {c.lower(): c for c in df.columns}

    title_candidates = ["title", "제목", "subject", "summary", "요약", "voc", "문의", "불만", "내용"]
    content_candidates = ["content", "본문", "내용", "description", "desc", "comment", "review", "리뷰", "의견", "상세"]
    url_candidates = ["url", "link", "링크", "주소"]
    source_candidates = ["source", "채널", "출처", "사이트"]

    def pick(candidates: Iterable[str]) -> str | None:
        for cand in candidates:
            if cand.lower() in lower_map:
                return lower_map[cand.lower()]
        return None

    title_col = pick(title_candidates)
    content_col = pick(content_candidates)
    url_col = pick(url_candidates)
    source_col = pick(source_candidates)

    items: list[VOCItem] = []
    for idx, row in df.iterrows():
        row_dict = {str(k): "" if pd.isna(v) else str(v) for k, v in row.items()}
        title = clean_text(row_dict.get(title_col, "")) if title_col else ""
        content = clean_text(row_dict.get(content_col, "")) if content_col else ""
        if not title and not content:
            # 컬럼명이 불명확하면 모든 셀을 합쳐 VOC 본문으로 사용
            content = clean_text(" | ".join(v for v in row_dict.values() if v and v.lower() != "nan"))
            title = content[:80]
        if not content:
            content = title
        if not title:
            title = content[:80]
        if len(clean_text(title + content)) < 3:
            continue
        url = clean_text(row_dict.get(url_col, "")) if url_col else ""
        src = clean_text(row_dict.get(source_col, "")) if source_col else f"업로드:{source_name}"
        merged = f"{title} {content}"
        items.append(
            VOCItem(
                source=src or f"업로드:{source_name}",
                title=title[:220],
                content=content[:1200],
                url=url,
                category=classify_category(merged),
                sentiment=classify_sentiment(merged),
                extra={"uploaded_file": source_name, "row_index": int(idx)},
            )
        )
    return deduplicate(items)


def dataframe_to_chunks(df: pd.DataFrame, source_name: str, max_rows: int = 500) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    if df is None or df.empty:
        return chunks
    df = df.head(max_rows).copy()
    for idx, row in df.iterrows():
        cells = []
        for col, val in row.items():
            if pd.isna(val):
                continue
            txt = clean_text(str(val))
            if txt:
                cells.append(f"{col}: {txt}")
        text = " | ".join(cells)
        if not text:
            continue
        for cidx, chunk in enumerate(split_text(text)):
            chunks.append(DocumentChunk(
                source=f"업로드:{source_name}",
                title=f"{source_name} row {idx}",
                text=chunk,
                chunk_id=f"{source_name}-{idx}-{cidx}",
                metadata={"file": source_name, "row_index": int(idx)},
            ))
    return chunks


def parse_uploaded_file(uploaded_file, max_rows: int = 500) -> tuple[list[VOCItem], list[DocumentChunk], str]:
    """Streamlit UploadedFile을 VOCItem/DocumentChunk로 변환한다."""
    name = uploaded_file.name
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    data = uploaded_file.getvalue()

    if ext == "csv":
        df = _read_csv_bytes(data)
        return dataframe_to_voc_items(df, name, max_rows), dataframe_to_chunks(df, name, max_rows), f"CSV {len(df)}행 읽음"

    if ext in {"xlsx", "xlsm"}:
        df = _read_xlsx_bytes(data)
        return dataframe_to_voc_items(df, name, max_rows), dataframe_to_chunks(df, name, max_rows), f"Excel {len(df)}행 읽음"

    if ext == "txt":
        text = _read_txt_bytes(data)
        chunks = [DocumentChunk(f"업로드:{name}", name, c, f"{name}-{i}", {"file": name}) for i, c in enumerate(split_text(text))]
        items = [
            VOCItem(
                source=f"업로드:{name}",
                title=c[:80],
                content=c[:1200],
                category=classify_category(c),
                sentiment=classify_sentiment(c),
                extra={"uploaded_file": name, "chunk_id": i},
            )
            for i, c in enumerate(split_text(text, chunk_size=1200, overlap=100))
        ]
        return deduplicate(items), chunks, f"TXT {len(text):,}자 읽음"

    if ext == "docx":
        text = _read_docx_bytes(data)
        chunks = [DocumentChunk(f"업로드:{name}", name, c, f"{name}-{i}", {"file": name}) for i, c in enumerate(split_text(text))]
        items = [
            VOCItem(
                source=f"업로드:{name}",
                title=c[:80],
                content=c[:1200],
                category=classify_category(c),
                sentiment=classify_sentiment(c),
                extra={"uploaded_file": name, "chunk_id": i},
            )
            for i, c in enumerate(split_text(text, chunk_size=1200, overlap=100))
        ]
        return deduplicate(items), chunks, f"DOCX {len(text):,}자 읽음"

    raise ValueError(f"지원하지 않는 파일 형식입니다: .{ext}. CSV, TXT, DOCX, XLSX를 사용하세요.")
