FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src/ ./src/
RUN pip install --no-cache-dir build && python -m build --wheel

FROM python:3.12-slim

RUN groupadd -r agenticu && useradd -r -g agenticu agenticu
WORKDIR /app

COPY --from=builder /build/dist/*.whl /tmp/
RUN set -- /tmp/agenticu-*.whl && pip install --no-cache-dir "$1[postgres]" && rm "$1"

COPY config.yaml /app/config.yaml

EXPOSE 8000
USER agenticu
ENTRYPOINT ["agenticu"]
CMD ["server"]
