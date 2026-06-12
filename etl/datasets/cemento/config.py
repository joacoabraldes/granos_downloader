"""Config de la tabla de despacho de cemento para el núcleo genérico (etl.core.db)."""

TABLE = "cemento_despacho"
KEY_COLS = ["date"]
# La 1ª columna (valor) es el "Despacho Nacional - Del Mes"; las otras 3 solo se
# llenan en filas 'definitivo'.
VALUE_COLS = ["valor", "exportacion", "consumo_despacho_nacional",
              "importaciones_propias"]
ACTUAL_VIEW = "cemento_despacho_actual"
