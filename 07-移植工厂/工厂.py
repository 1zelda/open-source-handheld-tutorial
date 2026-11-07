import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = Path("F:/_scratch/portfactory_env/Scripts/python.exe")

if __name__ == "__main__":
    if VENV_PYTHON.is_file() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        raise SystemExit(subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]))
    sys.path.insert(0, str(ROOT))
    from portfactory.cli import main
    raise SystemExit(main())
