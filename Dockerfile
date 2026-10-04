# Website + agent API in one container. Uses data/subset/*.parquet (16 MB), not the raw CSVs.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" duckdb pandas numpy "scikit-learn==1.9.1" joblib openai anthropic
COPY agents ./agents
COPY ml ./ml
COPY api ./api
COPY web ./web
COPY data/subset ./data/subset
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
