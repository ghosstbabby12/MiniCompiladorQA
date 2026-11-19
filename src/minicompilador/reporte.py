"""Orquestador del compilador y generación del REPORTE JSON.

``compilar()`` ejecuta las 6 fases en orden. Si una fase lanza un
``ErrorCompilador``, se detiene ahí: el reporte conserva los resultados de las
fases anteriores y explica el error. Las secciones de fases no alcanzadas
quedan en ``null`` (así el contrato JSON siempre tiene las mismas claves).

El reporte se valida contra ``esquemas/reporte.schema.json`` (JSON Schema
2020-12); ese mismo esquema lo publica la API en ``GET /esquema`` y lo usan
las pruebas de contrato.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator

from minicompilador import __version__
from minicompilador.ast_nodos import Programa, nodo_a_dict
from minicompilador.cpu import (
    CPU,
    LIMITE_CICLOS_POR_DEFECTO,
    InstruccionCPU,
    ResultadoCPU,
    traducir_a_cpu,
)
from minicompilador.errores import FASES, Advertencia, ErrorCompilador, ErrorEjecucion
from minicompilador.intermedio import ResultadoIntermedio, generar_intermedio
from minicompilador.lexer import Token, tokenizar
from minicompilador.parser import Parser
from minicompilador.registros import ResultadoRegistros, asignar_registros
from minicompilador.semantico import ResultadoSemantico, analizar


@dataclass
class Compilacion:
    """Resultado completo de compilar: un atributo por fase (``None`` si no se alcanzó)."""

    codigo: str
    hasta_fase: int = len(FASES)
    fases_completadas: list[str] = field(default_factory=list)
    tokens: list[Token] | None = None
    programa: Programa | None = None
    semantico: ResultadoSemantico | None = None
    intermedio: ResultadoIntermedio | None = None
    registros: ResultadoRegistros | None = None
    codigo_cpu: list[InstruccionCPU] | None = None
    cpu: ResultadoCPU | None = None
    error: ErrorCompilador | None = None

    @property
    def exito(self) -> bool:
        return self.error is None

    @property
    def fase_alcanzada(self) -> str:
        """Fase donde se detuvo: la del error, o la última completada."""
        if self.error is not None:
            return self.error.fase
        return self.fases_completadas[-1]

    @property
    def advertencias(self) -> list[Advertencia]:
        lista: list[Advertencia] = []
        if self.semantico:
            lista += self.semantico.advertencias
        if self.registros:
            lista += self.registros.advertencias
        return lista

    def a_reporte(self) -> dict[str, Any]:
        """Diccionario serializable a JSON con todas las secciones del reporte."""
        inter, regs = self.intermedio, self.registros
        return {
            "version": __version__,
            "fase_alcanzada": self.fase_alcanzada,
            "exito": self.exito,
            "fases_completadas": list(self.fases_completadas),
            "tokens": [t.a_dict() for t in self.tokens] if self.tokens is not None else None,
            "ast": nodo_a_dict(self.programa) if self.programa else None,
            "tabla_simbolos": self.semantico.tabla.a_dict() if self.semantico else None,
            "temporales": inter.temporales if inter else None,
            "total_temporales": inter.total_temporales if inter else None,
            "definiciones_temporales": inter.definiciones_temporales if inter else None,
            "optimizaciones": inter.optimizaciones if inter else None,
            "recorrido_postorden": inter.recorrido if inter else None,
            "codigo_intermedio": inter.como_texto() if inter else None,
            "asignacion_registros": regs.asignacion if regs else None,
            "registros_max_simultaneos": regs.max_registros_simultaneos if regs else None,
            "temporales_vivas_max": regs.max_temporales_vivas if regs else None,
            "spills": regs.spills if regs else None,
            "instrucciones_cpu": [str(i) for i in self.codigo_cpu] if self.codigo_cpu else None,
            "metricas": self.cpu.metricas() if self.cpu else None,
            "memoria_final": self.cpu.memoria_final if self.cpu else None,
            "salida": self.cpu.salida if self.cpu else None,
            "errores": [self.error.a_dict()] if self.error else [],
            "advertencias": [a.a_dict() for a in self.advertencias],
        }


def compilar(
    codigo: str,
    hasta_fase: int = len(FASES),
    limite_ciclos: int = LIMITE_CICLOS_POR_DEFECTO,
    plegar_constantes: bool = True,
) -> Compilacion:
    """Ejecuta las fases 1..``hasta_fase`` y devuelve el resultado de cada una.

    Nunca lanza ``ErrorCompilador``: lo guarda en ``Compilacion.error``.
    """
    if not 1 <= hasta_fase <= len(FASES):
        raise ValueError(f"hasta_fase debe estar entre 1 y {len(FASES)}")
    c = Compilacion(codigo, hasta_fase)

    def fase_lexico() -> None:
        c.tokens = tokenizar(codigo)

    def fase_sintactico() -> None:
        c.programa = Parser(c.tokens).parsear()

    def fase_semantico() -> None:
        c.semantico = analizar(c.programa)

    def fase_intermedio() -> None:
        c.intermedio = generar_intermedio(c.programa, plegar_constantes)

    def fase_registros() -> None:
        c.registros = asignar_registros(c.intermedio.instrucciones)
        c.codigo_cpu = traducir_a_cpu(c.intermedio.instrucciones, c.registros)

    def fase_simulacion() -> None:
        tabla = c.semantico.tabla
        direcciones = {s.nombre: s.direccion for s in tabla} | c.registros.direcciones_spill
        tipos = {s.nombre: s.tipo for s in tabla}
        cpu = CPU(limite_ciclos)
        try:
            c.cpu = cpu.ejecutar(c.codigo_cpu, direcciones, tipos)
        except ErrorEjecucion:
            c.cpu = cpu.resultado()  # salida y métricas parciales hasta el error
            raise

    pasos = [
        fase_lexico, fase_sintactico, fase_semantico,
        fase_intermedio, fase_registros, fase_simulacion,
    ]  # fmt: skip
    try:
        for nombre_fase, paso in zip(FASES[:hasta_fase], pasos, strict=False):
            paso()
            c.fases_completadas.append(nombre_fase)
    except ErrorCompilador as error:
        c.error = error
    return c


def compilar_a_reporte(codigo: str, **opciones: Any) -> dict[str, Any]:
    """Atajo: compila y devuelve directamente el diccionario del reporte."""
    return compilar(codigo, **opciones).a_reporte()


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------


@cache
def cargar_esquema() -> dict[str, Any]:
    """Lee el esquema empaquetado junto al código (funciona instalado o en Docker)."""
    texto = (
        resources.files("minicompilador")
        .joinpath("esquemas/reporte.schema.json")
        .read_text(encoding="utf-8")
    )
    esquema = json.loads(texto)
    Draft202012Validator.check_schema(esquema)  # el propio esquema debe ser válido
    return esquema


def errores_de_esquema(reporte: dict[str, Any]) -> list[str]:
    """Lista de violaciones del esquema (vacía si el reporte es válido)."""
    validador = Draft202012Validator(cargar_esquema())
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '(raíz)'}: {e.message}"
        for e in sorted(validador.iter_errors(reporte), key=lambda e: list(e.absolute_path))
    ]
