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


# =====================================================================
# REVISIONES
# =====================================================================
#
# La visibilidad es por auditor: cada consulta lleva usuario_id en el WHERE,
# no se filtra despues en Python. Una revision de ReteICA lleva cifras de un
# cliente concreto, y el que no es su dueno no la debe recibir ni de paso.

def guardar_revision(corrida: str, usuario_id: str, nit: str,
                     razon_social: str | None, periodo: str, municipio: str,
                     declarado_por: str | None, resumen: dict,
                     ruta_papel: str, encargo: str | None = None) -> None:
    semaforo = (resumen.get("semaforo") or {}).get("color")
    ejecutar(
        """INSERT INTO reteica.revision
             (corrida, usuario_id, nit, razon_social, periodo, municipio,
              declarado_por, semaforo, conclusion, impacto_total,
              puede_concluir_limpio, resumen, ruta_papel, encargo)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (corrida, usuario_id, nit, razon_social, periodo, municipio,
         declarado_por, semaforo, resumen.get("conclusion"),
         resumen.get("impacto_total"), resumen.get("puede_concluir_limpio"),
         json.dumps(resumen, default=str), ruta_papel, encargo),
    )


def crear_revision_en_proceso(corrida: str, usuario_id: str, nit: str,
                              periodo: str, municipio: str,
                              declarado_por: str | None,
                              encargo: str) -> None:
    """La fila nace antes de que el trabajo empiece.

    Es lo que permite que la pantalla pregunte por el avance y que, si el
    navegador se cae, la revision siga y aparezca despues en el historial.
    """
    ejecutar(
        """INSERT INTO reteica.revision
             (corrida, usuario_id, nit, periodo, municipio, declarado_por,
              encargo, estado, progreso)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'en_proceso','Preparando')""",
        (corrida, usuario_id, nit, periodo, municipio, declarado_por, encargo),
    )


def marcar_progreso(corrida: str, progreso: str) -> None:
    ejecutar("UPDATE reteica.revision SET progreso=%s WHERE corrida=%s",
             (progreso, corrida))


def terminar_revision(corrida: str, razon_social: str | None, resumen: dict,
                      ruta_papel: str) -> None:
    semaforo = (resumen.get("semaforo") or {}).get("color")
    ejecutar(
        """UPDATE reteica.revision
              SET estado='lista', progreso=NULL, razon_social=%s,
                  semaforo=%s, conclusion=%s, impacto_total=%s,
                  puede_concluir_limpio=%s, resumen=%s, ruta_papel=%s
            WHERE corrida=%s""",
        (razon_social, semaforo, resumen.get("conclusion"),
         resumen.get("impacto_total"), resumen.get("puede_concluir_limpio"),
         json.dumps(resumen, default=str), ruta_papel, corrida),
    )


def fallar_revision(corrida: str, error: str) -> None:
    """Una revision que fallo NO se borra: el auditor tiene que poder ver que
    la intento y por que no salio, en vez de que desaparezca sin rastro."""
    ejecutar(
        """UPDATE reteica.revision
              SET estado='fallo', progreso=NULL, error=%s WHERE corrida=%s""",
        (error[:2000], corrida),
    )


def revisiones_de(usuario_id: str, nit: str | None = None,
                  limite: int = 100) -> list[dict]:
    """La lista para el historial. Sin el resumen: pesa y no se muestra ahi."""
    if nit:
        return varios(
            """SELECT corrida, nit, razon_social, periodo, municipio,
                      declarado_por, creado_en, semaforo, impacto_total,
                      puede_concluir_limpio, estado, progreso
                 FROM reteica.revision
                WHERE usuario_id=%s AND nit=%s
                ORDER BY creado_en DESC LIMIT %s""",
            (usuario_id, nit, limite))
    return varios(
        """SELECT corrida, nit, razon_social, periodo, municipio,
                  declarado_por, creado_en, semaforo, impacto_total,
                  puede_concluir_limpio, estado, progreso
             FROM reteica.revision
            WHERE usuario_id=%s
            ORDER BY creado_en DESC LIMIT %s""",
        (usuario_id, limite))


def revision_de(corrida: str, usuario_id: str) -> dict | None:
    """Una revision, solo si es de quien la pide. None tambien si no es suya."""
    return uno(
        """SELECT * FROM reteica.revision
            WHERE corrida=%s AND usuario_id=%s""",
        (corrida, usuario_id))


def borrar_revision(corrida: str, usuario_id: str) -> bool:
    """Borra una revision si es del auditor que la pide.

    Devuelve True si borro algo, False si no existia o no era suya. La
    autorizacion va en el WHERE, igual que las lecturas: no basta con saber
    el id de la corrida, tiene que ser del dueno.
    """
    with conn() as c:
        cur = c.execute(
            "DELETE FROM reteica.revision WHERE corrida=%s AND usuario_id=%s",
            (corrida, usuario_id))
        c.commit()
        return cur.rowcount > 0


# =====================================================================
# ENCARGOS
# =====================================================================
#
# El encargo es la carpeta viva: sus documentos se conservan y se pueden
# completar o corregir despues, incluso si la revision ya salio bien.

def crear_encargo(encargo_id: str, usuario_id: str) -> None:
    ejecutar("INSERT INTO reteica.encargo (id, usuario_id) VALUES (%s,%s)",
             (encargo_id, usuario_id))


def encargo_de(encargo_id: str, usuario_id: str) -> dict | None:
    return uno("""SELECT * FROM reteica.encargo
                   WHERE id=%s AND usuario_id=%s""",
               (encargo_id, usuario_id))


def tocar_encargo(encargo_id: str, **campos) -> None:
    """Guarda lo ultimo que se sabe del encargo (NIT, periodo, razon social)."""
    campos = {k: v for k, v in campos.items() if v}
    sets = "".join(", %s=%%s" % k for k in campos)
    ejecutar("UPDATE reteica.encargo SET actualizado_en=now()%s WHERE id=%%s"
             % sets, (*campos.values(), encargo_id))


def revisiones_del_encargo(encargo_id: str) -> list[dict]:
    return varios(
        """SELECT corrida, creado_en, semaforo, impacto_total,
                  puede_concluir_limpio, estado, progreso
             FROM reteica.revision WHERE encargo=%s
            ORDER BY creado_en DESC""",
        (encargo_id,))


def clientes_de(usuario_id: str) -> list[dict]:
    """Los NIT que este auditor ya ha revisado, para el filtro del historial."""
    return varios(
        """SELECT nit, max(razon_social) AS razon_social,
                  count(*) AS revisiones, max(creado_en) AS ultima
             FROM reteica.revision
            WHERE usuario_id=%s
            GROUP BY nit ORDER BY max(creado_en) DESC""",
        (usuario_id,))
