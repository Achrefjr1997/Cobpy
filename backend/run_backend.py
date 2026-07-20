import sys
from pathlib import Path

src = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src))

import uvicorn

if __name__ == "__main__":
    reload = "--reload" in sys.argv or "-r" in sys.argv
    uvicorn.run(
        "cobol_migrator.api:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
    )
