FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src/ ./src/
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.12-slim

RUN groupadd -r agenticu && useradd -r -g agenticu agenticu
WORKDIR /app

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

COPY config.yaml /app/config.yaml
COPY schema.sql /app/schema.sql

EXPOSE 8000
USER agenticu
ENTRYPOINT ["agenticu"]
CMD ["server"]
