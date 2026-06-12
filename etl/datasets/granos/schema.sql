-- Esquema de la tabla de molienda de granos oleaginosos (MAGyP).
-- Modelo append-only: cada corrida inserta un snapshot nuevo con su ingested_at;
-- nunca se pisa un dato. Conviven histórico (Excel) y provisorio (HTML) del mismo mes.

create table if not exists molienda_granos (
    id          bigint generated always as identity primary key,
    date        date   not null,                 -- primer día del mes
    valor       double precision,                -- total molienda = suma de los 7 granos
    soja        double precision,
    girasol     double precision,
    lino        double precision,
    mani        double precision,
    algodon     double precision,
    cartamo     double precision,
    canola      double precision,
    estado      text,                            -- NULL=histórico (Excel) / provisorio (HTML) / desestacionalizado (X-13)
    fuente      text,                            -- URL del HTML / 'excel historico' / 'census x13'
    ingested_at timestamptz not null default now()
);

-- Búsqueda del último snapshot de un (date, estado).
create index if not exists molienda_granos_date_estado_idx
    on molienda_granos (date, estado, ingested_at desc);

-- Una sola fila desestacionalizada por mes (UPSERT desde el núcleo X-13).
create unique index if not exists molienda_granos_desest_uq
    on molienda_granos (date)
    where estado = 'desestacionalizado';

-- Serie observada "actual": último snapshot por mes, priorizando histórico (NULL)
-- sobre provisorio, excluyendo la serie desestacionalizada.
create or replace view molienda_granos_actual as
select distinct on (date)
    date, valor, soja, girasol, lino, mani, algodon, cartamo, canola,
    estado, fuente, ingested_at
from molienda_granos
where estado is distinct from 'desestacionalizado'
order by date,
         (case when estado is null then 0 when estado = 'provisorio' then 1 else 2 end),
         ingested_at desc;

-- Serie desestacionalizada (X-13), un valor por mes.
create or replace view molienda_granos_desest as
select distinct on (date)
    date, valor, fuente, ingested_at
from molienda_granos
where estado = 'desestacionalizado'
order by date, ingested_at desc;
