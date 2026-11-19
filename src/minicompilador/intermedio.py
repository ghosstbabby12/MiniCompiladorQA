"""Fase 4 - Código intermedio de tres direcciones (TAC).

"Tres direcciones" = cada instrucción tiene como máximo un destino y dos
operandos: ``destino = operando1 op operando2``. Es un punto medio entre el
árbol (fácil de analizar) y el ensamblador (fácil de ejecutar).

    c = a + b * 2;          %t1 = b * 2
                    ──►     %t2 = a + %t1
                            c = %t2

¿Cómo se genera? Con un RECORRIDO DFS EN POSTORDEN mediante el patrón Visitor:
para un ``BinOp`` primero se visita el hijo izquierdo, luego el derecho y AL
FINAL el propio nodo. Así, cuando se emite ``%t2 = a + %t1``, ``%t1`` ya fue
calculado. El postorden respeta automáticamente la precedencia porque el
parser dejó las operaciones más fuertes más abajo en el árbol.

Temporales: ``nueva_temporal()`` crea ``%t1``, ``%t2``... El prefijo ``%`` es
imposible de escribir para el usuario (el lexer rechaza ``%a``), así que una
temporal NUNCA choca con una variable del programa.

Control de flujo: se usan etiquetas (``L1:``) y saltos (``goto``, ``ifFalse``).

Optimización: PLEGADO DE CONSTANTES. Si ambos operandos son literales, la
operación se calcula en compilación (``2 * 3`` → ``6``) y no se emite
instrucción. Excepción: ``x / 0`` NO se pliega, para que el error ocurra en
ejecución con su mensaje explicativo (el optimizador nunca debe ocultar errores).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from minicompilador.ast_nodos import (
    Asignacion,
    BinOp,
    Declaracion,
    If,
    Nodo,
    Numero,
    Print,
    Programa,
    Variable,
    Visitante,
    While,
)
from minicompilador.operaciones import evaluar_binaria

#: Un operando TAC: un nombre (variable o temporal, ``str``) o un literal.
Operando = str | int | float | bool

PREFIJO_TEMPORAL = "%t"


def formatear_operando(operando: Operando) -> str:
    """``True`` → ``true`` (sintaxis Mini); el resto tal cual."""
    if isinstance(operando, bool):
        return "true" if operando else "false"
    return str(operando)


def es_literal(operando: Operando) -> bool:
    """Los nombres son ``str``; todo lo demás es un valor conocido en compilación."""
    return not isinstance(operando, str)


def es_temporal(operando: Operando) -> bool:
    return isinstance(operando, str) and operando.startswith(PREFIJO_TEMPORAL)


# ---------------------------------------------------------------------------
# Instrucciones TAC (cada una sabe imprimirse)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Instruccion:
    #: línea del código Mini que originó la instrucción (para el modo explicación).
    linea: int = field(default=0, kw_only=True, compare=False)


@dataclass(frozen=True)
class Copia(Instruccion):
    """``destino = fuente``"""

    destino: str
    fuente: Operando

    def __str__(self) -> str:
        return f"{self.destino} = {formatear_operando(self.fuente)}"


@dataclass(frozen=True)
class OperacionBinaria(Instruccion):
    """``destino = izquierda op derecha``"""

    destino: str
    izquierda: Operando
    op: str
    derecha: Operando

    def __str__(self) -> str:
        izq, der = formatear_operando(self.izquierda), formatear_operando(self.derecha)
        return f"{self.destino} = {izq} {self.op} {der}"


@dataclass(frozen=True)
class Etiqueta(Instruccion):
    """``L1:`` - marca un destino de salto; no hace nada al ejecutarse."""

    nombre: str

    def __str__(self) -> str:
        return f"{self.nombre}:"


@dataclass(frozen=True)
class Salto(Instruccion):
    """``goto L1`` - salto incondicional."""

    etiqueta: str

    def __str__(self) -> str:
        return f"goto {self.etiqueta}"


@dataclass(frozen=True)
class SaltoSiFalso(Instruccion):
    """``ifFalse cond goto L1`` - salta si la condición es falsa (o 0)."""

    condicion: Operando
    etiqueta: str

    def __str__(self) -> str:
        return f"ifFalse {formatear_operando(self.condicion)} goto {self.etiqueta}"


@dataclass(frozen=True)
class Imprimir(Instruccion):
    """``print x``"""

    valor: Operando

    def __str__(self) -> str:
        return f"print {formatear_operando(self.valor)}"


@dataclass
class ResultadoIntermedio:
    instrucciones: list[Instruccion]
    #: temporal → instrucción que la define ("%t1" → "%t1 = b * 2").
    definiciones_temporales: dict[str, str]
    #: descripción de cada plegado de constantes realizado.
    optimizaciones: list[str]
    #: etiqueta de cada nodo en el orden en que TERMINÓ de visitarse (postorden).
    recorrido: list[str]

    @property
    def temporales(self) -> list[str]:
        return list(self.definiciones_temporales)

    @property
    def total_temporales(self) -> int:
        return len(self.definiciones_temporales)

    def como_texto(self) -> list[str]:
        """Sección ``codigo_intermedio`` del reporte."""
        return [str(instruccion) for instruccion in self.instrucciones]


# ---------------------------------------------------------------------------
# Generador (patrón Visitor, DFS postorden)
# ---------------------------------------------------------------------------


class GeneradorIntermedio(Visitante):
    """Traduce el AST a TAC. Las expresiones DEVUELVEN el operando con su resultado."""

    def __init__(self, plegar_constantes: bool = True) -> None:
        self.plegar_constantes = plegar_constantes
        self._instrucciones: list[Instruccion] = []
        self._definiciones: dict[str, str] = {}
        self._optimizaciones: list[str] = []
        self._recorrido: list[str] = []
        self._contador_temporales = 0
        self._contador_etiquetas = 0

    def generar(self, programa: Programa) -> ResultadoIntermedio:
        self.visitar(programa)
        return ResultadoIntermedio(
            self._instrucciones, self._definiciones, self._optimizaciones, self._recorrido
        )

    # ------------------------------------------------------------ utilidades

    def nueva_temporal(self) -> str:
        """Devuelve ``%t1`` la primera vez, luego ``%t2``... (empieza en 1, no en 0)."""
        self._contador_temporales += 1
        return f"{PREFIJO_TEMPORAL}{self._contador_temporales}"

    def nueva_etiqueta(self) -> str:
        self._contador_etiquetas += 1
        return f"L{self._contador_etiquetas}"

    def _emitir(self, instruccion: Instruccion) -> None:
        self._instrucciones.append(instruccion)
        if isinstance(instruccion, OperacionBinaria) and es_temporal(instruccion.destino):
            self._definiciones[instruccion.destino] = str(instruccion)

    def _registrar_visita(self, nodo: Nodo) -> None:
        # Se llama al FINAL de cada visitar_*: por eso la lista queda en postorden.
        self._recorrido.append(nodo.etiqueta())

    # ------------------------------------------------------------ sentencias

    def visitar_programa(self, nodo: Programa) -> None:
        for sentencia in nodo.sentencias:
            self.visitar(sentencia)
        self._registrar_visita(nodo)

    def visitar_declaracion(self, nodo: Declaracion) -> None:
        # 'int c;' no genera código: el simulador reserva la celda con valor 0.
        if nodo.valor is not None:
            operando = self.visitar(nodo.valor)
            self._emitir(Copia(nodo.nombre, operando, linea=nodo.linea))
        self._registrar_visita(nodo)

    def visitar_asignacion(self, nodo: Asignacion) -> None:
        operando = self.visitar(nodo.valor)
        self._emitir(Copia(nodo.nombre, operando, linea=nodo.linea))
        self._registrar_visita(nodo)

    def visitar_if(self, nodo: If) -> None:
        """Esquema::

        ifFalse cond goto L_sino         (sin else: goto L_fin)
        <entonces>
        goto L_fin                       (solo si hay else)
        L_sino:
        <sino>
        L_fin:
        """
        condicion = self.visitar(nodo.condicion)
        etiqueta_sino = self.nueva_etiqueta()
        self._emitir(SaltoSiFalso(condicion, etiqueta_sino, linea=nodo.linea))
        for sentencia in nodo.entonces:
            self.visitar(sentencia)
        if nodo.sino is None:
            self._emitir(Etiqueta(etiqueta_sino, linea=nodo.linea))
        else:
            etiqueta_fin = self.nueva_etiqueta()
            self._emitir(Salto(etiqueta_fin, linea=nodo.linea))
            self._emitir(Etiqueta(etiqueta_sino, linea=nodo.linea))
            for sentencia in nodo.sino:
                self.visitar(sentencia)
            self._emitir(Etiqueta(etiqueta_fin, linea=nodo.linea))
        self._registrar_visita(nodo)

    def visitar_while(self, nodo: While) -> None:
        """Esquema::

        L_inicio:
        <cond>                   (se recalcula en CADA vuelta)
        ifFalse cond goto L_fin
        <cuerpo>
        goto L_inicio
        L_fin:
        """
        etiqueta_inicio = self.nueva_etiqueta()
        etiqueta_fin = self.nueva_etiqueta()
        self._emitir(Etiqueta(etiqueta_inicio, linea=nodo.linea))
        condicion = self.visitar(nodo.condicion)
        self._emitir(SaltoSiFalso(condicion, etiqueta_fin, linea=nodo.linea))
        for sentencia in nodo.cuerpo:
            self.visitar(sentencia)
        self._emitir(Salto(etiqueta_inicio, linea=nodo.linea))
        self._emitir(Etiqueta(etiqueta_fin, linea=nodo.linea))
        self._registrar_visita(nodo)

    def visitar_print(self, nodo: Print) -> None:
        operando = self.visitar(nodo.expresion)
        self._emitir(Imprimir(operando, linea=nodo.linea))
        self._registrar_visita(nodo)

    # ----------------------------------------------------------- expresiones

    def visitar_numero(self, nodo: Numero) -> Operando:
        self._registrar_visita(nodo)
        return nodo.valor

    def visitar_variable(self, nodo: Variable) -> Operando:
        self._registrar_visita(nodo)
        return nodo.nombre

    def visitar_binop(self, nodo: BinOp) -> Operando:
        # DFS postorden: izquierda → derecha → nodo actual.
        izquierda = self.visitar(nodo.izquierda)
        derecha = self.visitar(nodo.derecha)
        self._registrar_visita(nodo)

        if self.plegar_constantes and es_literal(izquierda) and es_literal(derecha):
            try:
                resultado = evaluar_binaria(nodo.op, izquierda, derecha)
            except (ZeroDivisionError, OverflowError):
                pass  # no se pliega: el error debe verse en ejecución, con su línea
            else:
                texto = f"{formatear_operando(izquierda)} {nodo.op} {formatear_operando(derecha)}"
                self._optimizaciones.append(
                    f"Línea {nodo.linea}: {texto} → {formatear_operando(resultado)}"
                )
                return resultado

        temporal = self.nueva_temporal()
        self._emitir(OperacionBinaria(temporal, izquierda, nodo.op, derecha, linea=nodo.linea))
        return temporal


def generar_intermedio(programa: Programa, plegar_constantes: bool = True) -> ResultadoIntermedio:
    """Atajo funcional para la fase de código intermedio."""
    return GeneradorIntermedio(plegar_constantes).generar(programa)
