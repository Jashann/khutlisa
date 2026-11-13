# Khutlisa as one container: the Python server (run with uv), the built web app, whisper.cpp and ffmpeg for
# voice, and the fonts for letters in other scripts. No data and no credentials are in the image. California's
# file and the speech model are fetched into the mounted volume at /data on the first start (deploy/first_start.py).
#
#   docker build -t khutlisa .
#   docker run --rm khutlisa test                      # the image's own checks; needs no network and no keys
#   docker run -p 8000:8000 -v khutlisa-data:/data --env-file khutlisa.env khutlisa
#
# Not built or run on the machine this was written on (its Docker daemon was not running); see deploy/README.md.

# ---- the web app -------------------------------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# `npm run build` first runs prebuild.mjs, which leaves the prepared figures as they are when there is no database.
RUN npm run build

# ---- whisper.cpp -------------------------------------------------------------------------------------------------
FROM debian:bookworm-slim AS whisper
ARG WHISPER_CPP_VERSION=v1.7.6
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${WHISPER_CPP_VERSION}" https://github.com/ggml-org/whisper.cpp /src \
    && cmake -S /src -B /src/build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF \
    && cmake --build /src/build -j "$(nproc)" --target whisper-cli

# ---- the server --------------------------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv
# ffmpeg turns a browser recording into what whisper reads. WenQuanYi Zen Hei is a TrueType font with Chinese,
# Japanese and Korean letters, which the PDF library can embed (it cannot use the OpenType Noto CJK fonts).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-wqy-zenhei libgomp1 curl tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=whisper /src/build/bin/whisper-cli /usr/local/bin/whisper-cli

RUN useradd --create-home --uid 10001 khutlisa && mkdir -p /app /data && chown khutlisa:khutlisa /app /data
WORKDIR /app
USER khutlisa
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_NO_CACHE=1
COPY --chown=khutlisa:khutlisa pyproject.toml uv.lock README.md ./
COPY --chown=khutlisa:khutlisa src ./src
RUN uv sync --frozen --no-dev
COPY --chown=khutlisa:khutlisa scripts ./scripts
COPY --chown=khutlisa:khutlisa deploy ./deploy
COPY --chown=khutlisa:khutlisa --from=web /app/web/dist ./web/dist

# Configuration is by environment variables only (deploy/README.md lists them). These are the paths inside the
# container; every secret is given at run time and none is set here.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    KHUTLISA_DB=/data/registers.duckdb \
    KHUTLISA_TOTALS=/data/totals.json \
    KHUTLISA_CLAIMS=/data/claims \
    KHUTLISA_WHISPER_MODEL=/data/models/ggml-small.bin \
    KHUTLISA_WIDE_FONT=/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc \
    PORT=8000
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1
ENTRYPOINT ["tini", "--", "/app/deploy/entrypoint.sh"]
CMD ["serve"]
