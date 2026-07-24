#!/usr/bin/env python3
"""
Extract a plain-text 'Speaker : content' transcript from a persisted
mcp_plaud_get_transcript tool-result file (the /tmp/hermes-results/<id>.txt
files Hermes writes when transcript JSON is too large to inline).

Usage:
    python3 extract_transcript.py /tmp/hermes-results/<toolcall_id>.txt <out.txt>

Handles:
  - JSON preceded by non-JSON preamble (finds the first '{"result"' and uses
    raw_decode so trailing bytes after the object don't raise "Extra data").
  - `result` being either a JSON string (needs a second json.loads) or already
    a parsed list.
  - Picks the first `data_type == "transaction"` block, parses its
    `data_content` (itself a JSON string) into segments, sorts by start_time,
    and joins as "{speaker} : {content}" lines.
"""
import json
import sys


def extract(path, out_path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    idx = raw.find('{"result"')
    if idx == -1:
        print("NO_JSON_START")
        return False
    raw = raw[idx:]

    decoder = json.JSONDecoder()
    outer, _ = decoder.raw_decode(raw)  # ignores any trailing "Extra data"

    result = outer.get("result") if isinstance(outer, dict) else outer
    items = json.loads(result) if isinstance(result, str) else result

    segments = None
    for item in items:
        if item.get("data_type") == "transaction":
            segments = json.loads(item["data_content"])
            break

    if segments is None:
        print("NO_TRANSACTION_FOUND")
        return False

    segments.sort(key=lambda s: s.get("start_time", 0))

    lines = []
    for s in segments:
        spk = s.get("speaker") or s.get("original_speaker") or "?"
        content = (s.get("content") or "").strip()
        if content:
            lines.append(f"{spk} : {content}")

    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"OK segments={len(segments)} chars={len(text)}")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: extract_transcript.py <persisted_result.txt> <out.txt>")
        sys.exit(1)
    ok = extract(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 2)
