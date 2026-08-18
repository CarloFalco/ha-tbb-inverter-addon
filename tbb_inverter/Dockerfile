ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /

COPY requirements.txt /requirements.txt
RUN pip3 install --no-cache-dir -r /requirements.txt

COPY tbb_reader.py /tbb_reader.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
