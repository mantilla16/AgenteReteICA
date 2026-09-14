-- Esquema de autenticacion para Motor de Revision de ReteICA.
-- Ejecutar en la misma base de datos de analitica-puc.
-- Reutiliza las tablas core.usuario, core.sesion y core.codigo_acceso
-- que ya existen del esquema de analitica-puc.

-- Si las tablas NO existen (base nueva), crearlas:
CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.usuario (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  usuario        text NOT NULL UNIQUE,
  nombre         text NOT NULL,
  correo         text,
  clave_hash     text,
  rol            text NOT NULL DEFAULT 'AUDITOR',
  activo         boolean NOT NULL DEFAULT true,
  creado_en      timestamptz NOT NULL DEFAULT now(),
  ultimo_acceso  timestamptz,
  cargo          text,
  registrado_en  timestamptz
);

CREATE TABLE IF NOT EXISTS core.sesion (
  token_hash  text PRIMARY KEY,
  usuario_id  uuid NOT NULL REFERENCES core.usuario(id) ON DELETE CASCADE,
  creada_en   timestamptz NOT NULL DEFAULT now(),
  expira_en   timestamptz NOT NULL,
  agente      text
);

CREATE INDEX IF NOT EXISTS ix_sesion_usuario ON core.sesion (usuario_id);
CREATE INDEX IF NOT EXISTS ix_sesion_expira  ON core.sesion (expira_en);

CREATE TABLE IF NOT EXISTS core.codigo_acceso (
  id           bigserial PRIMARY KEY,
  correo       text        NOT NULL,
  codigo_hash  text        NOT NULL,
  creado_en    timestamptz NOT NULL DEFAULT now(),
  expira_en    timestamptz NOT NULL,
  intentos     integer     NOT NULL DEFAULT 0,
  usado_en     timestamptz,
  ip           text,
  agente       text
);

CREATE INDEX IF NOT EXISTS ix_codigo_correo
  ON core.codigo_acceso (lower(correo), creado_en DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_usuario_correo
  ON core.usuario (lower(correo)) WHERE correo IS NOT NULL;
