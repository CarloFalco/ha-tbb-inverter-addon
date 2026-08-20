ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.13-alpine3.24
FROM ${BUILD_FROM}

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="addon" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.source="https://github.com/CarloFalco/ha-tbb-inverter-addon"

ENV ADDON_VERSION="${BUILD_VERSION}" \
    PYTHONUNBUFFERED=1

WORKDIR /

COPY requirements.txt /requirements.txt
RUN pip3 install --no-cache-dir -r /requirements.txt

COPY tbb_reader.py /tbb_reader.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
