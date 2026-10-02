FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS api
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/rescue
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY rescue ./rescue
COPY cases.json OAUTH_SETUP.md ./
COPY bootstrap ./bootstrap
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home rescue && mkdir /runtime && chown rescue:rescue /runtime
USER 10001:10001
ENV RESCUE_RUNTIME=/runtime RESCUE_DATA_ROOT=/data
EXPOSE 8093
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8093/healthz',timeout=2)"
CMD ["python","-m","uvicorn","rescue.api:app","--host","0.0.0.0","--port","8093","--no-proxy-headers","--no-access-log"]

# This image belongs on the dedicated execution VM, never inside the API service.
FROM docker:29-cli@sha256:9f36dfce2d1fd053d700a4eca00c358df79bf7d8cb69d4a9e8d9981af18834ea AS dockercli
FROM api AS executor
USER root
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8094/healthz',timeout=2)"
CMD ["python","-m","uvicorn","rescue.executor_api:app","--host","0.0.0.0","--port","8094","--no-proxy-headers","--no-access-log"]
