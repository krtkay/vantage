# Reference Dockerfile. NOT built locally (storage-conscious) - see docs/DOCKER.md.
# Build:  docker build -t vantage .
# Run:    docker run -p 8501:8501 --env-file .env vantage
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bake the dataset into the image so the container is self-contained.
RUN python seed/generate_data.py --scale rich

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "src/vantage/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
