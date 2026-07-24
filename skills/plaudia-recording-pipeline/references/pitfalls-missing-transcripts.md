# Pitfall: Recording in `transcribed` status but Plaud transcript unavailable

## Symptom
A recording has `status = 'transcribed'` in Supabase but:
- `raw_transcript` is NULL
- `transcript_segments` is NULL
- `mcp_plaud_get_transcript(file_id)` returns `[]`
- `mcp_plaud_get_note(file_id)` returns `[]`
- `mcp_plaud_get_file(file_id)` shows `note_list: []`, `source_list: []`

## Root cause
The Plaud device recorded the audio file, but Plaud's transcription engine never generated a transcript for it. Common causes:
- Recording stopped before transcription completed
- Audio file imported from external source (not recorded via Plaud app)
- Transient Plaud service issue
- Very short recording (< 30s) — Plaud may skip transcription

## Handling in the pipeline
Do NOT retry or loop — the recording will never get a transcript from Plaud. Instead:

1. **Set `status = 'error'`** with a descriptive message:
   ```sql
   UPDATE recordings SET status = 'error',
     error_message = 'Transcript Plaud indisponible (API get_transcript retourne []) — fichier audio sans transcription générée par Plaud',
     updated_at = now()
   WHERE id = '<recording_id>';
   ```

2. **Report** the affected recordings in the cron output (file ID, date, duration).

3. **User action required**: Either re-record via the Plaud app (with transcription active) or upload a manual transcript to `raw_transcript` and `transcript_segments`, then reset status to `'pending'`.

## Verification
After marking as error, the recording should NOT appear in:
```sql
SELECT id FROM recordings WHERE status = 'transcribed';
```