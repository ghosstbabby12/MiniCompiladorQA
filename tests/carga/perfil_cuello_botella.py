"""Análisis del cuello de botella (complementa la prueba de carga).

Locust dice CUÁNTO tarda la API; este script dice DÓNDE se va el tiempo y
por qué existe ``PROFUNDIDAD_MAXIMA`` en el parser.

    python tests/carga/perfil_cuello_botella.py

Mide:
  1. Tiempo de cada fase para el programa largo de la prueba de carga.
  2. Profundidad de recursión: marcos de pila de Python y tiempo según cuántos
     paréntesis anidados tenga una expresión, hasta el límite del parser.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from locustfile import PROGRAMA_LARGO  # noqa: E402

from minicompilador.errores import FASES, NOMBRES_FASES  # noqa: E402
from minicompilador.parser import PROFUNDIDAD_MAXIMA, Parser  # noqa: E402
from minicompilador.reporte import compilar  # noqa: E402

REPETICIONES = 30


def cronometrar(funcion, repeticiones: int = REPETICIONES) -> float:
    """Mediana en milisegundos (la mediana resiste picos del sistema operativo)."""
    tiempos = []
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        funcion()
        tiempos.append((time.perf_counter() - inicio) * 1000)
    return sorted(tiempos)[len(tiempos) // 2]


def tiempo_por_fase(codigo: str) -> None:
    print(f"1) Tiempo por fase - programa largo ({len(codigo)} caracteres)")
    anterior = 0.0
    for numero, fase in enumerate(FASES, start=1):
        acumulado = cronometrar(lambda n=numero: compilar(codigo, hasta_fase=n))
        print(f"   {NOMBRES_FASES[fase]:<22} {acumulado - anterior:7.2f} ms")
        anterior = acumulado
    print(f"   {'TOTAL':<22} {anterior:7.2f} ms\n")


def marcos_maximos(codigo: str) -> int:
    """Profundidad máxima de la pila de Python mientras se parsea."""
    maximo = 0

    def trazar(marco, evento, _arg):
        nonlocal maximo
        if evento == "call":
            profundidad, f = 0, marco
            while f is not None:
                profundidad, f = profundidad + 1, f.f_back
            maximo = max(maximo, profundidad)
        return None

    from minicompilador.lexer import tokenizar

    tokens = tokenizar(codigo)
    sys.settrace(trazar)
    try:
        Parser(tokens).parsear()
    finally:
        sys.settrace(None)
    return maximo


def recursion_del_parser() -> None:
    print("2) Paréntesis anidados → recursión del parser")
    print(f"   límite de recursión de Python: {sys.getrecursionlimit()} marcos")
    print("   anidamiento   marcos de pila   tiempo (compilar completo)")
    for niveles in (1, 25, 50, 75, PROFUNDIDAD_MAXIMA - 2):
        codigo = f"int x = {'(' * niveles}1{')' * niveles};"
        marcos = marcos_maximos(codigo)
        ms = cronometrar(lambda c=codigo: compilar(c))
        print(f"   {niveles:>11}   {marcos:>14}   {ms:8.2f} ms")
    demasiado = f"int x = {'(' * (PROFUNDIDAD_MAXIMA + 1)}1{')' * (PROFUNDIDAD_MAXIMA + 1)};"
    error = compilar(demasiado).error
    print(f"   {PROFUNDIDAD_MAXIMA + 1:>11}   → {type(error).__name__}: {error.mensaje[:60]}...")


if __name__ == "__main__":
    tiempo_por_fase(PROGRAMA_LARGO)
    recursion_del_parser()
