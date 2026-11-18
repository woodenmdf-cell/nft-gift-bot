FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core espeak-ng \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pillow edge-tts
WORKDIR /app
COPY . .
CMD ["python", "server.py"]
