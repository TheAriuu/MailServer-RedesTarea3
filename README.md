# Twisted Mail Server

A full-featured email server suite built with **Python 3** and **Twisted**, providing SMTP reception/delivery, bulk SMTP sending, POP3 retrieval, TLS encryption, and XMPP notifications.

---

## Components

| File | Role |
|------|------|
| `smtpserver.py` | SMTP/ESMTP server — receives inbound mail |
| `smtpclient.py` | Bulk SMTP client — sends personalised mail from CSV |
| `pop3server.py` | POP3 server — lets clients download their mail |
| `xmpp_notifier.py` | XMPP/Jabber notifier — alerts user on new mail |
| `mailstorage.py` | Shared filesystem storage layer |
| `user_manager.py` | CLI tool to manage user accounts |
| `generate_certs.sh` | Script to create self-signed TLS certificates |

---

## Requirements

### Python packages
```bash
pip install -r requirements.txt
```

### System packages (Debian / Ubuntu)
```bash
sudo apt install openssl python3-openssl
```

---

## Quick Start

### 1 · Generate TLS Certificates
```bash
chmod +x generate_certs.sh
./generate_certs.sh mydomain.com ./certs
```
For production, use **Let's Encrypt**:
```bash
sudo certbot certonly --standalone -d mail.mydomain.com
# cert  → /etc/letsencrypt/live/mail.mydomain.com/fullchain.pem
# key   → /etc/letsencrypt/live/mail.mydomain.com/privkey.pem
```

### 2 · Create User Accounts
```bash
# Interactive password prompt
python user_manager.py add -u alice@mydomain.com -s /var/mail

# With explicit password (not recommended for production)
python user_manager.py add -u bob@mydomain.com -p secret123 -s /var/mail

# List users
python user_manager.py list

# Show mailbox info
python user_manager.py info -u alice@mydomain.com -s /var/mail
```
Credentials are saved in `users.json`.

### 3 · Start the SMTP Server
```bash
# Basic (port 2525, no TLS)
python smtpserver.py -d mydomain.com -s /var/mail -p 2525

# With TLS — SMTPS on 4650, STARTTLS on 2525
python smtpserver.py \
    -d mydomain.com,mail.mydomain.com \
    -s /var/mail \
    -p 2525 \
    --ssl-cert certs/server.crt \
    --ssl-key  certs/server.key \
    --ssl-port 4650 \
    --starttls

# With XMPP notifications
python smtpserver.py -d mydomain.com -s /var/mail -p 2525 \
    --xmpp-config examples/xmpp_config.json
```

### 4 · Start the POP3 Server
```bash
# Plain POP3
python pop3server.py -s /var/mail -p 1100 --credentials users.json --domain mydomain.com

# With POP3S (implicit TLS)
python pop3server.py \
    -s /var/mail \
    -p 1100 \
    --ssl-cert certs/server.crt \
    --ssl-key  certs/server.key \
    --ssl-port 9950 \
    --credentials users.json \
    --domain mydomain.com
```

### 5 · Send Bulk Personalised Email
```bash
# Preview without sending
python smtpclient.py \
    -H localhost:2525 \
    -c examples/recipients.csv \
    -m examples/message_template.txt \
    --dry-run

# Send with STARTTLS
python smtpclient.py \
    -H mail.mydomain.com:587 \
    -c recipients.csv \
    -m campaign.txt \
    --tls \
    -u noreply@mydomain.com \
    -P mypassword

# Send via SMTPS (implicit TLS, port 465)
python smtpclient.py \
    -H mail.mydomain.com:465 \
    -c recipients.csv \
    -m campaign.txt \
    --ssl
```

---

## Message Template Syntax

```
From: noreply@mydomain.com
Subject: Hello {{name}}, welcome to {{company}}!
Attachment: /path/to/brochure.pdf, /path/to/terms.pdf
---
Hi {{name}},

This message is personalised for you at {{company}} in {{city}}.

Best regards,
The Team
```

Variables (`{{column_name}}`) map to **CSV header names** (case-sensitive).

---

## CSV Format

```csv
name,email,company,city
Alice García,alice@example.com,Acme Corp,San José
Bob Ramírez,bob@example.org,Globex Inc,Heredia
```

The `email` column is required; all other columns become template variables.

---

## DNS Configuration (for a real domain)

To make your server receive mail for `mydomain.com`, add these DNS records:

```dns
; MX record — tells the internet where to deliver mail
mydomain.com.      IN  MX  10  mail.mydomain.com.

; A record — resolves the mail server hostname
mail.mydomain.com. IN  A      <YOUR_SERVER_PUBLIC_IP>

; PTR record — reverse DNS (set in your VPS control panel)
<IP>.in-addr.arpa. IN  PTR   mail.mydomain.com.

; Optional: SPF — reduces spam classification
mydomain.com.      IN  TXT   "v=spf1 mx ~all"
```

### Port Forwarding

| Standard Port | Dev Port | Protocol |
|:---:|:---:|---|
| 25  | 2525 | SMTP inbound (receiving) |
| 465 | 4650 | SMTPS (implicit TLS) |
| 587 | 2587 | SMTP submission (STARTTLS) |
| 110 | 1100 | POP3 |
| 995 | 9950 | POP3S (implicit TLS) |

To use standard ports without running as root:
```bash
# Redirect standard ports to high ports
sudo iptables -t nat -A PREROUTING -p tcp --dport 25  -j REDIRECT --to-port 2525
sudo iptables -t nat -A PREROUTING -p tcp --dport 465 -j REDIRECT --to-port 4650
sudo iptables -t nat -A PREROUTING -p tcp --dport 110 -j REDIRECT --to-port 1100
sudo iptables -t nat -A PREROUTING -p tcp --dport 995 -j REDIRECT --to-port 9950
```

---

## Connecting Thunderbird (POP3)

1. Open **Account Settings → Add Mail Account**
2. Enter your name, `alice@mydomain.com`, and password
3. Choose **Manual Config**:
   - **Incoming**: POP3 · server: `mail.mydomain.com` · port: `995` · SSL/TLS
   - **Outgoing**: SMTP · server: `mail.mydomain.com` · port: `465` · SSL/TLS
4. Click **Re-test**, then **Done**

---

## XMPP Notification Config (`examples/xmpp_config.json`)

```json
{
  "jid":       "mailbot@xmpp-server.com",
  "password":  "your_xmpp_password",
  "server":    "xmpp-server.com",
  "port":      5222,
  "recipient": "admin@xmpp-server.com",
  "user_mapping": {
    "alice@mydomain.com": "alice_xmpp@chat.example.org"
  }
}
```

---

## Mail Storage Layout

```
/var/mail/
  mydomain.com/
    alice/
      index.json                    ← metadata (from, subject, read status, …)
      20250417_143022_000000_ab12.eml
      20250417_160300_000000_cd34.eml
    bob/
      index.json
      …
```

---

## Security Notes

- Store `server.key` with permissions `600` and owned by the service user.
- Never commit `users.json` with real passwords to version control.
- Use hashed passwords (`password_hash`) in `users.json` for production.
- Enable firewall rules to restrict SMTP to trusted relays if needed.
- In production, obtain certificates from Let's Encrypt rather than self-signed.

---

## Architecture Diagram

```
Internet  ──[SMTP port 25/465]──►  smtpserver.py
                                        │
                                   mailstorage.py   ◄──  pop3server.py ──► Mail Clients
                                        │                                  (Thunderbird…)
                                   xmpp_notifier.py ──► XMPP Server ──► User's Phone/PC
```
