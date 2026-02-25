# Security Policy

## Supported Versions

We support the latest release with security updates. Older versions may receive critical patches at our discretion.

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, report security issues privately:

### Email

Send to: **jcap93@pm.me**

Subject: `[SECURITY] Pulse - <brief description>`

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if you have one)

### Response Timeline

- **Acknowledgment:** Within 48 hours
- **Initial assessment:** Within 1 week
- **Fix timeline:** Depends on severity (critical = days, low = next release)
- **Disclosure:** After patch is released (coordinated disclosure)

### What to Expect

1. We'll confirm receipt and assess severity
2. We'll develop a fix and prepare a patch release
3. We'll notify you when the patch is ready
4. We'll publish a security advisory after the fix is released
5. We'll credit you (if you want) in the advisory

### Scope

**In scope:**
- Authentication/authorization bypass
- Remote code execution
- Sensitive data exposure (tokens, credentials)
- Denial of service (if critical)
- Injection vulnerabilities (command, SQL, etc.)

**Out of scope:**
- Social engineering
- Physical attacks
- Issues in third-party dependencies (report to them directly)
- Theoretical vulnerabilities without proof of concept

## Security Best Practices

When deploying Pulse:

1. **Protect your webhook token**
   - Use environment variables, not hardcoded values
   - Restrict file permissions on config files (600)
   - Never commit `.env` or `pulse.yaml` with real tokens

2. **Run with least privilege**
   - Don't run Pulse as root
   - Use dedicated service accounts
   - Limit file system access via permissions

3. **Network security**
   - Bind API to localhost only (default)
   - Use firewall rules if exposing publicly
   - Enable authentication for remote access (future feature)

4. **Keep Pulse updated**
   - Subscribe to GitHub releases
   - Apply security patches promptly
   - Review CHANGELOG.md for security notes

5. **Monitor logs**
   - Check for unusual trigger patterns
   - Review mutation audit logs
   - Alert on authentication failures (when auth is added)

## Known Issues

None currently. Check [GitHub Security Advisories](https://github.com/astra-ventures/pulse/security/advisories) for updates.

## Security Features

- **No external calls** — Pulse doesn't phone home or leak data
- **Local-first** — All state stored on your machine
- **Audit trail** — Self-modifications logged to audit file
- **Guardrails** — Mutation system prevents self-disabling
- **Rate limiting** — Prevents runaway triggers

## Future Security Enhancements

Planned for upcoming releases:

- API key authentication (v0.3)
- HTTPS support (v0.3)
- Webhook signature verification (v0.4)
- Encrypted state storage (v0.5)

## Questions?

Security questions? Email jcap93@pm.me or ask in [Discord](https://discord.com/invite/clawd) (#pulse channel, for non-sensitive questions).

---

**Thank you for helping keep Pulse secure!** 🔒
