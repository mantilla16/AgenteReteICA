"""
API del motor de revision de ReteICA con autenticacion.

Login por correo @rbcol.co + codigo de 6 digitos.
Basado en el sistema de analitica-puc.

Levantar en desarrollo: uvicorn motor_reteica.api.servidor:app --reload
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import openpyxl
from fastapi import (FastAPI, File, Form, HTTPException, Request, Response,
                     UploadFile)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .. import __version__
from ..auth import (hash_token, nuevo_token, normalizar_correo, nuevo_codigo,
                    hash_codigo, verificar_codigo, problema_con_correo, LARGO_CODIGO,
                    MINUTOS_VIGENCIA_CODIGO, MAX_INTENTOS_CODIGO, MAX_CODIGOS_POR_VENTANA,
                    MINUTOS_VENTANA_ENVIO)
from .. import correo as CO
from .. import db
from ..atestacion import AtestacionInvalida
from ..identidad import IdentidadIncompatible
from ..ia.cliente import ClienteIA, ia_configurada
from ..ingesta._io import leer_filas
from ..ingesta.borrador_pdf import leer_borrador
from ..ingesta.formato_historico import normalizar_periodo
from ..manifiesto import NOMBRE_ARCHIVO, ManifiestoIncompleto
from ..plantilla.deposito import depositar
from ..parametros.columnas import ColumnaNoIdentificada, detectar_tipo_documento
from ..parametros.municipios.santa_marta import MUNICIPIO
from ..pipeline import revisar
from ..recursos import ruta_recurso
from ..semaforo import evaluar
from ..tipos import etiqueta_estado

app = FastAPI(title="Motor de Revision de ReteICA", version=__version__)

MUNICIPIOS = {"santa_marta": MUNICIPIO}

_RAIZ = Path(tempfile.gettempdir()) / "motor_reteica_web"
_RAIZ.mkdir(exist_ok=True)
_WEB = ruta_recurso("web")
_PAPELES: dict[str, Path] = {}

COOKIE = "sesion_reteica"
SESION_HORAS = int(os.getenv("SESION_HORAS", "12"))
SESION_SEGURA = os.getenv("SESION_SEGURA", "0") in ("1", "true", "True", "si")
BASE_PATH = os.getenv("RETEICA_BASE_PATH", "/reteica").rstrip("/")

PUBLICAS = {"/auth/estado", "/auth/codigo", "/auth/verificar", "/login",
            "/auth/login.html"}


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

@app.on_event("startup")
def _abrir() -> None:
    db.abrir()


@app.on_event("shutdown")
def _cerrar() -> None:
    db.cerrar()


# --------------------------------------------------------------------------
# Middleware de sesion
# --------------------------------------------------------------------------

@app.middleware("http")
async def exigir_sesion(request: Request, call_next):
    ruta = request.url.path

    # Detectar base path (ej: /reteica)
    base = BASE_PATH
    ruta_relativa = ruta[len(base):] if ruta.startswith(base) else ruta

    if request.method == "OPTIONS" or ruta_relativa in PUBLICAS:
        return await call_next(request)

    # Permitir archivos estaticos
    if ruta_relativa.startswith("/login") or ruta_relativa.endswith((".css", ".js", ".ico", ".png")):
        return await call_next(request)

    token = request.cookies.get(COOKIE)
    u = db.usuario_de_sesion(hash_token(token)) if token else None
    if not u:
        if ruta_relativa.startswith("/auth/"):
            return await call_next(request)
        return RedirectResponse(url=base + "/login", status_code=302)

    request.state.usuario = u
    return await call_next(request)


# --------------------------------------------------------------------------
# Auth routes
# --------------------------------------------------------------------------

class PedirCodigo(BaseModel):
    correo: str


class VerificarCodigo(BaseModel):
    correo: str
    codigo: str


@app.get("/auth/estado")
def auth_estado() -> dict:
    sirve, falta = CO.configurado()
    return {"dominio": "rbcol.co", "correo_listo": sirve,
            "correo_problema": falta, "modo_correo": CO.modo(),
            "largo_codigo": LARGO_CODIGO,
            "minutos_codigo": MINUTOS_VIGENCIA_CODIGO}


@app.post("/auth/codigo")
def pedir_codigo(c: PedirCodigo, request: Request) -> dict:
    correo = normalizar_correo(c.correo)
    problema = problema_con_correo(correo)
    if problema:
        raise HTTPException(422, problema)

    desde = datetime.now(timezone.utc) - timedelta(minutes=MINUTOS_VENTANA_ENVIO)
    if db.codigos_recientes(correo, desde) >= MAX_CODIGOS_POR_VENTANA:
        raise HTTPException(
            429, f"Ya se enviaron varios codigos a ese correo. Espere "
                 f"{MINUTOS_VENTANA_ENVIO} minutos o use el ultimo que recibio.")

    codigo = nuevo_codigo()
    expira = datetime.now(timezone.utc) + timedelta(minutes=MINUTOS_VIGENCIA_CODIGO)
    db.crear_codigo(correo, hash_codigo(codigo), expira,
                    _ip(request), request.headers.get("user-agent"))
    try:
        via = CO.enviar_codigo(correo, codigo, MINUTOS_VIGENCIA_CODIGO)
    except CO.CorreoNoConfigurado as e:
        raise HTTPException(503, f"No se puede enviar el correo. {e}")
    except Exception as e:
        raise HTTPException(502, f"El correo no salio: {e}")

    return {"enviado": True, "minutos": MINUTOS_VIGENCIA_CODIGO}


@app.post("/auth/verificar")
def verificar_codigo_route(c: VerificarCodigo, request: Request,
                           response: Response) -> dict:
    correo = normalizar_correo(c.correo)
    problema = problema_con_correo(correo)
    if problema:
        raise HTTPException(422, problema)

    fila = db.codigo_vigente(correo)
    if not fila:
        raise HTTPException(401, "El codigo no es correcto o ya vencio")
    if fila["expira_en"] <= datetime.now(timezone.utc):
        raise HTTPException(401, "El codigo expiro")
    if fila["intentos"] >= MAX_INTENTOS_CODIGO:
        db.consumir_codigo(fila["id"])
        raise HTTPException(429, "Demasiados intentos. Pida un codigo nuevo")
    if not verificar_codigo((c.codigo or "").strip(), fila["codigo_hash"]):
        db.sumar_intento(fila["id"])
        raise HTTPException(401, "El codigo no es correcto")

    db.consumir_codigo(fila["id"])

    u = db.usuario_por_correo(correo)
    if u and not u["activo"]:
        raise HTTPException(403, "Cuenta desactivada")
    if not u:
        u = db.crear_usuario_por_correo(correo, correo.split("@")[0])

    _sesion_nueva(u, request, response)
    return {"usuario": u["usuario"], "nombre": u["nombre"],
            "correo": u["correo"], "rol": u["rol"]}


@app.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        db.borrar_sesion(hash_token(token))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


def _sesion_nueva(u: dict, request: Request, response: Response) -> None:
    token = nuevo_token()
    expira = datetime.now(timezone.utc) + timedelta(hours=SESION_HORAS)
    db.crear_sesion(hash_token(token), u["id"], expira,
                    request.headers.get("user-agent"))
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax",
        secure=SESION_SEGURA, max_age=SESION_HORAS * 3600, path="/",
    )


def _ip(request: Request) -> str | None:
    return (request.headers.get("x-real-ip")
            or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            or (request.client.host if request.client else None))


# --------------------------------------------------------------------------
# Paginas
# --------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login_page() -> str:
    idx = _WEB / "login.html"
    return idx.read_text(encoding="utf-8") if idx.exists() else "<h1>Login</h1>"


@app.get("/", response_class=HTMLResponse)
def inicio() -> str:
    idx = _WEB / "index.html"
    return idx.read_text(encoding="utf-8") if idx.exists() else "<h1>Motor de Revision de ReteICA</h1>"


# --------------------------------------------------------------------------
# Deteccion de roles por ESTRUCTURA
# --------------------------------------------------------------------------

def _es_borrador_pdf(ruta: Path) -> bool:
    try:
        leer_borrador(ruta)
        return True
    except Exception:
        return False


_MARCAS_DE_FACTURA = ("FACTURA", "FACTURA ELECTRONICA", "FACTURA DE VENTA")


def _es_factura_pdf(ruta: Path) -> bool:
    try:
        import pdfplumber
        with pdfplumber.open(ruta) as pdf:
            texto = " ".join((p.extract_text() or "") for p in pdf.pages[:2])
    except Exception:
        return False
    sin_tildes = (texto.upper().replace("Ó", "O").replace("Í", "I")
                  .replace("É", "E").replace("Á", "A").replace("Ú", "U"))
    return any(marca in sin_tildes for marca in _MARCAS_DE_FACTURA)


def _rol_xlsx(ruta: Path):
    try:
        filas = leer_filas(ruta)
    except Exception:
        return None
    tipo = detectar_tipo_documento(filas)
    if tipo:
        return tipo
    try:
        libro = openpyxl.load_workbook(ruta, read_only=True)
        periodos = [normalizar_periodo(n) for n in libro.sheetnames]
        libro.close()
    except Exception:
        return None
    return "formato_historico" if sum(1 for p in periodos if p) >= 2 else None


def _clasificar(rutas: list[Path]):
    archivos = {"borrador": None, "auxiliar": None, "balance": None,
               "erp": None, "formato_historico": None}
    facturas, sin_clasificar, conflictos = [], [], []

    for ruta in rutas:
        extension = ruta.suffix.lower()
        if extension == ".pdf":
            if _es_borrador_pdf(ruta):
                if archivos["borrador"]:
                    conflictos.append(
                        "dos archivos parecen ser el borrador: %r y %r"
                        % (archivos["borrador"], ruta.name))
                else:
                    archivos["borrador"] = ruta.name
            elif _es_factura_pdf(ruta):
                facturas.append(ruta.name)
            else:
                sin_clasificar.append(ruta.name)
        elif extension in (".xlsx", ".xls"):
            rol = _rol_xlsx(ruta)
            if rol is None:
                sin_clasificar.append(ruta.name)
            elif archivos[rol]:
                conflictos.append(
                    "dos archivos parecen ser %s: %r y %r"
                    % (rol, archivos[rol], ruta.name))
            else:
                archivos[rol] = ruta.name
        else:
            sin_clasificar.append(ruta.name)

    return archivos, facturas, sin_clasificar, conflictos


# --------------------------------------------------------------------------
# Traduccion del resultado a JSON
# --------------------------------------------------------------------------

def _f(valor) -> float:
    return float(valor) if isinstance(valor, Decimal) else valor


def _resumen(ctx) -> dict:
    luz = evaluar(ctx.informe)
    return {
        "controles": [{
            "codigo": r.codigo, "nombre": r.nombre, "estado": etiqueta_estado(r),
            "detalle": r.detalle, "excepciones": len(r.excepciones),
            "aplica": r.aplica,
        } for r in ctx.resultados],
        "cifras": {
            "auxiliar": _f(ctx.total_auxiliar), "erp": _f(ctx.total_erp),
            "base_gravable": _f(ctx.reconstruccion.total_base),
            "impuesto_contable": _f(ctx.reconstruccion.total_impuesto_contable),
            "impuesto_declarable": _f(ctx.reconstruccion.total_impuesto_declarable),
            "declarado": _f(ctx.borrador.renglones.get("24", Decimal("0"))),
        },
        "excepciones": [{
            "severidad": e.severidad.value, "control": e.control,
            "descripcion": e.descripcion, "tipo_referencia": e.tipo_referencia,
            "renglon": e.renglon, "impacto": _f(e.impacto_pesos),
        } for e in ctx.informe.excepciones_ordenadas],
        "impacto_total": _f(ctx.informe.impacto_total),
        "puede_concluir_limpio": ctx.informe.puede_concluir_limpio,
        "conclusion": ctx.informe.conclusion,
        "semaforo": {"color": luz.color, "motivo": luz.motivo,
                    "simbolo": luz.simbolo},
        "insumos_obtenidos": sorted(ctx.insumos_obtenidos),
        "razon_social": ctx.borrador.razon_social,
    }


# --------------------------------------------------------------------------
# API routes
# --------------------------------------------------------------------------

@app.post("/analizar")
async def analizar(
    archivos: list[UploadFile] = File(...),
    nit: str = Form(...), periodo: str = Form(...),
    municipio: str = Form("santa_marta"),
    declarado_por: str = Form(""), api_key: str = Form(""),
):
    if municipio not in MUNICIPIOS:
        raise HTTPException(400, "Municipio no soportado: %s" % municipio)

    corr = uuid.uuid4().hex[:12]
    carpeta = _RAIZ / corr
    carpeta.mkdir(exist_ok=True)

    rutas = []
    for subida in archivos:
        destino = carpeta / (subida.filename or "archivo_%d" % len(rutas))
        destino.write_bytes(await subida.read())
        rutas.append(destino)

    archivos_por_rol, facturas, sin_clasificar, conflictos = _clasificar(rutas)
    if conflictos:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise HTTPException(400, "; ".join(conflictos))

    manifiesto = {
        "nit": nit, "periodo": periodo, "municipio": MUNICIPIOS[municipio].nombre,
        "declarado_por": declarado_por or "sin declarar",
        "fecha": date.today().isoformat(),
        "archivos": {**archivos_por_rol, "facturas": facturas or None,
                    "pago_anterior": None},
    }
    (carpeta / NOMBRE_ARCHIVO).write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2), encoding="utf-8")

    # Con modelo local no hay llave que pedirle a nadie: si el servidor esta
    # configurado, la Revision Inteligente corre sola. La llave por formulario
    # se conserva para quien quiera usar Anthropic desde su propia cuenta.
    if api_key:
        cliente_ia = ClienteIA(api_key=api_key, proveedor="anthropic")
    elif ia_configurada():
        cliente_ia = ClienteIA()
    else:
        cliente_ia = None

    try:
        ctx = revisar(carpeta, nit=nit, periodo=periodo,
                      municipio=MUNICIPIOS[municipio], cliente_ia=cliente_ia)
    except (ManifiestoIncompleto, IdentidadIncompatible, ColumnaNoIdentificada,
            AtestacionInvalida, FileNotFoundError) as error:
        raise HTTPException(400, str(error))

    salida = carpeta / ("PT_ReteICA_%s.xlsx" % corr)
    depositar(ctx, salida)
    _PAPELES[corr] = salida

    resumen = _resumen(ctx)
    resumen["sin_clasificar"] = sin_clasificar
    return {"corrida": corr, "descarga": "/descargar/%s" % corr, "resumen": resumen}


@app.get("/salir")
def salir(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        db.borrar_sesion(hash_token(token))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/descargar/{corr}")
def descargar(corr: str):
    ruta = _PAPELES.get(corr)
    if not ruta or not ruta.exists():
        raise HTTPException(404, "Papel no encontrado o expirado.")
    return FileResponse(str(ruta), filename=ruta.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
