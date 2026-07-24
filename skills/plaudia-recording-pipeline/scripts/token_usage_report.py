#!/usr/bin/env python3
"""
Per-cron-job token usage report from the local Hermes session store.

`hermes insights --days N` only aggregates by whole calendar day and can't
answer "since 21h yesterday" or isolate one cron job's spend. This script
queries ~/state.db (sibling of config.yaml — find it via `hermes config path`)
directly instead.

Usage:
    python3 token_usage_report.py <state_db_path> "<cutoff ISO datetime UTC>"

Example:
    python3 token_usage_report.py /opt/data/state.db "2026-07-08T21:00:00"
"""
import sqlite3
import sys
import re
import datetime


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    db_path, cutoff_iso = sys.argv[1], sys.argv[2]
    cutoff = datetime.datetime.fromisoformat(cutoff_iso).replace(tzinfo=datetime.timezone.utc).timestamp()

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        """SELECT title, input_tokens+output_tokens+cache_read_tokens+cache_write_tokens
           FROM sessions WHERE started_at >= ? AND source='cron'""",
        (cutoff,),
    )
    rows = c.fetchall()
    groups = {}
    for title, tot in rows:
        # cron session titles are "<job_name> · <human timestamp>"
        job = re.sub(r" · .*", "", title or "unknown")
        g = groups.setdefault(job, [0, 0])
        g[0] += 1
        g[1] += tot or 0

    total_tokens = sum(t or 0 for _, t in rows)
    print(f"Cron runs since {cutoff_iso} UTC: {len(rows)}, total tokens: {total_tokens:,}")
    for job, (cnt, tot) in sorted(groups.items(), key=lambda x: -x[1][1]):
        avg = tot // cnt if cnt else 0
        print(f"  {job}: {cnt} runs, {tot:,} tokens (avg {avg:,}/run)")


if __name__ == "__main__":
    main()
