from __future__ import annotations

import sys
from pathlib import Path

from .research import read_json, write_json


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        raise SystemExit("usage: rd_worker analyze|provider INPUT OUTPUT")
    operation, input_path, output_path = args
    source, output = Path(input_path), Path(output_path)
    if operation == "analyze":
        from .reverse import analyze_binary
        result = analyze_binary(source, output)
        write_json(output / "analysis.json", result)
    elif operation == "provider":
        from .rd_provider import request_local
        result = request_local(**read_json(source))
        write_json(output, result)
    else:
        raise SystemExit("unknown research operation")


if __name__ == "__main__":
    main()
