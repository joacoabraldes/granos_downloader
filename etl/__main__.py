"""CLI del monorepo de ETLs.

  python -m etl <dataset> [run|load-history] [flags]   # dataset: granos|cemento|automotriz
  python -m etl init-db [datasets...]                   # aplica los schema.sql

Ejemplos:
  python -m etl init-db
  python -m etl granos load-history
  python -m etl granos --months-back 12
  python -m etl cemento --month 2026-04
  python -m etl automotriz load-history
  python -m etl automotriz --no-fetch        # solo desestacionalizar el histórico
"""
from __future__ import annotations

import importlib
import sys

DATASETS = ["granos", "cemento", "automotriz"]
SUBCOMMANDS = {"run", "load-history"}
USAGE = (
    "uso: python -m etl <dataset> [run|load-history] [flags]\n"
    "     python -m etl init-db [datasets...]\n"
    "     python -m etl export  [datasets...] [--dir CARPETA]\n"
    f"     datasets: {', '.join(DATASETS)}"
)


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0 if argv else 2)

    cmd, rest = argv[0], argv[1:]

    if cmd == "init-db":
        importlib.import_module("etl.initdb").main(rest)
        return

    if cmd == "export":
        importlib.import_module("etl.export").main(rest)
        return

    if cmd not in DATASETS:
        print(f"dataset desconocido: {cmd!r}\n{USAGE}", file=sys.stderr)
        sys.exit(2)

    sub = "run"
    if rest and rest[0] in SUBCOMMANDS:
        sub, rest = rest[0], rest[1:]
    module = "load_history" if sub == "load-history" else "run"
    importlib.import_module(f"etl.datasets.{cmd}.{module}").main(rest)


if __name__ == "__main__":
    main()
