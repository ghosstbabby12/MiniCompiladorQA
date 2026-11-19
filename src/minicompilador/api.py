"""API REST del MiniCompilador (FastAPI).

Endpoints
---------
    GET  /salud     → 200 {"estado": "ok", "version": ...}   (healthcheck)
    GET  /esquema   → 200 el JSON Schema del reporte          (el CONTRATO)
    POST /compilar  → el reporte JSON de las 6 fases
    POST /explicar  → la explicación en lenguaje sencillo (texto plano)

Códigos HTTP de /compilar (decisión de diseño, RFC 9110)
--------------------------------------------------------
    200 OK                    el programa compiló y se ejecutó sin errores.
    422 Unprocessable Content la SOLICITUD es correcta, pero el PROGRAMA Mini
                              tiene un error (léxico, sintáctico, semántico o de
                              ejecución). El cuerpo es el reporte completo, que
                              explica el error y cumple el mismo esquema.
    400 Bad Request           la solicitud está mal hecha: JSON roto, falta
                              ``codigo``, tipos incorrectos o valores fuera de
                              rango (``hasta_fase`` = 7, código demasiado largo).

¿Por qué no usar el 422 que FastAPI devuelve por defecto en validaciones? Porque
así el cliente distingue "TU PETICIÓN está mal" (400, corrige el cliente) de
"TU PROGRAMA está mal" (422, corrige el código Mini), que es exactamente la
diferencia que el RFC hace entre ambos códigos.

Persistencia: cada reporte de /compilar se guarda en S3 si está configurado
(ver ``almacenamiento.py``). El resultado va en CABECERAS, no en el cuerpo,
para no tocar el contrato JSON:
    X-Reporte-Clave: reportes/2026/11/19/<uuid>.json   (se guardó)
    X-Reporte-Guardado: no-configurado | error         (no se guardó)
Si S3 falla, el cliente recibe igual su reporte (degradación elegante).

Los endpoints son ``def`` (no ``async``): compilar usa CPU, y FastAPI ejecuta
las funciones síncronas en un pool de hilos, así una compilación larga no
bloquea el bucle de eventos que atiende /salud.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from minicompilador import __version__
from minicompilador.almacenamiento import (
    Almacenamiento,
    ErrorAlmacenamiento,
    crear_desde_entorno,
)
from minicompilador.cpu import LIMITE_CICLOS_POR_DEFECTO
from minicompilador.errores import FASES
from minicompilador.explicador import explicar
from minicompilador.reporte import Compilacion, cargar_esquema, compilar

#: Límites de la solicitud: protegen al servidor de entradas abusivas (un
#: programa de megas o un límite de ciclos enorme ocuparían la CPU minutos).
LONGITUD_MAXIMA_CODIGO = 20_000
LIMITE_CICLOS_MAXIMO = 1_000_000

HTTP_OK, HTTP_SOLICITUD_INVALIDA, HTTP_PROGRAMA_CON_ERRORES = 200, 400, 422

registro = logging.getLogger(__name__)


class SolicitudCompilacion(BaseModel):
    """Cuerpo de POST /compilar y POST /explicar.

    ``strict=True``: no hay conversiones "mágicas" (``"6"`` NO se acepta como
    ``6``, ni ``true`` como ``1``). ``extra="forbid"``: un campo mal escrito
    (``hasta_fse``) es un error, en vez de ignorarse en silencio.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        json_schema_extra={"examples": [{"codigo": "int a = 2;\nprint(a * 3);", "hasta_fase": 6}]},
    )

    codigo: Annotated[
        str, Field(max_length=LONGITUD_MAXIMA_CODIGO, description="Programa en lenguaje Mini")
    ]
    hasta_fase: Annotated[
        int, Field(ge=1, le=len(FASES), description="Última fase a ejecutar (1..6)")
    ] = len(FASES)
    limite_ciclos: Annotated[
        int, Field(ge=1, le=LIMITE_CICLOS_MAXIMO, description="Ciclos máximos del simulador")
    ] = LIMITE_CICLOS_POR_DEFECTO


def _compilar(solicitud: SolicitudCompilacion) -> Compilacion:
    return compilar(
        solicitud.codigo,
        hasta_fase=solicitud.hasta_fase,
        limite_ciclos=solicitud.limite_ciclos,
    )


def codigo_http(compilacion: Compilacion) -> int:
    """200 si el programa no tiene errores; 422 si el programa Mini falla."""
    return HTTP_OK if compilacion.exito else HTTP_PROGRAMA_CON_ERRORES


_RESPUESTAS_COMPILAR: dict[int | str, dict[str, Any]] = {
    HTTP_OK: {"description": "Compiló y ejecutó sin errores."},
    HTTP_SOLICITUD_INVALIDA: {"description": "Solicitud mal formada (JSON, campos o rangos)."},
    HTTP_PROGRAMA_CON_ERRORES: {"description": "El programa Mini tiene un error; ver 'errores'."},
}


def _cabeceras_de_guardado(almacenamiento: Almacenamiento, reporte: dict) -> dict[str, str]:
    """Intenta guardar el reporte y describe el resultado en cabeceras HTTP."""
    try:
        clave = almacenamiento.guardar(reporte)
    except ErrorAlmacenamiento as error:
        registro.warning("Reporte NO guardado: %s", error)
        return {"X-Reporte-Guardado": "error"}
    if clave is None:
        return {"X-Reporte-Guardado": "no-configurado"}
    return {"X-Reporte-Clave": clave}


def crear_app(almacenamiento: Almacenamiento | None = None) -> FastAPI:
    """Fábrica de la aplicación.

    Args:
        almacenamiento: dónde guardar los reportes. ``None`` → se decide por
            variables de entorno (``crear_desde_entorno``). Las pruebas
            inyectan aquí un doble de prueba.
    """
    if almacenamiento is None:
        almacenamiento = crear_desde_entorno()
    app = FastAPI(
        title="MiniCompilador QA",
        version=__version__,
        description="Compilador didáctico del lenguaje Mini: 6 fases y reporte JSON.",
    )

    @app.exception_handler(RequestValidationError)
    def solicitud_invalida(_request: Request, error: RequestValidationError) -> JSONResponse:
        """Convierte los errores de validación de FastAPI (422) en 400 explicados."""
        detalle = [
            {
                "campo": ".".join(str(parte) for parte in e["loc"] if parte != "body") or "body",
                "mensaje": e["msg"],
                "tipo": e["type"],
            }
            for e in error.errors()
        ]
        return JSONResponse(
            {"error": "solicitud_invalida", "detalle": detalle},
            status_code=HTTP_SOLICITUD_INVALIDA,
        )

    @app.get("/salud", tags=["operación"])
    def salud() -> dict[str, str]:
        """Healthcheck para Docker, docker-compose y el despliegue (CD)."""
        return {"estado": "ok", "version": __version__}

    @app.get("/esquema", tags=["contrato"])
    def esquema() -> dict[str, Any]:
        """El JSON Schema que cumple TODA respuesta de /compilar (200 y 422)."""
        return cargar_esquema()

    @app.post("/compilar", tags=["compilador"], responses=_RESPUESTAS_COMPILAR)
    def compilar_programa(solicitud: SolicitudCompilacion) -> JSONResponse:
        """Compila el programa y devuelve el reporte JSON de las 6 fases."""
        compilacion = _compilar(solicitud)
        reporte = compilacion.a_reporte()
        return JSONResponse(
            reporte,
            status_code=codigo_http(compilacion),
            headers=_cabeceras_de_guardado(almacenamiento, reporte),
        )

    @app.post("/explicar", tags=["compilador"], responses=_RESPUESTAS_COMPILAR)
    def explicar_programa(solicitud: SolicitudCompilacion) -> PlainTextResponse:
        """Igual que /compilar, pero responde con la explicación paso a paso."""
        compilacion = _compilar(solicitud)
        return PlainTextResponse(explicar(compilacion), status_code=codigo_http(compilacion))

    return app


#: Instancia que arranca uvicorn: ``uvicorn minicompilador.api:app``.
app = crear_app()
