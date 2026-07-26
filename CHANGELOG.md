# Changelog — Project Vaiśravaṇa

## v0.0.3 (2026-07-26)
- Fix: Dockerfile now COPYs VERSION + CHANGELOG.md into image so the bot reports the real vX.Y.Z (was falling back to 0.0.0).


## v0.0.2 (2026-07-26)
- Phase 13 versioning: VERSION file + git tag v0.0.x per deploy; bot announces vX.Y.Z + changelog on startup via Telegram; fly.toml aligned to 1m cadence.


## v0.0.1
- Versioning system introduced: repo-root VERSION file + git tag `v0.0.xxx` per deploy.
- Deployed bot now announces its version + changelog entry on startup via Telegram.
- Startup banner reports real cadence (decide=1m, ctx=5m,15m).
- Phase 12 time-sensitive 1m decision cadence with multi-timeframe (5m/15m) context.
- Phase 11 LLM research layer (propose-only, Sentinel-gated) — off by default.
