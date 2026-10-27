FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m copilot download-runtime && \
    cli_path="$(find /root/.cache/github-copilot-sdk/cli -type f -name copilot -print -quit)" && \
    test -n "$cli_path" && install -m 0755 "$cli_path" /usr/local/bin/copilot
ENV COPILOT_CLI_PATH=/usr/local/bin/copilot
ENV PYTHONNOUSERSITE=1
COPY main.py .
COPY native_apps.py .
COPY check_image.py .
RUN /usr/local/bin/copilot --version && python check_image.py
EXPOSE 8088
CMD ["python", "main.py"]
