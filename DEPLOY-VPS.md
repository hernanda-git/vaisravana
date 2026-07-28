# Deployment: Vaiśravaṇa bot stack on sera (this machine)

Runs entirely on this machine (sera, the Tencent Lighthouse instance in **ap-jakarta**).
There is **no cloud deploy** — Fly.io is no longer used. This document covers the
**Caddy reverse proxy + firewall lockdown** layer that wraps the
3 Dockerized bots (`gateway`, `vaisravana`, `listener`).

- **Host:** `43.157.208.115` (Lighthouse `lhins-09uls8ni`)
- **OS:** Ubuntu 24.04 LTS, 4 GB RAM, Docker 29.6 + compose v5.3.1
- **Stack root:** `/opt/bots`
- **Orchestration:** single `docker-compose.yml` on `bots-net` + a `systemd`
  unit (`bots-stack.service`) so the stack auto-starts on reboot.

---

## 1. Architecture

```
            ┌─────────────────────────────────────────────┐
 Internet ─▶│  Lighthouse (ufw)  :80  ─▶  Caddy        │
            │                              │  reverse_proxy │
            │               ┌──────────┴──────────┐        │
            │               │   bots-net (bridge)  │        │
            │   gateway:8000 ◀──/gateway*         │        │
            │   listener:9090 ◀──/listener*       │        │
            │   vaisravana  (no ingress, polls)  │        │
            └─────────────────────────────────────────────┘
```

- **Caddy is the ONLY public ingress** (`ports: "80:80"`).
- `gateway` and `listener` bind to `127.0.0.1` only — they are **not** directly
  reachable from the internet; Caddy reaches them over the `bots-net` bridge by
  service name.
- `vaisravana` has no ingress at all (it only polls Telegram + Binance outbound).

---

## 2. Firewall lockdown (ufw)

Caddy must be the sole public listener. The bots' own ports stay on loopback.

```bash
# 1. Default-deny, then allow only what is needed.
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# 2. SSH (lock to your IP if possible; otherwise leave open but key-only).
ufw allow 22/tcp

# 3. Caddy public ingress (HTTP now; add 443 in prod TLS mode).
ufw allow 80/tcp
# ufw allow 443/tcp        # uncomment in production TLS mode

# 4. The bots' real ports are on 127.0.0.1 — NOT exposed. No ufw rule needed.
#    (If you ever bind them to 0.0.0.0 by mistake, this is your safety net.)

ufw --force enable
ufw status verbose
```

> **From-the-host check:** `ss -tlnp | grep -E ':8000|:9090'` must show
> `127.0.0.1:...` (loopback), **not** `0.0.0.0:...`. Caddy shows
> `0.0.0.0:80`.

---

## 3. Caddy reverse proxy

File: `/opt/bots/Caddyfile` (mounted read-only into the `caddy` service).

### Current mode — path-routed HTTP on :80 (no domain required)

Works immediately, with **no DNS records and no certificates**:

```caddy
:80 {
    encode gzip
    handle_path /gateway*  { reverse_proxy gateway:8000 }
    handle_path /listener* { reverse_proxy listener:9090 }
    handle /up           { respond "caddy up" 200 }
    log { output stdout }
}
```

Test it:

```bash
curl -i http://43.157.208.115/gateway/health     # -> gateway /health JSON, 200
curl -i http://43.157.208.115/listener/           # -> listener (if it serves /)
curl -i http://43.157.208.115/up                 # -> "caddy up"
```

### Production mode — subdomain TLS via Cloudflare DNS-01

1. **DNS A records** at Cloudflare (zone `warga-digital.com`):
   - `gateway.warga-digital.com` → `43.157.208.115`
   - `listener.warga-digital.com` → `43.157.208.115`
2. **Cloudflare API token** (scope: `Zone → DNS → Edit`, per-zone) exported as
   `CF_API_TOKEN` (set it in the `caddy` service `environment:` block of
   `docker-compose.yml`).
3. **Uncomment** the production site blocks + `acme_dns cloudflare` global option
   in `Caddyfile`, and the `"443:443"` + `CF_API_TOKEN` lines in compose.
4. `docker compose up -d caddy` — Caddy fetches Let's Encrypt certs via the
   DNS challenge (works even if inbound :80/:443 were firewalled).

Production Caddyfile shape:

```caddy
{
    email admin@warga-digital.com
    acme_dns cloudflare {env.CF_API_TOKEN}
}
gateway.warga-digital.com  { encode gzip; reverse_proxy gateway:8000 }
listener.warga-digital.com { encode gzip; reverse_proxy listener:9090 }
```

> **Why DNS-01 instead of HTTP-01?** The Lighthouse firewall is deliberately
> tight. DNS-01 proves domain ownership through a Cloudflare TXT record, so
> Caddy needs **no inbound** :80/:443 challenge path — cleaner behind ufw.

---

## 4. Secrets handling

- All bot secrets live in `/opt/bots/<bot>/.env`, mode `600`, owner `root`.
  They were recovered from the Fly.io machines' environment and **never** passed
  through chat.
- `CF_API_TOKEN` is supplied only to the `caddy` container via compose
  `environment:` (not committed).
- The VPS SSH access uses a **dedicated** keypair, separate from the operator's
  personal `id_rsa`, so a compromised host can't touch other infra.

---

## 5. Operations

```bash
cd /opt/bots

# Status
docker compose ps
docker inspect -f '{{.State.Health.Status}}' bots-gateway

# Logs
docker logs -f bots-listener
docker logs -f bots-caddy

# Restart one service
docker compose up -d --force-recreate listener

# Full stack (also what systemd does on boot)
docker compose up -d
docker compose down

# Reboot resilience
systemctl status bots-stack
# (enabled; brings the whole stack up after `reboot`)
```

---

## 6. Rollback / recovery on this machine

All state lives on sera. To recover after a bad deploy, restart the stack:

```bash
systemctl restart bots-stack        # or: docker compose -f deploy/vps/docker-compose.yml up -d
# inspect
docker logs --tail 50 bots-vaisravana
```

There is no cloud fallback — the bot only runs here.

---

## 7. Migration checklist (as executed 2026-07-28)

- [x] VPS reachable; Binance geo-block test passed from ap-jakarta (`api`/`fapi` 200)
- [x] Docker + compose + systemd present; `/opt/bots/{gateway,vaisravana,listener}/{src,data}` created
- [x] Secrets recovered from Fly `env` → `/opt/bots/*/.env` (`600`)
- [x] Source copied (gateway 33 / vaisravana 151 / listener 172 files)
- [x] Persistent data pulled: `vaisravana.db` + `exclusions.json`; listener `trades.db` + Telethon `learnernoearner.session`
- [x] Single compose stack built; gateway healthy (`/health` 200)
- [x] `GATEWAY_URL` repointed to `http://gateway:8000` for listener
- [x] Fly machines scaled to 0 (token-conflict `409` resolved)
- [x] systemd `bots-stack.service` enabled (reboot-safe)
- [x] **Caddy reverse proxy added; bot ports bound to `127.0.0.1`**
- [x] **ufw default-deny + allow 22/80 (443 in prod); Caddy is sole ingress**
- [ ] DNS A records + Cloudflare `CF_API_TOKEN` → flip Caddyfile to production TLS mode
