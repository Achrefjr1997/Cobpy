# COBOL Migrator Backend

FastAPI backend for the COBOL to Python agentic migrator.

## Development

```bash
# Install dependencies
uv sync

# Run development server
uv run uvicorn cobol_migrator.api:app --reload --host 0.0.0.0 --port 8000

# Run tests
uv run pytest tests/ -v

# Run linter
uv run ruff check src/ tests/

# Format code
uv run ruff format src/ tests/
```

## API Endpoints

- `GET /health` — Health check
- `GET /api/migrations/{run_id}/events` — SSE stream for migration events
