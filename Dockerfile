# Bagholder's web app in a container: Python's own slim Debian image, the app's
# files, no build step. Data lives in /data, mounted from the host; the login is
# captured on the host once with `python3 bagholder.py --connect` (README, Docker).
FROM python:3.12-slim-bookworm

WORKDIR /app
COPY bagholder.py model.py market.py store.py csvimport.py ledger.html lightweight-charts.js favicon.png ./

RUN mkdir -p /data

# /data holds the database and the login; the server answers every interface of
# the container (compose publishes it on the host's loopback only); no browser
# opens at start and no update is downloaded: a new release is a new image.
ENV BAGHOLDER_HOME=/data \
    BAGHOLDER_PORT=8765 \
    BAGHOLDER_BIND=0.0.0.0 \
    BAGHOLDER_NO_BROWSER=1 \
    BAGHOLDER_NO_UPDATE=1 \
    PYTHONUNBUFFERED=1

# root inside the container, so a data folder mounted from any host user is writable
# as it is; the process touches nothing but /data, and the port is loopback-only.
VOLUME ["/data"]
EXPOSE 8765
CMD ["python3", "bagholder.py"]
