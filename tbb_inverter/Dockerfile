FROM ghcr.io/home-assistant/base-python:3.13-alpine3.24

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}"

WORKDIR /

COPY requirements.txt /requirements.txt
RUN pip3 install --no-cache-dir -r /requirements.txt

COPY tbb_reader.py /tbb_reader.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
