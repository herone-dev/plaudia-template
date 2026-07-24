# Plaud API transcript format

## `list_files` response shape

Each file object:
```json
{
  "id": "ca371a28571c327aa764d72bfad513c6",
  "name": "06-12 Réunion hebdomadaire: Cadrage MVP...",
  "created_at": "2026-06-15T13:47:53",
  "serial_number": "8810B30222696123",
  "start_at": "2026-06-12T18:57:11",
  "duration": "1123000"
}
```
- `duration` is in **milliseconds** — divide by 1000 for `duration_seconds`
- `start_at` maps to `recorded_at`
- `created_at` maps to `plaud_created_at`
- `serial_number` maps to `serial_number`

## `get_transcript` response shape

The API returns a **list** (not a dict), with items having `data_type`:

```json
[
  {
    "data_id": "source_transaction:eae68910:ca371a28571c327aa764d72bfad513c6",
    "data_type": "transaction",
    "data_title": "",
    "data_content": "[{\"content\": \"Hum, donc.\", \"end_time\": 1670, \"start_time\": 830, \"speaker\": \"Martin\"}, ...]"
  },
  {
    "data_id": "source_outline:eae68910:ca371a28571c327aa764d72bfad513c6",
    "data_type": "outline",
    "data_title": "",
    "data_content": "[{\"start_time\": 8430, \"end_time\": 28390, \"topic\": \"Contexte du...\"}]"
  }
]
```

### Parsing logic

```python
for item in transcript_data:
    if item.get("data_type") == "transaction":
        segments = json.loads(item.get("data_content", "[]"))
        for seg in segments:
            clean_segments.append({
                "speaker": seg.get("speaker", seg.get("original_speaker", "Speaker")),
                "original_speaker": seg.get("original_speaker", seg.get("speaker", "")),
                "content": seg.get("content", ""),
                "start_time": seg.get("start_time", 0),
                "end_time": seg.get("end_time", 0),
            })
    elif item.get("data_type") == "outline":
        pass  # Topic summaries — not stored in transcript_segments
```

### What to store in `recordings.transcript_segments`

Clean, flat array (no `data_id`/`data_type`/`data_title` wrapper):
```json
[
  {"speaker": "Martin", "original_speaker": "Speaker 1", "content": "Hum, donc.", "start_time": 830, "end_time": 1670},
  {"speaker": "Martin", "original_speaker": "Speaker 1", "content": "Oui.", "start_time": 3630, "end_time": 3790}
]
```

### `get_file` response

Returns the same fields as `list_files` but for a single file by ID:
```json
{"id": "...", "name": "...", "created_at": "...", "serial_number": "...", "start_at": "...", "duration": "..."}
```

## Notes
- `page_size` must be >= 10 (calls with smaller values return an error)
- The API requires `Accept: application/json, text/event-stream` header
- Response is SSE-framed (`event: message\ndata: {...}`) even for non-streaming calls
- Take the **last** `data:` line and `json.loads` on the remainder