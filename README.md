# Monitor de VPS (Flask + Postgres + Docker Compose)

Arquitetura 3 camadas: **Navegador → Servidor WEB (Flask) → SGBD (Postgres)**.
A app coleta o status TCP dos alvos, grava no banco e exibe a lista e gráficos (1h/24h/7d).

## Rodar
```bash
cp .env.example .env
# edite docker-compose.yml e troque REPO_URL pelo seu repositório GitHub
docker compose up -d --build
# http://localhost:8080
