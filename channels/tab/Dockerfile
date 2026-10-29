FROM node:24-bookworm-slim AS ui
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html sandbox.html tsconfig.json vite.config.js ./
COPY src ./src
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
COPY --from=ui /src/dist ./dist
RUN useradd --uid 10001 --create-home tab
USER tab
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
