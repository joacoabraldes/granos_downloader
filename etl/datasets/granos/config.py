"""Config de la tabla de molienda de granos para el núcleo genérico (etl.core.db)."""

TABLE = "molienda_granos"
KEY_COLS = ["date"]
VALUE_COLS = ["valor", "soja", "girasol", "lino", "mani", "algodon",
              "cartamo", "canola"]
ACTUAL_VIEW = "molienda_granos_actual"
