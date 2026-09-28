# COBOL to Python Agentic Migrator

An AI-powered tool that automatically translates COBOL programs to Python using a multi-agent architecture with LangGraph. The system validates the input COBOL first, then iteratively translates, tests, and refines the output until the Python code produces equivalent results — reporting a final verdict with a confidence score.

## Features

- **COBOL Validation First**: Compiles input COBOL with GnuCOBOL before translation; stops immediately if the source has errors
- **Multi-provider LLM Support**: OpenAI, Anthropic (Claude), Google (Gemini), and xAI (Grok)
- **Agentic Translation Loop**: Iterative refinement with automated testing and reflection
- **Four-tier Validation Stack**:
  - Differential testing (COBOL vs Python output comparison)
  - Property-based testing (with Hypothesis)
  - LLM-as-Judge semantic equivalence evaluation
  - Static analysis (with Pyflakes/Ruff)
- **Confidence Scoring**: Final verdict includes a confidence percentage based on weighted validator results
- **File Upload**: Upload `.cbl`/`.cob` files directly or paste code
- **Downloadable Output**: Download the generated Python file after migration
- **Synthetic Test Data**: Auto-generates dummy input files with synthetic data for file-dependent COBOL programs
- **Real-time Progress**: Server-Sent Events (SSE) for live agent reasoning updates
- **Isolated Test Execution**: Sandboxed environment with virtual environments in a dedicated `test_runs/` folder, cleaned up after each run
- **Migration History**: SQLite persistence for all migration records
- **Cross-platform**: Setup and run scripts for both Linux/macOS and Windows

## Prerequisites

Before running the setup script, ensure you have:

- **Python 3.11+** — [Download](https://www.python.org/downloads/)
- **Node.js 18+** — [Download](https://nodejs.org/)
- **GnuCOBOL** (optional but recommended) — enables COBOL compilation validation and differential testing
- **curl** (Linux/macOS) or **PowerShell** (Windows) — for installing `uv`
- **git**

### Check your versions:
```bash
python3 --version   # Should be 3.11 or higher
node --version      # Should be v18 or higher
cobc --version      # Optional: GnuCOBOL compiler
```

### Installing GnuCOBOL (optional):
```bash
# Ubuntu/Debian
sudo apt install gnucobol

# macOS
brew install gnucobol

# Windows (via MSYS2 or Chocolatey)
choco install gnucobol
```

## Quick Start

### 1. Clone the Repository
```bash
https://github.com/Achrefjr1997/Cobpy.git
cd Cobpy
```

### 2. Run Setup

**Linux / macOS:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows:**
```cmd
setup.bat
```

This will:
- Install `uv` (Python package manager) if not present
- Install all Python dependencies via `uv sync`
- Install all Node.js dependencies via `npm install`
- Create `.env` from `.env.example`
- Create required directories (`logs/`, `data/`)

### 3. Configure Your API Key

Edit `backend/.env` and add your LLM provider API key:

```bash
# Choose your provider
LLM_PROVIDER=openai  # Options: openai, anthropic, google, xai

# Add your API key (only the key for your selected provider is required)
OPENAI_API_KEY=sk-your-actual-key-here
```

### 4. Start the Application

**Linux / macOS:**
```bash
./run.sh
```

**Windows:**
```cmd
run.bat
```

The application will be available at:
- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **Health Check**: http://localhost:8000/health

Press `Ctrl+C` to stop both servers.

## Usage

1. Open http://localhost:5173 in your browser
2. Choose input method:
   - **Paste Code**: Type or paste COBOL source directly in the editor
   - **Upload File**: Drag-and-drop or browse for a `.cbl`, `.cob`, `.cobol`, or `.txt` file
3. (Optional) Check "Create mock files with synthetic data" if your COBOL reads from external files
4. Click **Start Migration**
5. Watch the agent:
   - **Validate COBOL** — compiles the input code (stops if errors found)
   - **Analyze** — extracts program summary and I/O contract
   - **Translate** — generates Python code
   - **Generate & Run Tests** — creates pytest tests and runs them in isolation
   - **Validate** — compares COBOL and Python outputs, runs LLM judge and static analysis
   - **Reflect** — learns from failures and retries if needed
6. View the final Python code in the right panel with verdict and confidence score
7. **Download** the `.py` file or **Copy** to clipboard

## Run Modes

**Linux / macOS:**
```bash
./run.sh              # Development mode (auto-reload on code changes)
./run.sh --no-reload  # Stable mode (recommended for actual migrations)
```

**Windows:**
```cmd
run.bat               # Development mode (auto-reload)
run.bat --no-reload   # Stable mode
```

## Migration Flow

```
Input COBOL
    │
    ▼
┌─────────────────┐
│ VALIDATE COBOL  │──── Compilation error? ──► STOP (report error)
└────────┬────────┘
         │ ✓ Compiles OK
         ▼
┌─────────────────┐
│    ANALYZE      │  Extract program summary & I/O contract
└────────┬────────┘
         ▼
┌─────────────────┐
│   TRANSLATE     │  LLM generates Python code
└────────┬────────┘
         ▼
┌─────────────────┐
│  GEN_TESTS +    │  Generate & run pytest in isolated venv
│  RUN_TESTS      │──── Tests fail? ──► REFLECT ──► retry TRANSLATE
└────────┬────────┘
         │ ✓ Tests pass
         ▼
┌─────────────────┐
│   VALIDATE      │  Differential + Property + LLM Judge + Static
└────────┬────────┘
         ▼
┌─────────────────┐
│   FINALIZE      │  Save to DB, emit verdict + confidence score
└─────────────────┘
```

## Project Structure

```
.
├── backend/
│   ├── src/cobol_migrator/
│   │   ├── agent/              # LangGraph agent implementation
│   │   │   └── nodes/          # Agent nodes:
│   │   │       ├── validate_cobol.py  # COBOL compilation check
│   │   │       ├── planner.py         # Decides next action
│   │   │       ├── analyze.py         # Extracts I/O contract
│   │   │       ├── translate.py       # LLM-based translation
│   │   │       ├── gen_tests.py       # Test generation
│   │   │       ├── run_tests.py       # Isolated test execution
│   │   │       ├── validate.py        # 4-validator stack
│   │   │       ├── reflect.py         # Failure analysis
│   │   │       └── finalize.py        # Persistence + verdict
│   │   ├── validators/         # Differential, property, LLM judge, static
│   │   ├── api.py              # FastAPI endpoints (REST + SSE + file upload)
│   │   ├── models.py           # LLM provider abstraction
│   │   ├── config.py           # Configuration management
│   │   ├── safety.py           # AST-based code safety checks
│   │   ├── test_environment.py # Isolated venv test runner
│   │   └── dummy_files.py      # Synthetic data file generation
│   └── tests/                  # Backend tests
├── frontend/
│   └── src/
│       ├── App.tsx             # Main UI (3-panel layout)
│       └── lib/api.ts          # API client + SSE subscription
├── stages/                     # Project planning documents
├── setup.sh                    # Linux/macOS setup
├── setup.bat                   # Windows setup
├── run.sh                      # Linux/macOS dev server
├── run.bat                     # Windows dev server
└── CLAUDE.md                   # Coding conventions
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/migrations` | Start migration from code snippet |
| `POST` | `/api/migrations/upload` | Start migration from uploaded file |
| `GET` | `/api/migrations/{run_id}/events` | SSE event stream |
| `GET` | `/api/migrations/{run_id}` | Get migration status |
| `GET` | `/api/migrations/{run_id}/download` | Download generated Python file |
| `POST` | `/api/migrations/{run_id}/stop` | Cancel a running migration |
| `GET` | `/api/migrations` | List migration history |

## Supported LLM Providers

| Provider | Models | Environment Variable |
|----------|--------|---------------------|
| OpenAI | gpt-4o, gpt-4o-mini, gpt-4-turbo, o1 | `OPENAI_API_KEY` |
| Anthropic | claude-sonnet-4-20250514, claude-haiku-4-20250514 | `ANTHROPIC_API_KEY` |
| Google | gemini-2.0-flash, gemini-1.5-pro | `GOOGLE_API_KEY` |
| xAI | grok-2, grok-2-mini | `XAI_API_KEY` |
| Fireworks | llama-v3p1-405b-instruct, etc. | `FIREWORKS_API_KEY` |

Configure models per task in `backend/.env`:
```bash
OPENAI_TRANSLATE_MODEL=gpt-4o
OPENAI_ANALYZE_MODEL=gpt-4o-mini
# ... etc
```

## Example COBOL Input

```cobol
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY "HELLO, WORLD".
           STOP RUN.
```

## Troubleshooting

### Port already in use (Linux/macOS)
The `run.sh` script automatically clears ports 8000 and 5173. If issues persist:
```bash
fuser -k 8000/tcp
fuser -k 5173/tcp
```

### Port already in use (Windows)
```cmd
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

### uv not found after setup
**Linux/macOS** — add to your shell profile (`~/.bashrc` or `~/.zshrc`):
```bash
export PATH="$HOME/.local/bin:$PATH"
```
**Windows** — restart your terminal or run:
```cmd
set PATH=%USERPROFILE%\.local\bin;%PATH%
```

### GnuCOBOL not installed
The migrator works without GnuCOBOL — it will skip COBOL compilation validation and differential testing. Install it for the full validation experience.

### API key errors
Ensure your `.env` file has the correct key for your chosen provider and that `LLM_PROVIDER` matches.

## Development

### Run Backend Tests
```bash
cd backend
uv run pytest                    # Fast tests only
uv run pytest -m slow            # Include slow integration tests
uv run ruff check src tests      # Linting
uv run ruff format src tests     # Formatting
```

### Frontend Development
```bash
cd frontend
npm run lint                     # ESLint
npm run build                    # Production build
```

## License

This project was created for IE624 coursework.
