FROM python:3.11-slim

ENV COQUI_TOS_AGREED=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ffmpeg \
        git \
        libsndfile1 \
        espeak-ng \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel

RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.2.2+cpu" \
        "torchaudio==2.2.2+cpu"

RUN pip install --no-cache-dir \
        "numpy<2" \
        "transformers<4.50" \
        "TTS==0.22.0"

WORKDIR /app

ENTRYPOINT ["python", "/app/xtts_worker.py"]
