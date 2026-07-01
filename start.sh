#!/bin/bash
# Install lark-cli
echo "Installing lark-cli..."
npm install -g @larksuite/cli@latest 2>/dev/null

# Configure lark-cli with app credentials
echo "Configuring lark-cli..."
lark-cli config init --non-interactive \
  --app-id "$LARK_APP_ID" \
  --app-secret "$LARK_APP_SECRET" \
  --domain "https://open.larksuite.com" 2>/dev/null || true

echo "lark-cli ready!"
echo "Starting Hermes gateway..."

# Start Hermes gateway
exec hermes gateway
