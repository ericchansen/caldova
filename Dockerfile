FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY caldova ./caldova
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home agent
USER agent
EXPOSE 8000
CMD ["python", "-m", "caldova.server"]
