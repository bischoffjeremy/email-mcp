FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir .

EXPOSE 8002

CMD ["fastmcp", "run", "src/server.py:mcp", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8002"]
