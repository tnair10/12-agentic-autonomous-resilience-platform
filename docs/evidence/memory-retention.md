# Memory and Safety Validation Snapshot

## Full-corpus memory test

Validated state:

- Total learned incidents: **31**
- Streamlit rows visible: **25**
- History-agent learning corpus: **31**
- Historical retrieval top-k: **5**
- History-agent validation: `HISTORY_AGENT=PASS`

This demonstrated that the Streamlit presentation limit is independent of long-term incident retention and retrieval.

## Scenario distribution at validation time

| Scenario | Retained incidents | Recovered | Safety blocked |
|---|---:|---:|---:|
| auth_failure | 4 | 4 | 0 |
| consumer_lag | 4 | 4 | 0 |
| db_latency | 5 | 5 | 0 |
| gc_storm | 4 | 3 | 1 |
| memory_pressure | 4 | 4 | 0 |
| retry_storm | 4 | 4 | 0 |
| tls_failure | 6 | 6 | 0 |

## Safety-block validation

One `gc_storm` incident was:

- diagnosed as `gc_storm`,
- assigned confidence `0.6167`,
- classified `HUMAN_APPROVAL_REQUIRED`,
- not autonomously remediated,
- persisted with `recovery_status=blocked_by_safety`,
- stored with `remediation_success=None`,
- excluded from remediation-attempt statistics because no action executed.

This validates the intended distinction:

**Incident memory retains investigated incidents. Remediation statistics describe actions that actually ran.**
