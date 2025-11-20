FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar requirements primero para mejor cache de Docker
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/app.py

# Carpeta para claves SSH
RUN mkdir -p /app/.ssh && chmod 700 /app/.ssh

EXPOSE 7860

CMD ["python", "app.py"]