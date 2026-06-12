"""ETL incremental del despacho de cemento (AFCP -> Supabase).

Por defecto recorre los últimos N meses y, para cada uno, intenta traer los valores
provisorio y definitivo de AFCP, insertando un snapshot sólo si es nuevo o cambió
(modelo append-only con dedup). Al terminar corre la desestacionalización (X-13).
Pensado para correr a diario por cron.

Ejemplos:
    python -m etl cemento                 # últimos 2 meses + desestacionalización
    python -m etl cemento --months-back 6
    python -m etl cemento --month 2026-04 # un mes puntual
    python -m etl cemento --force         # inserta aunque el valor no haya cambiado
    python -m etl cemento --no-desest     # saltea la desestacionalización
"""
from __future__ import annotations

import argparse
from datetime import date

from etl.core import db, seasonal
from . import config, source


def month_iter(end: date, n: int):
    """Genera los últimos n meses (primer día) hacia atrás desde `end` (inclusive)."""
    y, m = end.year, end.month
    for _ in range(n):
        yield date(y, m, 1)
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def _row_from_fields(fields: dict) -> dict:
    """Mapea el dict del parser a las columnas de la tabla (despacho_nacional->valor)."""
    return {
        "valor": fields.get("despacho_nacional"),
        "exportacion": fields.get("exportacion"),
        "consumo_despacho_nacional": fields.get("consumo_despacho_nacional"),
        "importaciones_propias": fields.get("importaciones_propias"),
    }


def process_month(conn, fecha: date, *, force: bool):
    """Trae provisorio y definitivo del mes y los snapshotea si corresponde."""
    # Si el mes ya tiene definitivo, el dato es final: no hace falta volver a
    # bajar las páginas de AFCP (salvo --force).
    if not force and db.has_estado(conn, table=config.TABLE, key_cols=config.KEY_COLS,
                                   key_vals=[fecha], estado="definitivo"):
        print(f"  {fecha:%Y-%m} ya tiene definitivo -> skip")
        return
    for estado, getter in (("provisorio", source.get_provisorio),
                           ("definitivo", source.get_definitivo)):
        try:
            fields, url = getter(fecha.year, fecha.month)
        except Exception as e:  # red caída, HTML inesperado, etc.
            print(f"  {fecha:%Y-%m} {estado:10} ERROR {e}")
            continue
        if fields is None:
            print(f"  {fecha:%Y-%m} {estado:10} no publicado")
            continue
        row = _row_from_fields(fields)
        if row["valor"] is None:
            print(f"  {fecha:%Y-%m} {estado:10} sin despacho nacional -> skip")
            continue
        changed = db.insert_if_changed(
            conn, table=config.TABLE, key_cols=config.KEY_COLS, key_vals=[fecha],
            value_cols=config.VALUE_COLS, row=row, estado=estado, fuente=url, force=force,
        )
        print(f"  {fecha:%Y-%m} {estado:10} dn={row['valor']} -> "
              f"{'inserted' if changed else 'unchanged'}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="etl cemento",
                                 description="ETL despacho de cemento AFCP")
    ap.add_argument("--months-back", type=int, default=2,
                    help="cantidad de meses hacia atrás a revisar (default 2)")
    ap.add_argument("--month", help="mes puntual YYYY-MM (ignora --months-back)")
    ap.add_argument("--force", action="store_true",
                    help="inserta snapshot aunque el valor no haya cambiado")
    ap.add_argument("--no-desest", action="store_true",
                    help="saltea la desestacionalización (X-13) al final")
    ap.add_argument("--x13-out", metavar="DIR",
                    help="guardar la salida de X-13 (html/factores/diagnósticos) en DIR")
    args = ap.parse_args(argv)

    if args.month:
        y, m = map(int, args.month.split("-"))
        months = [date(y, m, 1)]
    else:
        months = list(month_iter(date.today(), args.months_back))

    conn = db.get_conn()
    try:
        for fecha in months:
            process_month(conn, fecha, force=args.force)
        if not args.no_desest:
            try:
                seasonal.deseasonalize(conn, table=config.TABLE,
                                       source_view=config.ACTUAL_VIEW,
                                       keep_dir=args.x13_out)
            except Exception as e:  # X-13 nunca debe tumbar el ETL
                print(f"  [desest] error inesperado: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
