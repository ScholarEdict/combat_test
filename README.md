# combat_test

This project includes a lightweight browser client for multi-account combat testing.

## Run as website

```bash
python3 backend/server.py --host 0.0.0.0 --port 8080
```

Open: `http://127.0.0.1:8080`

## Browser flow (per tab/account)

1. Register account.
2. Login.
3. Create or select profile.
4. Click **Play** (calls `POST /play/start`).
5. Move near another profile and use **Hit**.

## Database design note

See `docs/database_refinement.md` for schema rationale.
