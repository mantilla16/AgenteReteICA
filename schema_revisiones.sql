-- Registro historico de revisiones de ReteICA.
-- Ejecutar en la misma base de analitica-puc, despues de schema_auth.sql
-- (esta tabla referencia core.usuario).

CREATE SCHEMA IF NOT EXISTS reteica;

-- El encargo es la carpeta viva de un cliente y un periodo: los documentos
-- se acumulan ahi y NO se borran. Sobre un mismo encargo se puede revisar
-- varias veces -- se agrega el balance que faltaba, se corrige un archivo mal
-- exportado -- y cada corrida deja su propio registro en reteica.revision.
CREATE TABLE IF NOT EXISTS reteica.encargo (
  id             text PRIMARY KEY,
  usuario_id     uuid NOT NULL REFERENCES core.usuario(id) ON DELETE CASCADE,
  nit            text,
  periodo        text,
  municipio      text,
  declarado_por  text,
  razon_social   text,
  creado_en      timestamptz NOT NULL DEFAULT now(),
  actualizado_en timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_encargo_usuario
  ON reteica.encargo (usuario_id, actualizado_en DESC);

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

-- De que encargo salio esta corrida. Se agrega aparte porque la tabla ya
-- existe en produccion con revisiones dentro: las viejas quedan en NULL, que
-- es la verdad (se hicieron antes de que los documentos se conservaran).
ALTER TABLE reteica.revision
  ADD COLUMN IF NOT EXISTS encargo text REFERENCES reteica.encargo(id);

CREATE INDEX IF NOT EXISTS ix_revision_encargo
  ON reteica.revision (encargo, creado_en DESC);
