"""Desestacionalización Census X-13ARIMA-SEATS, llamando al binario directo.

Reutilizable entre ETLs: toma una serie mensual observada (1 valor por mes) desde una
vista, corre X-13 y hace UPSERT del resultado como estado 'desestacionalizado' (1 fila por
mes que se actualiza en cada corrida).

No depende de statsmodels: arma el .spc, ejecuta x13as y lee la tabla d11 (serie
desestacionalizada por X-11). Funciona con el binario "html" (x13ashtml) renombrado a
x13as, que es el que se consigue precompilado para Linux.

Requisitos: binario x13as accesible y `X13PATH` apuntando a su carpeta (o al binario).

Si falta X13PATH/el binario, NO rompe: avisa y saltea (devuelve "skipped"), así el ETL y
la demo en Windows siguen andando (la desest se corre aparte, p.ej. en una VM Linux).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from datetime import date

MIN_MESES = 36           # X-13 necesita varios años de historia
VALORES_POR_LINEA = 10   # X-13 corta líneas de input a ~132 chars


def _x13_binary():
    """Ruta al binario x13as a partir de X13PATH (carpeta o archivo), o None."""
    x13path = os.environ.get("X13PATH")
    if not x13path:
        return None
    if os.path.isfile(x13path):
        return x13path
    for name in ("x13as", "x13as.exe", "x13ashtml"):
        cand = os.path.join(x13path, name)
        if os.path.isfile(cand):
            return cand
    return None


def _es_contigua(dates) -> bool:
    """True si la lista de fechas (primer día de mes) es mensual sin huecos."""
    for a, b in zip(dates, dates[1:]):
        esperado_mes = a.month % 12 + 1
        esperado_anio = a.year + (1 if a.month == 12 else 0)
        if (b.year, b.month) != (esperado_anio, esperado_mes):
            return False
    return True


def _write_spc(path, dates, values, mode=None):
    """Escribe el .spc de X-13 con los datos wrapeados a VALORES_POR_LINEA por línea.

    `mode` = modo del X-11 ('add' aditivo / None = default multiplicativo). El
    multiplicativo no admite valores <= 0; para series con ceros/negativos usar 'add'.
    """
    y, m = dates[0].year, dates[0].month
    nums = [f"{v:.3f}" for v in values]
    bloques = ["  " + " ".join(nums[i:i + VALORES_POR_LINEA])
               for i in range(0, len(nums), VALORES_POR_LINEA)]
    data = "\n".join(bloques)
    x11_opts = "save=(d11)" if not mode else f"mode={mode} save=(d11)"
    spc = (
        f'series{{ title="serie" start={y}.{m:02d} period=12\n'
        f' data=(\n{data}\n ) }}\n'
        f'x11{{ {x11_opts} }}\n'
    )
    with open(path, "w") as f:
        f.write(spc)


def _parse_d11(path):
    """Lee la tabla d11 -> lista de (date primer-día-de-mes, valor)."""
    out = []
    with open(path) as f:
        for ln in f:
            parts = ln.split()
            if len(parts) != 2:
                continue
            ym, val = parts
            if not (len(ym) == 6 and ym.isdigit()):
                continue  # saltea header y separador
            out.append((date(int(ym[:4]), int(ym[4:6]), 1), round(float(val), 3)))
    return out


def deseasonalize(conn, *, table, source_view, conflict_cols=("date",),
                  extra_cols=None, where=None, where_params=(),
                  out_estado="desestacionalizado", fuente="census x13") -> str:
    """Corre X-13 sobre la serie observada y hace UPSERT de la desestacionalizada.

    - `source_view`   vista con (date, valor) de la serie observada.
    - `where`/`where_params`  filtro opcional sobre la vista (p.ej. por `serie`).
    - `extra_cols`    columnas fijas a setear en cada fila insertada (p.ej. {"serie": ...}).
    - `conflict_cols` columnas del índice parcial único (target del ON CONFLICT).

    Devuelve "ok", "skipped" o "error".
    """
    x13bin = _x13_binary()
    if not x13bin:
        print("  [desest] X13PATH no seteado o binario x13as no encontrado -> se saltea")
        return "skipped"

    extra_cols = dict(extra_cols or {})

    # 1. Serie observada (1 valor por mes) desde la vista.
    sql = f"select date, valor from {source_view}"
    if where:
        sql += f" where {where}"
    sql += " order by date"
    with conn.cursor() as cur:
        cur.execute(sql, where_params)
        rows = cur.fetchall()
    if len(rows) < MIN_MESES:
        print(f"  [desest] serie demasiado corta ({len(rows)} meses) -> se saltea")
        return "skipped"
    dates = [r[0] for r in rows]
    values = [float(r[1]) for r in rows]
    if not _es_contigua(dates):
        print("  [desest] la serie tiene huecos mensuales -> se saltea")
        return "skipped"

    # 2. Correr x13as en un directorio temporal.
    # El X-11 multiplicativo (default) no admite valores <= 0; si la serie tiene algún
    # cero/negativo (p.ej. produccion abril-2020, COVID), usamos modo aditivo.
    mode = "add" if any(v <= 0 for v in values) else None
    if mode:
        print(f"  [desest] serie con valores <= 0 -> X-11 aditivo (mode=add)")
    workdir = tempfile.mkdtemp(prefix="x13_")
    base = "serie"
    _write_spc(os.path.join(workdir, base + ".spc"), dates, values, mode=mode)
    try:
        subprocess.run([x13bin, base], cwd=workdir, capture_output=True,
                       text=True, timeout=120)
    except Exception as e:
        print(f"  [desest] no se pudo ejecutar x13as: {e}")
        return "error"

    d11 = os.path.join(workdir, base + ".d11")
    if not os.path.isfile(d11):
        print(f"  [desest] X-13 no produjo d11. Revisar {workdir}/{base}_err.html")
        return "error"
    series = _parse_d11(d11)

    # 3. UPSERT: 1 fila por mes con estado=out_estado (se actualiza cada corrida).
    cols = list(extra_cols) + ["date", "valor", "estado", "fuente"]
    placeholders = ", ".join(["%s"] * len(cols))
    target = ", ".join(conflict_cols)
    sql = (
        f"insert into {table} ({', '.join(cols)}) values ({placeholders}) "
        f"on conflict ({target}) where estado = '{out_estado}' "
        f"do update set valor = excluded.valor, ingested_at = now()"
    )
    fixed = list(extra_cols.values())
    with conn.cursor() as cur:
        for d, val in series:
            cur.execute(sql, fixed + [d, val, out_estado, fuente])
    conn.commit()

    shutil.rmtree(workdir, ignore_errors=True)
    tag = " ".join(f"{k}={v}" for k, v in extra_cols.items())
    print(f"  [desest] {len(series)} meses desestacionalizados "
          f"(UPSERT{', ' + tag if tag else ''}, fuente='{fuente}')")
    return "ok"
