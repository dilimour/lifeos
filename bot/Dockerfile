FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends poppler-utils \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lifeos ./lifeos
RUN useradd -u 1000 -m bot
USER bot
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "lifeos"]
