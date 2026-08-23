# Data Outage Log — Polymarket Smart-Money Paper-Trade

This file documents interruptions to automated data collection, for the integrity
of the pre-registered (frozen strategy v1.1) track record. Gaps caused by external
factors are logged here so the eventual writeup has an honest audit trail.

---

## Outage #1 — ISP-level regulatory block (ADM)

**Window:** 2026-07-11 → 2026-07-13 (three days). Failed scheduled runs on
07-11, 07-12, 07-13, and the 09:00 run on 07-14; access restored and the engine
re-run manually on 2026-07-14, so 07-14 data was captured.
**Status:** RESOLVED (2026-07-14)
**Impact:** No sharp signals captured on 2026-07-11, -12, -13. No new positions
opened, no resolutions recorded, `paper_ledger.csv` frozen at last successful run
(2026-07-10) until the manual re-run on 2026-07-14. Any positions the roster
traders opened, or market resolutions that fired, during 11–13 Jul are absent from
the dataset and are unrecoverable (see Backfill note).

### Symptom
The launchd job (`com.peter.polymarket-paper`, 09:00 daily) continued to fire and
exit 0 every day, but `paper_ledger.csv` stopped updating after 2026-07-10. The
job log (`paper_trader.log`) shows every one of the 116 roster-trader position
reads failing since the 2026-07-11 run with:

```
SSLError(SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: Hostname mismatch, certificate is not
valid for 'data-api.polymarket.com')
```

Because the script treats fetch failures as warnings (not fatal), it exits cleanly
with status 0, which masked the outage at the launchd level.

### Root cause
`data-api.polymarket.com` is being intercepted at the network level and redirected
to the Italian gambling regulator's (ADM / Agenzia delle Dogane e dei Monopoli)
block server. Polymarket has been added to Italy's blocklist of unlicensed
gambling operators.

Evidence gathered 2026-07-14:

- **Certificate served** by `data-api.polymarket.com:443`:
  - `subject = CN=sito-inibito-giochi.adm.gov.it, O=SOGEI, ST=Roma, C=IT`
  - `subjectAltName = sito-inibito-giochi.adm.gov.it, sito-inibito-tabacchi.adm.gov.it`
  - `issuer = Sectigo Public Server Authentication CA OV R36`
  - ("sito inibito giochi" = "inhibited gambling site"; SOGEI is the Italian
    state IT company.)
- **DNS resolution** returns the block server from *every* resolver, indicating
  transparent interception of plaintext DNS (port 53) by the ISP:
  - via ISP resolver (192.168.1.1): `data-api.polymarket.com -> 217.175.53.72`
  - via Cloudflare (1.1.1.1):        `data-api.polymarket.com -> 217.175.53.72`
  - `217.175.53.72` is the ADM/SOGEI block address.

The block is therefore **not** a Polymarket outage, an expired certificate, or a
stale local CA bundle — it is a deliberate, ISP-enforced DNS redirect.

### Remediation
Plain DNS-server changes do not work (the ISP intercepts port-53 traffic
regardless of chosen resolver). The interception operates on plaintext DNS
(port 53), so the fix was to move resolution into an encrypted channel the ISP
cannot rewrite.

**Fix applied (2026-07-14):** installed a system-wide DNS-over-HTTPS (DoH)
configuration profile pointing at Cloudflare (`Cloudflare-DoH.mobileconfig`,
endpoint `https://cloudflare-dns.com/dns-query`). Because it is system-wide, all
processes — including the launchd job — inherit it with no change to
`paper_trader.py` or the plist.

**Verification (2026-07-14):**
- `curl https://data-api.polymarket.com/positions?...` returned a valid position
  JSON payload (previously an SSL hostname-mismatch error).
- Manual run of `paper_trader.py` read roster traders successfully with no
  `[warn] GET failed` lines.
- Note: `nslookup` still shows the blocked IP because it issues its own port-53
  queries and bypasses the system DoH resolver — this is expected and not an
  indication of failure. The system resolver (used by Python/curl) is the one that
  matters.

**Resolved on:** 2026-07-14
**Backfill note:** Sharp signals for 2026-07-11, -12, -13 are unrecoverable
retroactively (the engine reads *current* positions, not history); this 3-day
window is a permanent gap in the record and must be disclosed as such in any
writeup. 2026-07-14 was captured via the manual re-run.

**Watch item:** if the ISP later escalates from DNS-only to IP/SNI filtering,
DoH will stop being sufficient and a VPN (always-on / connect-on-login) will be
required to keep the 09:00 job running. Symptom would be the same log signature
returning despite the DoH profile still installed.

---
*Last updated: 2026-07-14*
