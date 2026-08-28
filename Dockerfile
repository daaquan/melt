FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src src
COPY locales locales
RUN pip install --no-cache-dir .
ENV MELT_DB_PATH=/data/melt.db
ENV MELT_LOCALE_DIR=/app/locales
EXPOSE 8080
CMD ["uvicorn", "melt.app:app", "--host", "0.0.0.0", "--port", "8080"]
