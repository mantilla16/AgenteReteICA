"""
API del motor de revision de ReteICA con autenticacion.

Login por correo @rbcol.co + codigo de 6 digitos.
Basado en el sistema de analitica-puc.

Levantar en desarrollo: uvicorn motor_reteica.api.servidor:app --reload
"""
from __future__ import annotations

import json
import os
import re
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

_WEB = ruta_recurso("web")

# Nada de esto puede vivir en /tmp: el sistema lo limpia solo y lo borra al
# reiniciar. Los papeles quedan archivados, y los documentos del encargo se
# conservan para poder completarlo o corregirlo despues.
_PAPELES = Path(os.getenv("RETEICA_PAPELES", "/var/lib/reteica/papeles"))

# La corrida es uuid4().hex[:12]. Se valida antes de tocar el disco: el id
# viaja en la URL y sin esto un ../.. serviria cualquier archivo del servidor.
_RE_CORRIDA = re.compile(r"^[0-9a-f]{12}$")


# Los documentos del encargo se conservan: sobre un mismo encargo se revisa
# varias veces, agregando lo que falto o corrigiendo un archivo mal exportado.
_ENCARGOS = Path(os.getenv("RETEICA_ENCARGOS", "/var/lib/reteica/encargos"))

# Que controles dependen de cada insumo. Sirve para decirle al auditor, ANTES
# de correr, que va a perder si sigue sin ese documento -- en vez de que lo
# descubra diez minutos despues leyendo la conclusion.
CONTROLES_POR_INSUMO = {
    "balance":           ("C2",),
    "erp":               ("C3", "C5"),
    "facturas":          ("C6", "C11"),
    "formato_historico": ("C12", "C15"),
    "pago_anterior":     ("C12",),
}

OBLIGATORIOS = ("borrador", "auxiliar")

NOMBRE_INSUMO = {
    "borrador":          "Borrador de la declaracion",
    "auxiliar":          "Auxiliar 2368",
    "balance":           "Balance de prueba",
    "erp":               "Reporte de retenciones del ERP",
    "facturas":          "Facturas fuente",
    "pago_anterior":     "Declaracion y pago del mes anterior",
    "formato_historico": "Formato historico del cliente",
}


def _deposito_papeles() -> Path:
    _PAPELES.mkdir(parents=True, exist_ok=True)
    return _PAPELES


def _carpeta_encargo(enc: str) -> Path:
    if not _RE_CORRIDA.match(enc or ""):
        raise HTTPException(404, "Ese encargo no existe.")
    return _ENCARGOS / enc


def _exigir_encargo(enc: str, request: Request) -> Path:
    """La carpeta del encargo, solo si es de quien la pide."""
    if db.encargo_de(enc, request.state.usuario["id"]) is None:
        raise HTTPException(404, "Ese encargo no existe o no es suyo.")
    return _carpeta_encargo(enc)


def _tablero(carpeta: Path) -> dict:
    """Que reconocio el motor en lo que va subido, y que falta.

    Es la misma clasificacion que corre la revision, solo que ahora se hace
    al subir cada archivo y no al final: el auditor ve el tablero llenarse en
    vez de esperar diez minutos para descubrir que le faltaba el balance.
    """
    rutas = sorted(p for p in carpeta.iterdir()
                   if p.is_file() and p.name != NOMBRE_ARCHIVO)
    roles, facturas, sin_clasificar, conflictos = _clasificar(rutas)

    presentes = {r for r, v in roles.items() if v}
    if facturas:
        presentes.add("facturas")

    faltan = [r for r in NOMBRE_INSUMO if r not in presentes]
    en_riesgo = sorted({c for r in faltan
                        for c in CONTROLES_POR_INSUMO.get(r, ())})

    return {
        "insumos": {**roles, "facturas": facturas or None},
        "facturas": facturas,
        "sin_clasificar": sin_clasificar,
        "conflictos": conflictos,
        "faltan": faltan,
        "faltan_obligatorios": [r for r in OBLIGATORIOS if r not in presentes],
        "controles_en_riesgo": en_riesgo,
        "puede_revisar": not conflictos and all(r in presentes
                                                for r in OBLIGATORIOS),
    }


def _ruta_papel(corr: str) -> Path | None:
    """Donde quedo el papel de una corrida.

    Antes esto era un diccionario en memoria, y ahi estaba el defecto: con
    varios workers de gunicorn, el POST que genera el papel y el GET que lo
    descarga caen en procesos distintos. El que descarga tiene el diccionario
    vacio y contesta "Papel no encontrado" sobre un archivo que existe. La
    ruta es determinista, asi que no hay nada que recordar.
    """
    if not _RE_CORRIDA.match(corr or ""):
        return None
    ruta = _PAPELES / ("%s.xlsx" % corr)
    return ruta if ruta.exists() else None


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
    request: Request,
    archivos: list[UploadFile] = File(...),
    nit: str = Form(...), periodo: str = Form(...),
    municipio: str = Form("santa_marta"),
    declarado_por: str = Form(""), api_key: str = Form(""),
):
    """Camino de un solo golpe: sube todo y revisa.

    Se conserva porque es una API util por si sola, pero la pantalla ya no lo
    usa: ahora los documentos se suben uno a uno a un encargo, que ademas
    sobrevive a la revision para poder completarlo.
    """
    enc = _nuevo_encargo(request)
    carpeta = _carpeta_encargo(enc)
    for subida in archivos:
        nombre = Path(subida.filename or "archivo").name
        (carpeta / nombre).write_bytes(await subida.read())

    return await _revisar_encargo(
        request, enc, nit=nit, periodo=periodo, municipio=municipio,
        declarado_por=declarado_por, api_key=api_key)


# --------------------------------------------------------------------------
# Encargos: la carpeta viva del cliente
# --------------------------------------------------------------------------

def _nuevo_encargo(request: Request) -> str:
    enc = uuid.uuid4().hex[:12]
    _carpeta_encargo(enc).mkdir(parents=True, exist_ok=True)
    db.crear_encargo(enc, request.state.usuario["id"])
    return enc


@app.post("/encargos")
def abrir_encargo(request: Request) -> dict:
    enc = _nuevo_encargo(request)
    return {"encargo": enc, **_tablero(_carpeta_encargo(enc))}


@app.get("/encargos/{enc}")
def ver_encargo(enc: str, request: Request) -> dict:
    fila = db.encargo_de(enc, request.state.usuario["id"])
    if fila is None:
        raise HTTPException(404, "Ese encargo no existe o no es suyo.")
    datos = _fila_json(fila)
    datos["encargo"] = enc
    datos.update(_tablero(_carpeta_encargo(enc)))
    datos["revisiones"] = [_fila_json(r)
                           for r in db.revisiones_del_encargo(enc)]
    return datos


@app.post("/encargos/{enc}/documentos")
async def subir_documento(enc: str, request: Request,
                          archivo: UploadFile = File(...)) -> dict:
    """Un documento a la vez: se guarda, se clasifica y se devuelve el tablero.

    Subir de a uno es lo que permite reconocerlo al instante. Un archivo con
    el mismo nombre REEMPLAZA al anterior: asi se corrige un export mal hecho
    sin tener que empezar de cero.
    """
    carpeta = _exigir_encargo(enc, request)
    nombre = Path(archivo.filename or "archivo").name
    if not nombre or nombre.startswith("~$"):
        raise HTTPException(400, "Ese archivo no es un documento (%s)." % nombre)
    (carpeta / nombre).write_bytes(await archivo.read())
    db.tocar_encargo(enc)
    tablero = _tablero(carpeta)
    tablero["encargo"] = enc
    tablero["subido"] = nombre
    return tablero


@app.delete("/encargos/{enc}/documentos/{nombre}")
def quitar_documento(enc: str, nombre: str, request: Request) -> dict:
    carpeta = _exigir_encargo(enc, request)
    ruta = carpeta / Path(nombre).name
    if not ruta.exists() or not ruta.is_file():
        raise HTTPException(404, "Ese documento no esta en el encargo.")
    ruta.unlink()
    db.tocar_encargo(enc)
    return {"encargo": enc, **_tablero(carpeta)}


@app.post("/encargos/{enc}/revisar")
async def revisar_encargo(
    enc: str, request: Request,
    nit: str = Form(...), periodo: str = Form(...),
    municipio: str = Form("santa_marta"),
    declarado_por: str = Form(""), api_key: str = Form(""),
):
    _exigir_encargo(enc, request)
    return await _revisar_encargo(
        request, enc, nit=nit, periodo=periodo, municipio=municipio,
        declarado_por=declarado_por, api_key=api_key)


async def _revisar_encargo(request: Request, enc: str, *, nit: str,
                           periodo: str, municipio: str, declarado_por: str,
                           api_key: str):
    if municipio not in MUNICIPIOS:
        raise HTTPException(400, "Municipio no soportado: %s" % municipio)

    carpeta = _carpeta_encargo(enc)
    rutas = sorted(p for p in carpeta.iterdir()
                   if p.is_file() and p.name != NOMBRE_ARCHIVO)
    archivos_por_rol, facturas, sin_clasificar, conflictos = _clasificar(rutas)
    if conflictos:
        raise HTTPException(400, "; ".join(conflictos))

    corr = uuid.uuid4().hex[:12]
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

    # El papel va al archivo permanente. La carpeta del encargo NO se borra:
    # es lo que permite volver, agregar el balance que faltaba o reemplazar un
    # archivo mal exportado, y revisar otra vez sin subirlo todo de nuevo.
    salida = _deposito_papeles() / ("%s.xlsx" % corr)
    depositar(ctx, salida)

    resumen = _resumen(ctx)
    resumen["sin_clasificar"] = sin_clasificar

    # El registro no puede tumbar una revision que ya se hizo: si la base
    # falla, el auditor igual recibe su papel y la respuesta lo dice, en vez
    # de perder diez minutos de trabajo por una fila que no se escribio.
    registrada = True
    try:
        usuario = request.state.usuario
        db.guardar_revision(
            corrida=corr, usuario_id=usuario["id"], nit=nit,
            razon_social=resumen.get("razon_social"), periodo=periodo,
            municipio=MUNICIPIOS[municipio].nombre,
            declarado_por=declarado_por or None, resumen=resumen,
            ruta_papel=str(salida), encargo=enc)
        db.tocar_encargo(enc, nit=nit, periodo=periodo,
                         municipio=MUNICIPIOS[municipio].nombre,
                         declarado_por=declarado_por,
                         razon_social=resumen.get("razon_social"))
    except Exception as error:
        registrada = False
        print("[revision] no se pudo registrar %s: %s" % (corr, error),
              flush=True)

    return {"corrida": corr, "encargo": enc,
            "descarga": "/descargar/%s" % corr,
            "resumen": resumen, "registrada": registrada,
            "tablero": _tablero(carpeta)}


# --------------------------------------------------------------------------
# Historial: cada auditor ve lo suyo
# --------------------------------------------------------------------------

@app.get("/revisiones")
def listar_revisiones(request: Request, nit: str = "") -> dict:
    usuario = request.state.usuario
    filas = db.revisiones_de(usuario["id"], nit=nit or None)
    return {"revisiones": [_fila_json(f) for f in filas]}


@app.get("/clientes")
def listar_clientes(request: Request) -> dict:
    usuario = request.state.usuario
    return {"clientes": [_fila_json(f) for f in db.clientes_de(usuario["id"])]}


@app.get("/revisiones/{corr}")
def ver_revision(corr: str, request: Request) -> dict:
    usuario = request.state.usuario
    fila = db.revision_de(corr, usuario["id"])
    if fila is None:
        raise HTTPException(404, "Esa revision no existe o no es suya.")
    datos = _fila_json(fila)
    datos["descarga"] = "/descargar/%s" % corr
    datos["papel_disponible"] = _ruta_papel(corr) is not None
    return datos


def _fila_json(fila: dict) -> dict:
    """Las filas traen datetime, Decimal y uuid: nada de eso es JSON."""
    salida = {}
    for clave, valor in fila.items():
        if clave == "usuario_id":
            continue          # de adentro para afuera no se publica
        if isinstance(valor, datetime):
            salida[clave] = valor.isoformat()
        elif isinstance(valor, Decimal):
            salida[clave] = float(valor)
        else:
            salida[clave] = valor
    return salida


@app.get("/salir")
def salir(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        db.borrar_sesion(hash_token(token))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/descargar/{corr}")
def descargar(corr: str, request: Request):
    # El papel es del auditor que lo genero. Se pregunta a la base ANTES de
    # mirar el disco: que el archivo exista no autoriza a nadie a recibirlo.
    fila = db.revision_de(corr, request.state.usuario["id"])
    if fila is None:
        raise HTTPException(404, "Papel no encontrado o expirado.")
    ruta = _ruta_papel(corr)
    if ruta is None:
        raise HTTPException(404, "Papel no encontrado o expirado.")
    # Un nombre que el auditor pueda archivar, no el id de la corrida.
    nombre = "PT_ReteICA_%s_%s.xlsx" % (fila["nit"],
                                        str(fila["periodo"]).replace("-", ""))
    return FileResponse(str(ruta), filename=nombre,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
