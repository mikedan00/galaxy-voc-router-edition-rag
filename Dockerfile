FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8501

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
EXPOSE 8501

HEALTHCHECK CMD python - <<'PY'
import urllib.request
urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=5)
print('ok')
PY

ENTRYPOINT ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
