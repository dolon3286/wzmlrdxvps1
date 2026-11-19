FROM mysterysd/wzmlx:v3

WORKDIR /usr/src/app

COPY requirements.txt .
RUN uv pip uninstall --python /wzvenv/bin/python -y pyrotgfork 2>/dev/null || true
RUN uv pip install --python /wzvenv/bin/python --no-cache-dir -r requirements.txt

COPY . .

ENTRYPOINT ["bash", "start.sh"]
