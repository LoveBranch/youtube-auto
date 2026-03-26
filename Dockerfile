FROM python:3.11-slim

# ffmpeg 설치
RUN apt-get update && apt-get install -y ffmpeg fonts-noto-cjk fontconfig && \
    fc-cache -fv && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE $PORT

CMD uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000}
