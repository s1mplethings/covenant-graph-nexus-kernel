FROM python@sha256:37ed081dbe77115b843b3d139801105e110f43005a2df4e80af94777cfd807f5
RUN apk add --no-cache chromium ffmpeg nodejs npm sqlite ripgrep curl \
    && pip install --no-cache-dir flask pytest websocket-client requests
RUN mkdir /workspace /input /opt/evaltools && chmod 1777 /workspace
COPY browser.py /opt/evaltools/browser.py
ENV HOME=/tmp/home PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
USER 65534:65534
CMD ["sleep", "infinity"]
