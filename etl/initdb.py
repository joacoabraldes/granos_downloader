"""Aplica el schema.sql de cada dataset a la base apuntada por DATABASE_URL.

Idempotente: los DDL usan `create table if not exists` / `create or replace view`.
Uso: `python -m etl init-db [granos cemento automotriz]` (sin args = todos).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etl.core import db

DATASETS_DIR = Path(__file__).parent / "datasets"
ALL = ["granos", "cemento", "automotriz"]


def apply_schema(conn, name: str) -> None:
    path = DATASETS_DIR / name / "schema.sql"
    if not path.is_file():
        print(f"  {name}: no hay schema.sql en {path}", file=sys.stderr)
        return
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    print(f"  {name}: schema aplicado ({path.name})")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="etl init-db",
                                 description="Aplica los schema.sql a DATABASE_URL.")
    ap.add_argument("datasets", nargs="*", metavar="dataset",
                    help=f"datasets a inicializar (default: todos). Opciones: {', '.join(ALL)}")
    args = ap.parse_args(argv)
    names = args.datasets or ALL
    unknown = [n for n in names if n not in ALL]
    if unknown:
        ap.error(f"dataset(s) desconocido(s): {', '.join(unknown)}")

    conn = db.get_conn()
    try:
        for name in names:
            apply_schema(conn, name)
    finally:
        conn.close()
    print("init-db OK")


if __name__ == "__main__":
    main()
