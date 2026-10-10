#!/usr/bin/env bash
# Первичная установка Synapse + Postgres + ntfy. Повторный запуск безопасен.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || cp .env.example .env
set -a; . ./.env; set +a

if [ "${POSTGRES_PASSWORD}" = "change_me" ]; then
  POSTGRES_PASSWORD=$(openssl rand -hex 24)
  sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${POSTGRES_PASSWORD}/" .env
  echo "Сгенерирован пароль Postgres (в .env)"
fi
chmod 600 .env

mkdir -p data/postgres data/synapse data/ntfy/cache data/ntfy/lib

if [ ! -f data/synapse/homeserver.yaml ]; then
  docker compose run --rm -e SYNAPSE_SERVER_NAME="${SERVER_NAME}" -e SYNAPSE_REPORT_STATS=no synapse generate
fi
docker compose run --rm --entrypoint python -e POSTGRES_PASSWORD -e MATRIX_HOST synapse /scripts/patch_homeserver.py

docker compose up -d
echo "Ждём, пока Synapse станет healthy..."
st=unknown
for _ in $(seq 1 30); do
  st=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose ps -q synapse)" 2>/dev/null || echo unknown)
  [ "$st" = "healthy" ] && break; sleep 5
done
echo "Synapse: $st"
curl -fsS http://127.0.0.1:18008/_matrix/client/versions >/dev/null && echo "Synapse отвечает на 127.0.0.1:18008"
curl -fsS http://127.0.0.1:18090/v1/health && echo

# UnifiedPush: любой может писать в топики up*, читать — только авторизованные
docker compose exec -T ntfy ntfy access everyone 'up*' write-only || true

cat <<MSG

Готово. Дальше вручную (пароли вводятся интерактивно):
  1) Пользователь Matrix (админ):
     docker compose exec synapse register_new_matrix_user -c /data/homeserver.yaml -u john -a http://localhost:8008
  2) Пользователь ntfy для телефона:
     docker compose exec ntfy ntfy user add --role=admin john
MSG
