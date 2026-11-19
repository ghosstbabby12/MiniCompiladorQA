"""Semántica de los operadores de Mini (fuente única de verdad).

¿Por qué un módulo aparte? Dos fases calculan operaciones:
    * el código intermedio, al PLEGAR CONSTANTES en tiempo de compilación
      (``2 * 3`` → ``6``), y
    * el simulador de CPU, al EJECUTAR el programa.
Si cada una tuviera su propia implementación, podrían dar resultados
distintos (un bug muy difícil de encontrar). Compartir esta función garantiza
que "optimizar" nunca cambie el resultado del programa.

Mini sigue la semántica de C/Java, que difiere de Python con negativos:

    ===========  ========  ======================
    Expresión    Mini (C)  Python (``//`` y ``%``)
    ===========  ========  ======================
    ``-7 / 2``   ``-3``    ``-4``  (Python redondea hacia -∞)
    ``-7 % 2``   ``-1``    ``1``   (en C el signo es el del dividendo)
    ===========  ========  ======================

Rango numérico (igual que ``int``/``double`` en C y Java):
    * ``int`` es de 32 bits con signo: [-2147483648, 2147483647].
    * ``float`` debe ser finito (sin ``inf`` ni ``nan``).
Python no tiene esos límites (sus enteros crecen sin fin), así que los
imponemos aquí. Además es necesario para el contrato: ``inf`` no es JSON
válido y un entero de miles de dígitos no se puede convertir a texto.
"""

from __future__ import annotations

import math

Valor = int | float | bool

OPERADORES_ARITMETICOS = frozenset({"+", "-", "*", "/", "%"})
OPERADORES_RELACIONALES = frozenset({"<", ">", "<=", ">=", "==", "!="})

ENTERO_MINIMO = -(2**31)
ENTERO_MAXIMO = 2**31 - 1


def _son_enteros(izquierda: Valor, derecha: Valor) -> bool:
    # bool es subclase de int en Python; aquí solo cuentan los enteros "de verdad".
    return all(isinstance(v, int) and not isinstance(v, bool) for v in (izquierda, derecha))


def division_entera_c(dividendo: int, divisor: int) -> int:
    """División entera truncando hacia cero, como en C (sin pasar por float)."""
    cociente = abs(dividendo) // abs(divisor)
    return cociente if (dividendo < 0) == (divisor < 0) else -cociente


def verificar_rango(valor: Valor) -> Valor:
    """Devuelve ``valor`` si cabe en los tipos de Mini.

    Raises:
        OverflowError: entero fuera de 32 bits o real no finito.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, int) and not ENTERO_MINIMO <= valor <= ENTERO_MAXIMO:
        raise OverflowError(f"{valor} no cabe en un int de 32 bits")
    if isinstance(valor, float) and not math.isfinite(valor):
        raise OverflowError("el resultado real es demasiado grande (infinito)")
    return valor


def evaluar_binaria(op: str, izquierda: Valor, derecha: Valor) -> Valor:
    """Calcula ``izquierda op derecha`` con la semántica de Mini.

    Raises:
        ZeroDivisionError: en ``/`` o ``%`` con divisor 0.
        OverflowError: si el resultado se sale del rango de su tipo.
            En ambos casos quien llama decide qué hacer: el optimizador NO
            pliega y el simulador lanza ErrorEjecucion con la línea.
        ValueError: si el operador no existe en Mini.
    """
    if op in ("/", "%") and derecha == 0:
        raise ZeroDivisionError(f"{izquierda} {op} 0")
    return verificar_rango(_calcular(op, izquierda, derecha))


def _calcular(op: str, izquierda: Valor, derecha: Valor) -> Valor:
    match op:
        case "+":
            return izquierda + derecha
        case "-":
            return izquierda - derecha
        case "*":
            return izquierda * derecha
        case "/":
            if _son_enteros(izquierda, derecha):
                return division_entera_c(izquierda, derecha)
            return izquierda / derecha
        case "%":
            if _son_enteros(izquierda, derecha):
                return izquierda - derecha * division_entera_c(izquierda, derecha)
            return math.fmod(izquierda, derecha)
        case "<":
            return izquierda < derecha
        case ">":
            return izquierda > derecha
        case "<=":
            return izquierda <= derecha
        case ">=":
            return izquierda >= derecha
        case "==":
            return izquierda == derecha
        case "!=":
            return izquierda != derecha
    raise ValueError(f"Operador desconocido en Mini: '{op}'")
