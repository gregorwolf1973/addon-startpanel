FROM python:3.12-alpine

RUN pip3 install --no-cache-dir flask requests werkzeug

COPY app /app

EXPOSE 8099

CMD ["python3", "/app/server.py"]
