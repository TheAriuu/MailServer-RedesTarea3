# Genera certificados self-signed TLS para el mail server
# Para correrlo: ./generate_certs.sh [DOMINIO] [output_dir]
# Por defecto:
#   DOMINIO     = localhost
#   output_dir = ./certs
# Salidas:
#   <output_dir>/server.key   - Private key (keep secret!)
#   <output_dir>/server.crt   - Self-signed certificate
#   <output_dir>/server.pem   - Combined PEM (key + cert) for convenience
#

set -euo pipefail

DOMINIO="${1:-localhost}"
OUTPUT_DIR="${2:-./certs}"
DAYS=3650   # 10 años

mkdir -p "${OUTPUT_DIR}"

echo "==> Generando certificado TLS para el dominio: ${DOMINIO}"
echo "    Output directory: ${OUTPUT_DIR}"
echo ""

# Generar llave
openssl genrsa -out "${OUTPUT_DIR}/server.key" 4096
echo "✓  Private key:   ${OUTPUT_DIR}/server.key"

# Generar certificado self-signed
openssl req -new -x509 \
  -key   "${OUTPUT_DIR}/server.key" \
  -out   "${OUTPUT_DIR}/server.crt" \
  -days  "${DAYS}" \
  -subj  "/C=CR/ST=SanJose/L=SanJose/O=MailServer/CN=${DOMINIO}" \
  -addext "subjectAltName=DNS:${DOMINIO},DNS:mail.${DOMINIO},IP:127.0.0.1"

echo "✓  Certificate:   ${OUTPUT_DIR}/server.crt"

# PEM combinado
cat "${OUTPUT_DIR}/server.key" "${OUTPUT_DIR}/server.crt" > "${OUTPUT_DIR}/server.pem"
chmod 600 "${OUTPUT_DIR}/server.key" "${OUTPUT_DIR}/server.pem"
echo "✓  Combined PEM:  ${OUTPUT_DIR}/server.pem"

# Inspeccionar el certificado
echo ""
echo "==> Detalles del certificado:"
openssl x509 -in "${OUTPUT_DIR}/server.crt" -noout -subject -issuer -dates

echo ""
echo "==> Uso en mail servers:"
echo "    SMTP:  python smtpserver.py ... --ssl-cert ${OUTPUT_DIR}/server.crt --ssl-key ${OUTPUT_DIR}/server.key --starttls"
echo "    POP3:  python pop3server.py ... --ssl-cert ${OUTPUT_DIR}/server.crt --ssl-key ${OUTPUT_DIR}/server.key"
echo ""