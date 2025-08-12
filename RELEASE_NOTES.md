## v1.1.0 — Safer originals handling (restore-time archival)

**Highlights**
- Originals are only renamed/moved *after* a successful restore from `TDARR_OUTPUT_DIR`.
- Optional archive move and retention now execute post-restore.
- No changes to `.env` keys or their semantics.

**Why it matters**
- Avoids losing/archiving originals when Tdarr hasn’t produced output.

**Upgrade notes**
- If you previously depended on immediate archival, note the timing change.
- Consider running with `--dry-run` first and verifying logs.

**Testing checklist**
- Dry-run copy into Tdarr.
- Place a test output file in `TDARR_OUTPUT_DIR` and run: confirm rename → optional move → restore → sweep.
