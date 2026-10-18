# Hostinger stable deployment

The selected production hostname is:

```text
https://google-forms-mcp.srv1913479.hstgr.cloud
```

Google Web OAuth must authorize this exact callback:

```text
https://google-forms-mcp.srv1913479.hstgr.cloud/oauth/google/callback
```

## Host directories

```bash
sudo install -d -m 700 -o 10001 -g 10001 \
  /srv/google-forms-mcp/config \
  /srv/google-forms-mcp/data \
  /srv/google-forms-mcp/secrets

sudo install -m 600 -o 10001 -g 10001 \
  /path/to/google-web-client.json \
  /srv/google-forms-mcp/secrets/google-web-client.json
```

Copy `deploy/hostinger.env.example` to `/srv/google-forms-mcp/config/connector.env`, then enforce owner `10001:10001` and mode `0600`.

## Deploy

```bash
docker compose -f deploy/hostinger-compose.yml pull
docker compose -f deploy/hostinger-compose.yml up -d
docker compose -f deploy/hostinger-compose.yml ps
curl --fail http://127.0.0.1:8767/health
```

The Traefik labels request the stable Hostinger wildcard hostname and a Let's Encrypt certificate. Before production, replace the image tag with the immutable digest emitted by the verified GitHub Actions build.

## Verify externally

```bash
curl --fail https://google-forms-mcp.srv1913479.hstgr.cloud/health
```

Then complete one Google login, connect a supported MCP client with the issued token, create a draft, publish it, and disconnect the test user.
