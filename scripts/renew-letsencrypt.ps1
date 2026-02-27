$ErrorActionPreference = "Stop"

docker compose --env-file .env.prod --profile certbot run --rm certbot renew --webroot -w /var/www/certbot
docker compose --env-file .env.prod exec -T nginx nginx -s reload

Write-Host "Certificate renewal finished and nginx reloaded."

