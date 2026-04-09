# PelviBiz Agent API

AI Hub Agent API for intelligent carousel generation.

## Deploy

This repo deploys to the VPS with GitHub Actions on every push to `main`.

### Required GitHub secrets

- `VPS_HOST` → `185.164.110.1`
- `VPS_USER` → `root`
- `VPS_PORT` → `22`
- `VPS_SSH_KEY` → private key for the VPS

### Remote path

The backend lives at `/root/pelvibiz-agent-api` and is restarted via:

```bash
systemctl restart pelvibiz-agent-api
```
