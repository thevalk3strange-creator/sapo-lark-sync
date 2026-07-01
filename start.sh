#!/bin/bash
set -e

echo "=== Lark CLI Setup ==="

# Create lark-cli env file from Railway env vars
mkdir -p /opt/data
cat > /opt/data/.env << ENVEOF
FEISHU_APP_ID=${LARK_APP_ID}
FEISHU_APP_SECRET=${LARK_APP_SECRET}
ENVEOF

echo "lark-cli .env created"

# Bind lark-cli to Hermes (bot-only identity)
echo "Binding lark-cli to Hermes..."
lark-cli config bind \
  --source hermes \
  --app-id "${LARK_APP_ID}" \
  --identity bot-only 2>&1 || echo "Bind skipped (may already be bound)"

echo "=== Starting Hermes Gateway ==="
exec hermes gateway
