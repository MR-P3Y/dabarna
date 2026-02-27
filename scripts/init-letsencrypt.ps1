param(
    [Parameter(Mandatory = $true)]
    [string]$Domain,
    [Parameter(Mandatory = $true)]
    [string]$Email
)

$ErrorActionPreference = "Stop"

Write-Host "Starting nginx (HTTP challenge endpoint)..."
docker compose --env-file .env.prod up -d nginx

Write-Host "Requesting certificate for $Domain ..."
docker compose --env-file .env.prod --profile certbot run --rm certbot certonly `
  --webroot -w /var/www/certbot `
  -d $Domain `
  --email $Email `
  --agree-tos `
  --no-eff-email

Write-Host "Reloading nginx with TLS configuration..."
docker compose --env-file .env.prod restart nginx

Write-Host "Certificate issuance completed."

