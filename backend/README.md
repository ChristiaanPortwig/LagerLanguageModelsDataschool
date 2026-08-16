# Backend

Run from the repository root so package imports and `data/` paths are consistent:

```bash
.venv/bin/uvicorn backend.app:app --reload --port 4000
```

See the root [README](../README.md) for Docker, scheduling, persistence, and the frontend API contract. Interactive endpoint documentation is available at `/docs` while the API is running.
