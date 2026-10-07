# Containerization (Docker)

> **Not built in this repo by design** — the author runs locally and has storage
> constraints. A ready-to-use [`Dockerfile`](../Dockerfile) and `.dockerignore`
> are included so anyone can build it in one command. Everything below is
> reference material.

## Build & run

```bash
# from the project root
docker build -t vantage .

docker run --rm -p 8501:8501 --env-file .env vantage
# open http://localhost:8501
```

The image is based on `python:3.11-slim`, installs `requirements.txt`, copies the
source, and **bakes the dataset in** (`python seed/generate_data.py --scale rich`
runs during build) so the container is fully self-contained. It exposes `8501`
and includes a Streamlit health check.

Pass configuration with `--env-file .env` (never bake secrets into the image):

```bash
docker run --rm -p 8501:8501 \
  -e GROQ_API_KEY=your_key \
  -e LLM_PROVIDER=groq \
  vantage
```

## docker-compose (optional)

```yaml
# docker-compose.yml
services:
  app:
    build: .
    ports:
      - "8501:8501"
    env_file:
      - .env
```

```bash
docker compose up --build
```

## Notes

- **Image size**: `python:3.11-slim` + these deps ≈ 1.0–1.3 GB. To slim further,
  use a multi-stage build, or generate data at container **start** (entrypoint)
  instead of at build time to keep the image layer smaller.
- **Smaller data**: build with a lighter dataset by changing the Dockerfile line to
  `--scale small`.
- **Read-only data**: for a smaller runtime image, generate the DB in a volume on
  first run rather than baking it in:
  ```bash
  docker run --rm -p 8501:8501 -v vantage_data:/app/data --env-file .env vantage
  ```
- **Production**: put the container behind the AWS services described in
  [DEPLOYMENT_AWS.md](DEPLOYMENT_AWS.md); keep secrets in a secrets manager, not in
  the image.
