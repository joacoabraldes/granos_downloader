"""Monorepo de ETLs mensuales (granos / cemento / automotriz) hacia Supabase.

Núcleo compartido en `etl.core`; cada serie vive en `etl.datasets.<nombre>` con su
propio `source.py` (scraping/parsing), `load_history.py`, `run.py`, `config.py` y
`schema.sql`. CLI: `python -m etl <dataset> [run|load-history] [flags]`.
"""
