FROM python:3.12-slim

ARG REPO_URL
ARG REPO_REF=main

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# git para clonar o repositório no build
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Se REPO_URL for informado, clona o repo para dentro do container
RUN if [ -n "$REPO_URL" ]; then \
      echo "Clonando $REPO_URL (ref: $REPO_REF)..." && \
      git clone --depth=1 --branch "$REPO_REF" "$REPO_URL" /app; \
    else \
      echo "Sem REPO_URL; usará o contexto local."; \
    fi

# Dependências
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copia o restante (no-op se já clonou)
COPY . /app

EXPOSE 8080
CMD ["python", "app.py"]
