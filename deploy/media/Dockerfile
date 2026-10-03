FROM python:3.13-slim AS download
ARG VERSION=1.21.1
ARG SHA256=653abc672a3e693f8d3b2717752492fdcfb8072291ec108d03d3dd857411b0ee
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --location --retry 3 -o /tmp/media.tar.gz \
       "https://github.com/bluenviron/mediamtx/releases/download/v${VERSION}/mediamtx_v${VERSION}_linux_amd64.tar.gz" \
    && echo "${SHA256}  /tmp/media.tar.gz" | sha256sum --check \
    && tar -xzf /tmp/media.tar.gz -C /tmp mediamtx

FROM python:3.13-slim
RUN useradd --uid 10001 --create-home media
COPY --from=download /tmp/mediamtx /usr/local/bin/mediamtx
COPY deploy/media/gateway.py /app/gateway.py
USER media
EXPOSE 8888
ENTRYPOINT ["python", "/app/gateway.py"]
