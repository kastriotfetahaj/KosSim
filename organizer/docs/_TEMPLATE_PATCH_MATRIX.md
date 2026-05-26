# Patch Matrix — svcN

> Organizer-only. Do **not** mount into player containers.

| Field | Value |
|-------|-------|
| Service | svcN-codename |
| Stack | (language / framework) |
| Persistence | (postgres / sqlite / disk / …) |
| Interaction | (REST / WebSocket / CLI / …) |
| Flagstores | N |
| Noise variants | N |

## Vulnerability index

| Idx | Name | Flagstore | Difficulty | Discoverability | Patchability | Impact |
|----:|------|----------:|-----------:|----------------:|-------------:|-------:|
|   0 | …    |         0 |        x/5 |             x/5 |          x/5 |    x/5 |
|   1 | …    |         1 |        x/5 |             x/5 |          x/5 |    x/5 |
|   2 | …    |         2 |        x/5 |             x/5 |          x/5 |    x/5 |

For each vulnerability below, fill in every section. Do **not** add
solving clues to player-visible files; this matrix is the only place
the bug is explained in writing.

---

## vuln 0 — <short name>

### Affected flagstore
0 (variant_id=0 in checker tasks)

### Attack surface
<endpoint, protocol message, file format, …>

### Root cause
<the actual reason the bug exists — code-level>

### Exploit idea
<one paragraph>

### Exploit steps
1. …
2. …
3. …

### Why this bug is realistic
<reference a real-world equivalent if possible>

### Ratings
- Difficulty: x/5
- Discoverability: x/5
- Patchability: x/5
- Impact: x/5

### Expected solve path
<what we expect strong teams to do>

### Nearby rabbit holes
- <rabbit hole 1> — why it's not a real bug:
- <rabbit hole 2> — why it's not a real bug:

### Reference patch explanation
<what the patch changes and why>

### Regression tests
- <test 1>
- <test 2>

### Checker coverage
- PUTFLAG fsK: …
- GETFLAG fsK: …
- HAVOC checks that prevent silent regression: …

### attack_info fields
| Field | Type | Purpose |
|-------|------|---------|
| …     | …    | …       |

### Persistence notes
<does the flag survive restart? where is it stored?>

---

## vuln 1 — <short name>

(same template)

---

## vuln 2 — <short name>

(same template; remove section if service has only 2 flagstores)
