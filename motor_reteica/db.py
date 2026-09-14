"""
Capa de base de datos para sesiones y usuarios.

Usa la misma PostgreSQL de analitica-puc.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DSN = os.getenv(
    "AUDITORIA_DSN",
    "postgresql://postgres:postgres@localhost:5432/auditoria_puc",
)

pool = ConnectionPool(DSN, min_size=1, max_size=4, open=False)


def abrir() -> None:
    pool.open()


def cerrar() -> None:
    pool.close()


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    with pool.connection() as c:
        c.row_factory = dict_row
        yield c


def uno(sql: str, p: tuple = ()) -> dict | None:
    with conn() as c:
        return c.execute(sql, p).fetchone()


def varios(sql: str, p: tuple = ()) -> list[dict]:
    with conn() as c:
        return c.execute(sql, p).fetchall()


def ejecutar(sql: str, p: tuple = ()) -> None:
    with conn() as c:
        c.execute(sql, p)
        c.commit()


# =====================================================================
# USUARIOS
# =====================================================================

def usuario_por_correo(correo: str) -> dict | None:
    return uno("SELECT * FROM core.usuario WHERE lower(correo)=lower(%s)",
               (correo,))


def usuario_por_id(usuario_id: str) -> dict | None:
    return uno("SELECT * FROM core.usuario WHERE id=%s", (usuario_id,))


def crear_usuario_por_correo(correo: str, usuario: str) -> dict:
    return uno(
        """INSERT INTO core.usuario (usuario, nombre, correo, rol, registrado_en)
           VALUES (%s,%s,%s,'AUDITOR',NULL) RETURNING *""",
        (usuario, correo, correo),
    )


def actualizar_usuario(usuario_id: str, **campos: Any) -> dict | None:
    if not campos:
        return usuario_por_id(usuario_id)
    sets = ", ".join(f"{k}=%s" for k in campos)
    return uno(
        f"""UPDATE core.usuario SET {sets} WHERE id=%s RETURNING *""",
        (*campos.values(), usuario_id),
    )


# =====================================================================
# SESIONES
# =====================================================================

def crear_sesion(token_hash: str, usuario_id: str, expira_en: datetime,
                 agente: str | None) -> None:
    with conn() as c:
        c.execute(
            """INSERT INTO core.sesion (token_hash, usuario_id, expira_en, agente)
               VALUES (%s,%s,%s,%s)""",
            (token_hash, usuario_id, expira_en, agente),
        )
        c.execute("UPDATE core.usuario SET ultimo_acceso=now() WHERE id=%s",
                  (usuario_id,))
        c.execute("DELETE FROM core.sesion WHERE expira_en < now()")
        c.commit()


def usuario_de_sesion(token_hash: str) -> dict | None:
    return uno(
        """SELECT u.id, u.usuario, u.nombre, u.correo, u.rol, u.activo,
                  u.cargo, u.registrado_en
           FROM core.sesion s JOIN core.usuario u ON u.id = s.usuario_id
           WHERE s.token_hash=%s AND s.expira_en > now() AND u.activo""",
        (token_hash,),
    )


def borrar_sesion(token_hash: str) -> None:
    ejecutar("DELETE FROM core.sesion WHERE token_hash=%s", (token_hash,))


# =====================================================================
# CODIGOS DE ACCESO
# =====================================================================

def codigos_recientes(correo: str, desde: datetime) -> int:
    return uno(
        """SELECT count(*) AS n FROM core.codigo_acceso
            WHERE lower(correo)=lower(%s) AND creado_en >= %s""",
        (correo, desde),
    )["n"]


def crear_codigo(correo: str, codigo_hash: str, expira_en: datetime,
                 ip: str | None, agente: str | None) -> dict:
    return uno(
        """INSERT INTO core.codigo_acceso
             (correo, codigo_hash, expira_en, ip, agente)
           VALUES (%s,%s,%s,%s,%s) RETURNING id, creado_en, expira_en""",
        (correo, codigo_hash, expira_en, ip, agente),
    )


def codigo_vigente(correo: str) -> dict | None:
    return uno(
        """SELECT * FROM core.codigo_acceso
            WHERE lower(correo)=lower(%s) AND usado_en IS NULL
            ORDER BY creado_en DESC LIMIT 1""",
        (correo,),
    )


def sumar_intento(codigo_id: int) -> int:
    return uno(
        """UPDATE core.codigo_acceso SET intentos = intentos + 1
            WHERE id=%s RETURNING intentos""",
        (codigo_id,),
    )["intentos"]


def consumir_codigo(codigo_id: int) -> None:
    ejecutar("UPDATE core.codigo_acceso SET usado_en=now() WHERE id=%s",
             (codigo_id,))
