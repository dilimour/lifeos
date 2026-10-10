#!/usr/bin/env bash
# Установка LifeOS-бота: база, пользователь Matrix, личный конфиг, запуск. Повторный запуск безопасен.
set -euo pipefail
cd "$(dirname "$0")"

add() { grep -q "^$1=" .env || echo "$1=$2" >> .env; }
add LIFEOS_BOT_PASSWORD "$(openssl rand -hex 16)"
add LIFEOS_DB_PASSWORD "$(openssl rand -hex 16)"
add LIFEOS_OWN_PHONE ""
add COMPOSE_PROFILES bot
chmod 600 .env
set -a; . ./.env; set +a

echo "== база lifeos"
docker compose exec -T postgres psql -U synapse -d postgres -v ON_ERROR_STOP=1 -c \
  "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='lifeos') THEN CREATE ROLE lifeos LOGIN PASSWORD '${LIFEOS_DB_PASSWORD}'; END IF; END \$\$;"
docker compose exec -T postgres psql -U synapse -d postgres -tAc "select 1 from pg_database where datname='lifeos'" | grep -q 1 \
  || docker compose exec -T postgres createdb -U synapse -O lifeos lifeos

echo "== пользователь @lifeos:${SERVER_NAME}"
docker compose exec -T synapse register_new_matrix_user -c /data/homeserver.yaml \
  -u lifeos -p "${LIFEOS_BOT_PASSWORD}" --no-admin http://localhost:8008 2>&1 | tail -1 || true

echo "== личный конфиг ../../bot/local/config.yaml"
mkdir -p ../../bot/local data/bot
[ -f ../../bot/local/config.yaml ] || cp ../../bot/config.example.yaml ../../bot/local/config.yaml
chown -R 1000:1000 data/bot

echo "== сборка и запуск"
docker compose up -d --build bot
sleep 15
docker compose logs --tail 15 bot
