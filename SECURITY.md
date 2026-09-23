# Security

## What the kit does with secrets

- The AppMetrica token is read-only (`appmetrica:read`) and is looked up in the environment
  variable `APPMETRICA_TOKEN`, then `<project>/analytics/.env`, then
  `~/.config/game-analytics-kit/.env`.
- It is sent only in the `Authorization` header to `api.appmetrica.yandex.ru`. It is never
  printed, logged, written to the database, reports, notes, `analytics.toml` or git; `status`
  only says where it was found. The selftest checks that it never reaches a URL.
- Advertising ids, IP addresses and operators are not downloaded unless `sync
  --with-device-ids` is given. The database stays on the machine that runs the kit.

## If a token leaked

Revoke it at <https://oauth.yandex.ru> (the app you created for the kit → tokens) and issue a
new one. A token pasted into an agent's chat should be treated as leaked.

## Reporting a vulnerability

Please do not open a public issue for a security problem (for example, a path where the
token could end up in a log, a report or a URL). Use GitHub's private vulnerability reporting
on this repository (**Security → Report a vulnerability**). You will get an answer within a
few days; a fix goes into the next release with a line in CHANGELOG.md.
