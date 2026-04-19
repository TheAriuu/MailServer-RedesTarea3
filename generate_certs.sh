#!/usr/bin/env bash
# generate_certs.sh - Generate self-signed TLS certificates for the mail server
#
# Usage:
#   ./generate_certs.sh [domain] [output_dir]
#
# Defaults:
#   domain     = localhost
#   output_dir = ./certs
#
# Outputs:
#   <output_dir>/server.key   - Private key (keep secret!)
#   <output_dir>/server.crt   - Self-signed certificate
#   <output_dir>/server.pem   - Combined PEM (key + cert) for convenience
#
# For production use a certificate from a trusted CA (e.g. Let's Encrypt):
#   sudo certbot certonly --standalone -d mail.yourdomain.com
#   Then use /etc/letsencrypt/live/mail.yourdomain.com/privkey.pem
#         and /etc/letsencrypt/live/mail.yourdomain.com/fullchain.pem

set -euo pipefail

DOMAIN="${1:-localhost}"
OUTPUT_DIR="${2:-./certs}"
DAYS=3650   # 10 years for dev/testing

mkdir -p "${OUTPUT_DIR}"

echo "==> Generating TLS certificate for domain: ${DOMAIN}"
echo "    Output directory: ${OUTPUT_DIR}"
echo ""

# ── Generate private key ──────────────────────────────────────────────────────
openssl genrsa -out "${OUTPUT_DIR}/server.key" 4096
echo "✓  Private key:   ${OUTPUT_DIR}/server.key"

# ── Generate self-signed certificate ─────────────────────────────────────────
openssl req -new -x509 \
  -key   "${OUTPUT_DIR}/server.key" \
  -out   "${OUTPUT_DIR}/server.crt" \
  -days  "${DAYS}" \
  -subj  "/C=CR/ST=SanJose/L=SanJose/O=MailServer/CN=${DOMAIN}" \
  -addext "subjectAltName=DNS:${DOMAIN},DNS:mail.${DOMAIN},IP:127.0.0.1"

echo "✓  Certificate:   ${OUTPUT_DIR}/server.crt"

# ── Combined PEM (useful for some clients) ───────────────────────────────────
cat "${OUTPUT_DIR}/server.key" "${OUTPUT_DIR}/server.crt" > "${OUTPUT_DIR}/server.pem"
chmod 600 "${OUTPUT_DIR}/server.key" "${OUTPUT_DIR}/server.pem"
echo "✓  Combined PEM:  ${OUTPUT_DIR}/server.pem"

# ── Inspect the certificate ──────────────────────────────────────────────────
echo ""
echo "==> Certificate details:"
openssl x509 -in "${OUTPUT_DIR}/server.crt" -noout -subject -issuer -dates

echo ""
echo "==> Usage in mail servers:"
echo "    SMTP:  python smtpserver.py ... --ssl-cert ${OUTPUT_DIR}/server.crt --ssl-key ${OUTPUT_DIR}/server.key --starttls"
echo "    POP3:  python pop3server.py ... --ssl-cert ${OUTPUT_DIR}/server.crt --ssl-key ${OUTPUT_DIR}/server.key"
echo ""
echo "==> NOTE: Self-signed certs will trigger warnings in mail clients."
echo "    For production, use Let's Encrypt:"
echo "    sudo certbot certonly --standalone -d mail.${DOMAIN}"
