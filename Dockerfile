FROM python:3.12-slim

# ffmpeg: grava e corta | fonts-dejavu: legenda e gancho | deno: o yt-dlp precisa para ler o YouTube
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

ENV TZ=America/Sao_Paulo PYTHONUNBUFFERED=1 DADOS=/dados COOKIES=/config/cookies.txt
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -U -r requirements.txt
COPY robo ./robo

CMD ["python", "-m", "robo.main"]
