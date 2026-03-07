# combat_test

This project now includes a lightweight browser client for multi-account combat testing.

## Run as a website

```bash
python3 backend/server.py --host 0.0.0.0 --port 8080
```

Then open `http://127.0.0.1:8080` in your browser.

To test multi-account PvP:
1. Open multiple tabs/windows.
2. Login/register with different accounts.
3. Create one profile per account.
4. Connect each session and move players near each other.
5. Use **Hit** in one tab to apply knockback on another player's profile.

## Database design note

The backend now uses a peer-to-peer-oriented schema with explicit reset-and-create SQL in:

- `docs/database_refinement.md`
- `backend/sql/p2p_schema.sql`
