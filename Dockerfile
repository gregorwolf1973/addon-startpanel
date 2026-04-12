ARG BUILD_FROM=python:3.12-alpine
FROM $BUILD_FROM

RUN pip3 install --no-cache-dir flask requests

COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
