-- Registro historico de revisiones de ReteICA.
-- Ejecutar en la misma base de analitica-puc, despues de schema_auth.sql
-- (esta tabla referencia core.usuario).

CREATE SCHEMA IF NOT EXISTS reteica;

CREATE TABLE IF NOT EXISTS reteica.revision (
  -- El id de 12 hex que ya genera la API. Es tambien el nombre del papel en
  -- disco, asi que la fila y el archivo se encuentran el uno al otro.
  corrida        text PRIMARY KEY,

  -- De quien es. La visibilidad es por auditor: cada quien ve lo suyo.
  usuario_id     uuid NOT NULL REFERENCES core.usuario(id) ON DELETE CASCADE,

  nit            text NOT NULL,
  razon_social   text,
  periodo        text NOT NULL,          -- AAAA-MM
  municipio      text NOT NULL,
  declarado_por  text,
  creado_en      timestamptz NOT NULL DEFAULT now(),

  -- Lo que se muestra en la lista sin abrir el resumen completo.
  semaforo       text,
  conclusion     text,
  impacto_total  numeric,
  puede_concluir_limpio boolean,

  -- El _resumen() entero: controles, cifras, excepciones. En jsonb para no
  -- tener que migrar la tabla cada vez que el motor agregue un control.
  resumen        jsonb NOT NULL,

  -- Donde quedo el .xlsx. Fuera de /tmp, que se borra al reiniciar.
  ruta_papel     text NOT NULL
);

-- La lista del auditor, lo mas reciente primero.
CREATE INDEX IF NOT EXISTS ix_revision_usuario
  ON reteica.revision (usuario_id, creado_en DESC);

-- Filtrar por cliente, y ver los reprocesos de un mismo periodo juntos.
CREATE INDEX IF NOT EXISTS ix_revision_cliente
  ON reteica.revision (usuario_id, nit, periodo, creado_en DESC);
