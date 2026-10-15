FROM denoland/deno:bin AS deno

FROM python:3.12-slim

# Add project source
WORKDIR /musicbot
COPY . ./
COPY ./config sample_config

# Install build + runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  libffi-dev \
  libsodium-dev \
  ca-certificates \
  ffmpeg \
  libopus-dev \
  git \
  wget \
  unzip \
  && rm -rf /var/lib/apt/lists/*

# Copy the deno binary (Debian has real glibc, no compat shim needed)
COPY --from=deno /deno /usr/local/bin/deno
RUN chmod +x /usr/local/bin/deno

# Install pip dependencies + PO token provider plugin
RUN pip3 install --no-cache-dir -r requirements.txt \
  && pip3 install --no-cache-dir -U bgutil-ytdlp-pot-provider

# Fetch the bgutil-ytdlp-pot-provider script (pre-built release, no npm/tsc needed)
RUN mkdir -p /root/bgutil-ytdlp-pot-provider \
  && wget -qO /tmp/bgutil.zip https://github.com/Brainicism/bgutil-ytdlp-pot-provider/releases/download/1.3.1/bgutil-ytdlp-pot-provider.zip \
  && unzip /tmp/bgutil.zip -d /root/bgutil-ytdlp-pot-provider \
  && rm /tmp/bgutil.zip

# Create volumes for audio cache, config, data and logs
VOLUME ["/musicbot/audio_cache", "/musicbot/config", "/musicbot/data", "/musicbot/logs"]

ENV APP_ENV=docker

ENTRYPOINT ["/bin/sh", "docker-entrypoint.sh"]
