FROM --platform=linux/amd64 python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir PyMuPDF==1.23.7

COPY 1a.py .

RUN mkdir -p /app/input /app/output

ENTRYPOINT ["python", "1a.py"]
