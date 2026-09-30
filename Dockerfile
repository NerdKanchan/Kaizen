FROM node:22-bookworm-slim AS ui
WORKDIR /build/ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir '.[api]'
COPY --from=ui /build/ui/dist /app/ui/dist
COPY scripts/serve_hosted.py /app/scripts/serve_hosted.py
ENV KAIZEN_WORKSPACE=/var/data/kaizen KAIZEN_HOSTED=1 KAIZEN_SECURE_COOKIES=1
EXPOSE 10000
CMD ["python", "/app/scripts/serve_hosted.py"]
