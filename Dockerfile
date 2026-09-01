# The tool server and the orchestrator. Both run from this stage; the service each becomes is
# decided by the entrypoint compose gives it.
FROM python:3.11-slim AS service

ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000

ENTRYPOINT ["orient-mcp"]
CMD ["--transport", "stdio"]

# The page needs Streamlit and its chart component, which the services behind it do not. Naming
# the extra rather than the packages keeps the versions in pyproject, where the rest of them are.
FROM service AS gui

USER root
RUN pip install --no-cache-dir ".[gui]"
USER app

EXPOSE 8501

ENTRYPOINT ["orient-gui"]
CMD ["--host", "0.0.0.0", "--port", "8501"]
