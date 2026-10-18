FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GOOGLE_FORMS_MULTIUSER_DATA_DIR=/var/lib/google-forms-mcp \
    PORT=8000

RUN groupadd --system app && useradd --system --gid app --home /app app \
    && mkdir -p /app /var/lib/google-forms-mcp \
    && chown -R app:app /app /var/lib/google-forms-mcp

WORKDIR /app

COPY --chown=app:app pyproject.toml README.md LICENSE ./
COPY --chown=app:app src ./src

RUN pip install --no-cache-dir .

USER app

VOLUME ["/var/lib/google-forms-mcp"]
EXPOSE 8000

CMD ["google-forms-connector"]
