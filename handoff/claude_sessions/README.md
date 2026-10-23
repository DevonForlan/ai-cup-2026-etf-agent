# Claude Code session handoffs

Exact copies of Claude Code's **Owner-facing final responses** at major points (task finished, BLOCKED, Owner
Decision required, review requested, pause / handoff, significant competition / runtime status change).

Rule: `docs/COLLABORATION_WORKFLOW.md` §7.10. The latest one is linked from the relevant PR / Issue comment as
`LATEST_CLAUDE_HANDOFF = handoff/claude_sessions/<file>.md @ <commit sha>`.

## File name

`YYYY-MM-DD_<session-id>_turnNNN.md` (date in +08:00; `turnNNN` zero-padded; `turnUNK` if unknown).

## File layout

```
# Claude Code session handoff — <session-id> turn NNN

| Field | Value |
|---|---|
| Session id | <uuid> |
| Project | AI CUP 2026 玉山人工智慧公開挑戰賽 — Agent 基金經理人 |
| Repository | DevonForlan/ai-cup-2026-etf-agent |
| Timestamp | <+08:00> (<UTC>) |
| Turn | NNN |
| Trigger | task finished / BLOCKED / Owner Decision / review requested / pause / runtime change |
| Kind | LIVE (written before the response) / BACKFILL (extracted from the local transcript) |
| Verbatim sha256 | <sha256 of the text between the markers, UTF-8, LF> |

## References
branch / HEAD / PR / Issue

## State
tests · CI · Quant freeze · blockers · pending decisions

## Tool / action log (redacted)
...

## Claude:
<!-- BEGIN VERBATIM CLAUDE RESPONSE -->
<the exact response the Owner saw>
<!-- END VERBATIM CLAUDE RESPONSE -->
```

## Verify the verbatim block

```
python -c "import hashlib,re,sys;t=open(sys.argv[1],encoding='utf-8').read().replace('\r\n','\n');m=re.search(r'<!-- BEGIN VERBATIM CLAUDE RESPONSE -->\n(.*)\n<!-- END VERBATIM CLAUDE RESPONSE -->',t,re.S);print(hashlib.sha256(m.group(1).encode()).hexdigest())" <file>
```

The printed hash must equal the header's `Verbatim sha256`.

## Never in this folder

Passwords, API keys, tokens, cookies, browser storage, CSRF tokens, credential files, unnecessary account email /
personal identifiers, raw screenshots. Tool output is redacted. The response is verbatim, except that a secret inside it
is replaced by `[REDACTED]` in both the session and the file.
