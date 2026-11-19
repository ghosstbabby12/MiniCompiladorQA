"""Interfaz de línea de comandos.

Ejemplos::

    python -m minicompilador ejemplos/validos/programa_especificacion.mini
    python -m minicompilador programa.mini --explicar
    python -m minicompilador programa.mini --fase 3 --json

Códigos de salida (útiles en scripts y CI):
    0 = compiló y ejecutó sin errores
    1 = el programa Mini tiene un error (léxico, sintáctico, semántico o de ejecución)
    2 = uso incorrecto del CLI (archivo inexistente, argumentos inválidos)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from minicompilador import __version__
from minicompilador.cpu import LIMITE_CICLOS_POR_DEFECTO
from minicompilador.errores import FASES, NOMBRES_FASES
from minicompilador.explicador import explicar
from minicompilador.reporte import compilar

SALIDA_OK, SALIDA_ERROR_PROGRAMA, SALIDA_ERROR_USO = 0, 1, 2


def _crear_parser() -> argparse.ArgumentParser:
    fases = ", ".join(f"{i}={NOMBRES_FASES[f]}" for i, f in enumerate(FASES, start=1))
    parser = argparse.ArgumentParser(
        prog="minicompilador",
        description="Compilador didáctico del lenguaje Mini (6 fases).",
    )
    parser.add_argument("archivo", type=Path, help="archivo .mini a compilar")
    parser.add_argument(
        "--explicar", action="store_true", help="explica cada fase en lenguaje sencillo"
    )
    parser.add_argument(
        "--fase",
        type=int,
        choices=range(1, len(FASES) + 1),
        default=len(FASES),
        metavar="N",
        help=f"detenerse después de la fase N ({fases})",
    )
    parser.add_argument("--json", action="store_true", help="imprime el reporte JSON completo")
    parser.add_argument(
        "--limite-ciclos",
        type=int,
        default=LIMITE_CICLOS_POR_DEFECTO,
        help=f"ciclos máximos del simulador (por defecto {LIMITE_CICLOS_POR_DEFECTO})",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _crear_parser().parse_args(argv)

    try:
        codigo = args.archivo.read_text(encoding="utf-8")
    except OSError as error:
        print(f"No se pudo leer '{args.archivo}': {error.strerror}", file=sys.stderr)
        return SALIDA_ERROR_USO

    compilacion = compilar(codigo, hasta_fase=args.fase, limite_ciclos=args.limite_ciclos)

    if args.json:
        print(json.dumps(compilacion.a_reporte(), ensure_ascii=False, indent=2))
    elif args.explicar:
        print(explicar(compilacion), end="")
    else:
        _imprimir_resumen(compilacion)

    return SALIDA_OK if compilacion.exito else SALIDA_ERROR_PROGRAMA


def _imprimir_resumen(compilacion) -> None:
    """Salida por defecto: lo que imprimió el programa, o el error."""
    if compilacion.cpu is not None:
        for linea in compilacion.cpu.salida:
            print(linea)
    for advertencia in compilacion.advertencias:
        print(f"⚠ línea {advertencia.linea}: {advertencia.mensaje}", file=sys.stderr)
    if compilacion.error is not None:
        print(f"✘ {compilacion.error}", file=sys.stderr)
    else:
        print(f"✔ Fase alcanzada: {NOMBRES_FASES[compilacion.fase_alcanzada]}", file=sys.stderr)
