#!/bin/sh
set -eu

SERVER_NAME="${NGINX_SERVER_NAME:-_}"
TEMPLATE_DIR="/etc/nginx/templates"
CONF_PATH="/etc/nginx/conf.d/default.conf"
CERT_PATH="/etc/letsencrypt/live/${SERVER_NAME}"

if [ "$SERVER_NAME" != "_" ] && [ -f "${CERT_PATH}/fullchain.pem" ] && [ -f "${CERT_PATH}/privkey.pem" ]; then
  export NGINX_SERVER_NAME="$SERVER_NAME"
  envsubst '${NGINX_SERVER_NAME}' < "${TEMPLATE_DIR}/https.conf.template" > "${CONF_PATH}"
  echo "nginx: TLS config enabled for ${SERVER_NAME}"
else
  export NGINX_SERVER_NAME="$SERVER_NAME"
  envsubst '${NGINX_SERVER_NAME}' < "${TEMPLATE_DIR}/http-only.conf.template" > "${CONF_PATH}"
  echo "nginx: HTTP-only config enabled (certificate not found for ${SERVER_NAME})"
fi

exec nginx -g "daemon off;"

