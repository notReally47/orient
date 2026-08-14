FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 9000

# stdio by default so a local MCP client can run the image directly; compose passes the
# streamable-http arguments, including the host, because the SDK binds loopback otherwise.
ENTRYPOINT ["python", "-m", "orient.mcp.server"]
CMD ["--transport", "stdio"]