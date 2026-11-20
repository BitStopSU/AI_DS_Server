#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env
  echo "DASHBOARD_SESSION_SECRET=$(openssl rand -hex 32)" >> .env
  echo "→ Создан .env. Заполните DISCORD_TOKEN, DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, OWNER_IDS"
fi

npm install
echo "✅ Установка завершена. Запуск: npm start"