# Hostinger stable deployment

Stable hostname:

```text
https://google-forms-mcp.srv1913479.hstgr.cloud
```

Google Web OAuth callback:

```text
https://google-forms-mcp.srv1913479.hstgr.cloud/oauth/google/callback
```

## Docker Manager

1. Open VPS → Docker Manager → Compose.
2. Set the application name to `google-forms-mcp`.
3. Paste `deploy/hostinger-compose.yml` into the YAML editor.
4. In the **Environment** section, add:

   ```text
   GOOGLE_FORMS_WEB_CLIENT_ID=<the Web OAuth client ID>
   GOOGLE_FORMS_WEB_CLIENT_SECRET_VALUE=<the Web OAuth client secret>
   ```

5. Deploy.

The stack pulls a public, immutable GHCR digest, runs as UID/GID `10001`, mounts one Docker-managed data volume, drops Linux capabilities, uses a read-only root filesystem, and is routed through Hostinger Traefik with Let's Encrypt.

The stack uses a Docker-managed named volume for encrypted user credentials, hashed MCP tokens, audit events, and per-user draft databases. Back up the `google-forms-mcp-data` volume and its generated master key together.

## Verify

```bash
curl --fail https://google-forms-mcp.srv1913479.hstgr.cloud/health
```

Then complete one Google login, connect a supported MCP client with the issued token, create a draft, publish it, and disconnect the test user.

## Image updates

GitHub Actions publishes verified images to:

```text
ghcr.io/derek-suwho/google-forms-mcp
```

Production Compose pins an immutable digest. Update that digest only after its corresponding workflow run passes tests, typing, formatting, package build, image build, and container smoke tests.
