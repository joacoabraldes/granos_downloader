"""ETL incremental de la industria automotriz (ADEFA -> Supabase).

Por cada mes objetivo baja el PDF de ADEFA y snapshotea las 3 series (produccion,
ventas, expo) con estado='provisorio'. Al final desestacionaliza cada serie por
separado (X-13).

El parser del PDF de ADEFA todavía es un stub (falta el patrón de URL, generado por
JS). Hasta completarlo:
  - `python -m etl automotriz load-history` carga el histórico desde el Excel, y
  - `python -m etl automotriz` corre la desestacionalización sobre ese histórico
    (la etapa de fetch avisa y se saltea con elegancia).

Flags:
  --month YYYY-MM     procesar solo ese mes
  --months-back N     últimos N meses a revisar (default 2)
  --force             insertar snapshot aunque no haya cambiado
  --no-fetch          saltear la descarga del PDF (solo desestacionalizar el histórico)
  --no-desest         saltear la desestacionalización X-13
"""
from __future__ import annotations

import argparse
from datetime import date

import urllib3

from etl.core import db, seasonal
from . import config, source


def month_iter(end: date, n: int):
    y, m = end.year, end.month
    for _ in range(n):
        yield date(y, m, 1)
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def process_month(conn, fecha: date, *, force: bool) -> int:
    """Baja el PDF del mes y snapshotea las 3 series. Devuelve cuántas insertó."""
    try:
        data = source.get_month(fecha.year, fecha.month)
        fuente = source.pdf_url(fecha.year, fecha.month)
    except NotImplementedError as e:
        print(f"  {fecha:%Y-%m} fetch ADEFA pendiente: {e}")
        return 0
    except Exception as e:  # red caída, PDF inesperado, etc.
        print(f"  {fecha:%Y-%m} ERROR {e}")
        return 0
    if not data:
        print(f"  {fecha:%Y-%m} no publicado")
        return 0
    inserted = 0
    for serie in config.SERIES:
        valor = data.get(serie)
        if valor is None:
            continue
        if db.insert_if_changed(
            conn, table=config.TABLE, key_cols=config.KEY_COLS,
            key_vals=[serie, fecha], value_cols=config.VALUE_COLS,
            row={"valor": float(valor)}, estado="provisorio", fuente=fuente, force=force,
        ):
            inserted += 1
            print(f"  + {fecha:%Y-%m} {serie:11} provisorio valor={valor}")
    return inserted


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="etl automotriz",
                                 description="ETL automotriz ADEFA")
    ap.add_argument("--month", help="mes puntual YYYY-MM (ignora --months-back)")
    ap.add_argument("--months-back", type=int, default=2,
                    help="últimos N meses a revisar (default 2)")
    ap.add_argument("--force", action="store_true", help="insertar aunque no cambie")
    ap.add_argument("--no-fetch", action="store_true",
                    help="saltear la descarga del PDF (solo desestacionalizar)")
    ap.add_argument("--no-desest", action="store_true",
                    help="saltear la desestacionalización X-13")
    ap.add_argument("--x13-out", metavar="DIR",
                    help="guardar la salida de X-13 (html/factores/diagnósticos) en DIR")
    args = ap.parse_args(argv)
    urllib3.disable_warnings()  # cert de ADEFA (verify=False)

    if args.month:
        y, m = map(int, args.month.split("-"))
        months = [date(y, m, 1)]
    else:
        months = list(month_iter(date.today(), args.months_back))

    conn = db.get_conn()
    try:
        if not args.no_fetch:
            total = sum(process_month(conn, f, force=args.force) for f in months)
            print(f"Provisorios insertados/cambiados: {total}")

        if not args.no_desest:
            for serie in config.SERIES:
                try:
                    seasonal.deseasonalize(
                        conn, table=config.TABLE, source_view=config.ACTUAL_VIEW,
                        conflict_cols=("serie", "date"), extra_cols={"serie": serie},
                        where="serie = %s", where_params=(serie,),
                        keep_dir=args.x13_out,
                    )
                except Exception as e:  # X-13 nunca tumba el ETL
                    print(f"  [desest] {serie}: error inesperado: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
