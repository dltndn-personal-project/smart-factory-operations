FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY src/ src/
COPY config/ config/
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT} PYTHONPATH=/app/src FOPS_DEFAULT_CONFIG=/app/config/default.yaml \
    IMAGE_ROOT=/data HTTP_PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('HTTP_PORT','8080'), timeout=2)"
CMD ["python", "-m", "factory_operations", "serve"]
