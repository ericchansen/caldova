FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml .
COPY caldova ./caldova
RUN pip install --no-cache-dir . "azure-identity>=1.17,<2"
COPY channels/facade.py ./channels/facade.py
EXPOSE 8000
CMD ["python", "-m", "channels.facade"]
