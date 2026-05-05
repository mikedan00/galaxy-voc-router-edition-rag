# Galaxy VOC Collector — Router/RAG Edition

Streamlit 기반 Galaxy VOC 분석 도구입니다.

## 주요 기능

1. 기본 VOC 수집
   - 삼성 Members, 네이버 지식인, 네이버 카페, DC인사이드, 클리앙
2. 사용자 URL 추가 수집
   - 앱 사이드바에서 URL을 한 줄에 하나씩 입력
   - 임의 리뷰 페이지, 커뮤니티 글, 게시판 URL을 VOC 소스로 추가
3. 파일 업로드 기반 VOC 적용
   - CSV, XLSX/XLSM, TXT, DOCX 지원
   - 업로드 파일을 VOCItem으로 변환
   - 동시에 RAG 검색용 청크로 분할
4. 경량 임베딩/RAG
   - 외부 벡터DB 없이 TF-IDF 방식으로 근거 검색
   - VOC와 업로드 파일 청크를 통합 인덱싱
   - RAG 기반 질문 답변 생성
   - AI 분석/SRS 생성 시 RAG 근거 자동 포함 가능
5. Hugging Face Router 기반 LLM 호출
   - `https://router.huggingface.co/v1/chat/completions`
   - provider suffix 후보 fallback 지원
6. 산출물
   - `analysis.json`
   - `rag_context.json`
   - `srs.md`
   - `docx`
   - 결과 ZIP 다운로드

## 로컬 실행

```powershell
cd C:\0MyWork1\galaxy-voc-router-edition-rag
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env
python scripts/check_env.py
python scripts/test_hf_router.py
streamlit run app.py
```

PowerShell 실행 정책 오류가 나면 현재 창에서만 허용합니다.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

## .env 예시

```env
LLM_ENGINE=hf_api
HF_TOKEN=hf_새로발급한토큰
HF_ROUTER_MODEL=google/gemma-4-26B-A4B-it:deepinfra
HF_MODEL_CANDIDATES=google/gemma-4-26B-A4B-it:deepinfra,google/gemma-4-26B-A4B-it:novita,google/gemma-4-31B-it:deepinfra,google/gemma-4-31B-it:together,Qwen/Qwen3.5-9B:together,Qwen/Qwen2.5-7B-Instruct:together
HF_MAX_TOKENS=1400
HF_TEMPERATURE=0.2
HF_TIMEOUT_CONNECT=10
HF_TIMEOUT_READ=120
HF_MAX_RETRIES=3
PORT=8501
```

> 기존에 공개 채팅이나 GitHub에 노출된 HF 토큰은 반드시 폐기하고 새 토큰을 발급하세요.

## Streamlit Cloud 배포

### 1. GitHub에 업로드

```powershell
git init
git add .
git commit -m "Add URL upload RAG features"
git branch -M main
git remote add origin https://github.com/mikedan00/galaxy-voc-router-edition.git
git push -u origin main
```

이미 origin이 있으면:

```powershell
git remote set-url origin https://github.com/mikedan00/galaxy-voc-router-edition.git
git push -u origin main
```

### 2. Streamlit Secrets

Streamlit Cloud → Manage App → Settings → Secrets에 아래처럼 TOML 형식으로 입력합니다.

```toml
HF_TOKEN = "hf_새로발급한토큰"
LLM_ENGINE = "hf_api"
HF_ROUTER_MODEL = "google/gemma-4-26B-A4B-it:deepinfra"
HF_MODEL_CANDIDATES = "google/gemma-4-26B-A4B-it:deepinfra,google/gemma-4-26B-A4B-it:novita,google/gemma-4-31B-it:deepinfra,google/gemma-4-31B-it:together,Qwen/Qwen3.5-9B:together,Qwen/Qwen2.5-7B-Instruct:together"
HF_MAX_TOKENS = "1400"
HF_TEMPERATURE = "0.2"
HF_TIMEOUT_CONNECT = "10"
HF_TIMEOUT_READ = "120"
HF_MAX_RETRIES = "3"
```

### 3. Python 버전

Streamlit Cloud에서 Python 3.11 또는 3.12를 선택하세요.
이 프로젝트에는 `.python-version`과 `runtime.txt`도 포함되어 있습니다.

## 앱 사용 순서

1. `HF Router 연결 확인`
2. 기본 VOC 수집 또는 사용자 URL 추가
3. 파일 업로드 탭에서 CSV/XLSX/TXT/DOCX 업로드
4. RAG 탭에서 검색/답변 확인
5. `VOC AI 분석`
6. `SRS Markdown 생성`
7. `DOCX 생성`
8. 내보내기 탭에서 결과 다운로드

## 파일 업로드 컬럼 인식

CSV/XLSX는 다음 컬럼명을 자동 인식합니다.

- 제목: `title`, `제목`, `subject`, `summary`, `요약`, `voc`, `문의`, `불만`, `내용`
- 본문: `content`, `본문`, `내용`, `description`, `desc`, `comment`, `review`, `리뷰`, `의견`, `상세`
- URL: `url`, `link`, `링크`, `주소`
- 출처: `source`, `채널`, `출처`, `사이트`

컬럼명이 불명확하면 행 전체 셀을 합쳐 VOC 본문으로 사용합니다.

## 배포 안정성 메모

- `lxml`, `python-docx`, `torch`, `transformers`, `sentence-transformers`, `faiss`, `chromadb`는 기본 requirements에서 제외했습니다.
- DOCX 읽기/쓰기는 표준 라이브러리 기반으로 구현했습니다.
- RAG도 표준 라이브러리 TF-IDF 방식으로 구현했습니다.
- 따라서 Streamlit Cloud에서 의존성 설치 실패 가능성이 낮습니다.


## PPTX 출력 기능

이번 버전은 DOCX뿐 아니라 PowerPoint 보고서(.pptx)도 생성합니다.

앱 왼쪽의 **분석/명세서** 영역에서 `📊 PPTX 생성` 버튼을 누르면 다음 내용을 포함한 16:9 보고서가 만들어집니다.

- 표지
- VOC 분석 대시보드
- Executive Summary
- 핵심 이슈와 문제 진술
- 기능 요구사항
- 비기능 요구사항과 KPI
- 개선 로드맵
- RAG 근거 및 답변
- 대표 VOC 샘플
- SRS 본문 요약

생성된 PPTX는 **내보내기** 탭에서 `PPTX 다운로드` 또는 `결과 ZIP 다운로드`로 받을 수 있습니다.
Streamlit Cloud 배포 안정성을 위해 `python-pptx`, `lxml` 없이 표준 라이브러리 기반 OOXML 생성 방식으로 구현되어 있습니다.
