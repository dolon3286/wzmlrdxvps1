FROM mysterysd/wzmlx:v3

WORKDIR /usr/src/app

COPY requirements.txt .
RUN uv pip install --python /wzvenv/bin/python --no-cache-dir -r requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip mkvtoolnix \
    && (apt-cache show gpac >/dev/null 2>&1 && apt-get install -y --no-install-recommends gpac || echo "gpac/MP4Box package unavailable; skipping optional helper") \
    && arch="$(dpkg --print-architecture)" \
    && case "$arch" in amd64) narch="linux-x64" ;; arm64) narch="linux-arm64" ;; *) echo "Unsupported arch: $arch" && exit 1 ;; esac \
    && release="$(curl -fsSL https://api.github.com/repos/nilaoda/N_m3u8DL-RE/releases/latest | python3 -c "import json,sys; data=json.load(sys.stdin); print(next(a['browser_download_url'] for a in data['assets'] if '$narch' in a['name'] and a['name'].endswith('.tar.gz')))" )" \
    && mkdir -p /tmp/n_m3u8dl \
    && curl -fL "$release" -o /tmp/n_m3u8dl.tar.gz \
    && tar -xzf /tmp/n_m3u8dl.tar.gz -C /tmp/n_m3u8dl \
    && install -m 0755 "$(find /tmp/n_m3u8dl -type f -name N_m3u8DL-RE -print -quit)" /usr/local/bin/N_m3u8DL-RE \
    && rm -rf /tmp/n_m3u8dl /tmp/n_m3u8dl.tar.gz /var/lib/apt/lists/*

COPY . .

ENTRYPOINT ["bash", "start.sh"]
