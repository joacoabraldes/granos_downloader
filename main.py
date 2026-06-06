"""ETL incremental de molienda de oleaginosas (provisorios desde el HTML).

Por defecto revisa los últimos N meses publicados en el HTML y hace insert-if-changed
con estado='provisorio'. Al final corre la desestacionalización X-13 (salvo --no-desest).

Flags:
  --month YYYY-MM     procesar solo ese mes
  --months-back N     procesar los últimos N meses publicados (default 6)
  --force             insertar snapshot aunque no haya cambiado
  --no-desest         saltear la etapa de desestacionalización
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import urllib3

import db
import magyp

ESTADO = "provisorio"


def parse_month(s: str) -> dt.date:
    return dt.datetime.strptime(s, "%Y-%m").date().replace(day=1)


def target_dates(parsed: dict[dt.date, dict], month: str | None,
                 months_back: int) -> list[dt.date]:
    """Lista de meses a procesar, dentro de los que trae el HTML."""
    available = sorted(parsed)
    if month:
        d = parse_month(month)
        return [d] if d in parsed else _missing(d, available)
    return available[-months_back:] if months_back > 0 else available


def _missing(d: dt.date, available: list[dt.date]) -> list[dt.date]:
    print(f"[warn] {d:%Y-%m} no está publicado en el HTML "
          f"(rango {available[0]:%Y-%m}..{available[-1]:%Y-%m}).", file=sys.stderr)
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description="ETL incremental molienda oleaginosas.")
    ap.add_argument("--month", help="procesar solo este mes (YYYY-MM)")
    ap.add_argument("--months-back", type=int, default=6,
                    help="últimos N meses publicados a revisar (default 6)")
    ap.add_argument("--force", action="store_true", help="insertar aunque no cambie")
    ap.add_argument("--no-desest", action="store_true",
                    help="saltear desestacionalización X-13")
    args = ap.parse_args()

    urllib3.disable_warnings()
    html = magyp.fetch_html()
    parsed = magyp.parse_molienda(html)
    if not parsed:
        print("No se parseó ningún mes del HTML.", file=sys.stderr)
        sys.exit(1)

    dates = target_dates(parsed, args.month, args.months_back)
    print(f"HTML: {len(parsed)} meses ({min(parsed):%Y-%m}..{max(parsed):%Y-%m}). "
          f"A procesar: {len(dates)}")

    conn = db.get_conn()
    inserted = 0
    try:
        for d in dates:
            row = parsed[d]
            if db.insert_if_changed(conn, d, row, estado=ESTADO,
                                    fuente=magyp.PAGE_URL, force=args.force):
                inserted += 1
                print(f"  + {d:%Y-%m}  provisorio  valor={row['valor']:.0f}")
        print(f"Provisorios insertados/cambiados: {inserted}  |  "
              f"sin cambios: {len(dates) - inserted}")

        if not args.no_desest:
            try:
                import seasonal
                seasonal.run_desest(conn)
            except Exception as e:  # degradación elegante: el ETL no se rompe
                print(f"[desest] saltado: {e}", file=sys.stderr)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
