# Privacy Decoder

Analyzes Privacy Policies and EULAs in plain English using Claude AI.

## Local Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# edit .env and add your ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000
```

App runs at `http://localhost:8000/privacydecoder/`

## Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `ADMIN_API_KEY` | Secret key for admin endpoints (leave blank to disable auth) |
| `APP_HOST` | Bind host (default `0.0.0.0`) |
| `APP_PORT` | Bind port (default `8000`) |
| `MAX_DOC_CHARS` | Max characters sent to Claude (default `150000`) |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/privacydecoder/analyze` | Analyze a URL |
| `GET` | `/privacydecoder/popular` | Most-analyzed policies |
| `GET` | `/privacydecoder/history?url=...` | Version history for a URL |
| `GET` | `/privacydecoder/admin/settings` | Get admin settings |
| `POST` | `/privacydecoder/admin/settings` | Update admin settings |
| `GET` | `/privacydecoder/health` | Health check |

Admin endpoints require `X-Admin-Key` header matching `ADMIN_API_KEY`.

### Update popular list size

```bash
curl -X POST http://localhost:8000/privacydecoder/admin/settings \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your-admin-key" \
  -d '{"popular_list_size": 15}'
```

## Deployment (EC2)

```bash
# 1. Sync files
rsync -av --exclude='.env' --exclude='*.db' . ubuntu@3.236.177.73:/var/www/apps/privacy-decoder/

# 2. On server
cd /var/www/apps/privacy-decoder
pip install -r requirements.txt
playwright install chromium --with-deps

# 3. Create /etc/privacy-decoder.env with secrets

# 4. Install systemd service (see below)
```

### systemd service: `/etc/systemd/system/privacy-decoder.service`

```ini
[Unit]
Description=Privacy Decoder
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/var/www/apps/privacy-decoder
EnvironmentFile=/etc/privacy-decoder.env
ExecStart=/usr/local/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

### Nginx block

```nginx
location /privacydecoder/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 120s;
}
```
