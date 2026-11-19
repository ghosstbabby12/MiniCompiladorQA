"""Fase 5 - Asignación de registros (algoritmo *linear scan*).

La CPU simulada tiene SOLO 4 registros (R0-R3). Los registros son la memoria
más rápida: leerlos no cuesta accesos a memoria. Esta fase decide en qué
registro vive cada temporal; si no alcanzan, la temporal se guarda en memoria
(*spill*), lo que la hace más lenta de usar.

Algoritmo, en 3 pasos:

1. INTERVALOS DE VIDA. Para cada temporal se calcula ``[inicio, fin]``:
   ``inicio`` = instrucción que la define, ``fin`` = última instrucción que la
   lee. Las temporales nacen y mueren dentro de UNA sentencia, por eso estos
   intervalos lineales son correctos aunque haya bucles.

2. RECORRIDO LINEAL (Poletto & Sarkar, 1999). Se recorren los intervalos por
   orden de inicio. Antes de asignar, se liberan los registros cuyas
   temporales ya murieron. Si queda un registro libre, se asigna el de número
   más bajo (determinista: facilita probar y explicar).

3. SPILL. Si los 4 registros están ocupados, la NUEVA temporal se guarda en
   memoria, en la "zona de spill" (direcciones 2000, 2004...).

Regla de vida (importante para entender los valores límite): una temporal
muere DESPUÉS de la instrucción donde se usa por última vez. En
``%t4 = %t2 + %t3``, ``%t2`` y ``%t3`` siguen vivas mientras se calcula ``%t4``,
así que ``%t4`` necesita un registro distinto. Esto evita que la CPU
sobrescriba un operando antes de leerlo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from minicompilador.errores import Advertencia
from minicompilador.intermedio import (
    Copia,
    Imprimir,
    Instruccion,
    OperacionBinaria,
    Operando,
    SaltoSiFalso,
    es_temporal,
)

NOMBRES_REGISTROS: tuple[str, ...] = ("R0", "R1", "R2", "R3")
NUM_REGISTROS = len(NOMBRES_REGISTROS)
DIRECCION_BASE_SPILL = 2000
TAMANO_PALABRA = 4


@dataclass(frozen=True)
class Intervalo:
    """Vida de una temporal: desde la instrucción ``inicio`` hasta ``fin`` (inclusive)."""

    temporal: str
    inicio: int
    fin: int

    def vivo_en(self, posicion: int) -> bool:
        return self.inicio <= posicion <= self.fin


@dataclass
class ResultadoRegistros:
    #: temporal → "R0".."R3" o "MEM[2000]" si hubo spill.
    asignacion: dict[str, str]
    intervalos: list[Intervalo]
    #: registros ocupados al mismo tiempo (nunca más de 4).
    max_registros_simultaneos: int
    #: temporales vivas al mismo tiempo (la "demanda"; puede superar 4).
    max_temporales_vivas: int
    #: temporales enviadas a memoria, con su dirección.
    direcciones_spill: dict[str, int] = field(default_factory=dict)
    advertencias: list[Advertencia] = field(default_factory=list)

    @property
    def spills(self) -> int:
        return len(self.direcciones_spill)

    def registro_de(self, temporal: str) -> str | None:
        """Nombre del registro de la temporal, o ``None`` si vive en memoria."""
        ubicacion = self.asignacion[temporal]
        return ubicacion if ubicacion in NOMBRES_REGISTROS else None


# ---------------------------------------------------------------------------
# Paso 1: intervalos de vida
# ---------------------------------------------------------------------------


def operandos_leidos(instruccion: Instruccion) -> list[Operando]:
    """Operandos que la instrucción LEE (no el destino)."""
    match instruccion:
        case OperacionBinaria(izquierda=izquierda, derecha=derecha):
            return [izquierda, derecha]
        case Copia(fuente=fuente):
            return [fuente]
        case SaltoSiFalso(condicion=condicion):
            return [condicion]
        case Imprimir(valor=valor):
            return [valor]
    return []


def calcular_intervalos(instrucciones: list[Instruccion]) -> list[Intervalo]:
    """Recorre el TAC una vez y devuelve los intervalos ordenados por inicio."""
    inicio: dict[str, int] = {}
    fin: dict[str, int] = {}
    for posicion, instruccion in enumerate(instrucciones):
        for operando in operandos_leidos(instruccion):
            if es_temporal(operando):
                fin[operando] = posicion
        if isinstance(instruccion, OperacionBinaria) and es_temporal(instruccion.destino):
            inicio[instruccion.destino] = posicion
            fin.setdefault(instruccion.destino, posicion)  # temporal que nadie lee
    return sorted(
        (Intervalo(t, inicio[t], fin[t]) for t in inicio),
        key=lambda intervalo: intervalo.inicio,
    )


# ---------------------------------------------------------------------------
# Pasos 2 y 3: recorrido lineal con spill
# ---------------------------------------------------------------------------


def asignar_registros(instrucciones: list[Instruccion]) -> ResultadoRegistros:
    intervalos = calcular_intervalos(instrucciones)
    asignacion: dict[str, str] = {}
    direcciones_spill: dict[str, int] = {}
    activos: list[Intervalo] = []  # temporales que HOY ocupan un registro
    libres = list(NOMBRES_REGISTROS)
    max_registros = 0

    for intervalo in intervalos:
        # Liberar registros de temporales que murieron ANTES de esta instrucción.
        for muerto in [a for a in activos if a.fin < intervalo.inicio]:
            activos.remove(muerto)
            libres.append(asignacion[muerto.temporal])
        libres.sort()  # siempre el registro de número más bajo

        if libres:
            asignacion[intervalo.temporal] = libres.pop(0)
            activos.append(intervalo)
            max_registros = max(max_registros, len(activos))
        else:
            direccion = DIRECCION_BASE_SPILL + TAMANO_PALABRA * len(direcciones_spill)
            direcciones_spill[intervalo.temporal] = direccion
            asignacion[intervalo.temporal] = f"MEM[{direccion}]"

    advertencias = [
        Advertencia(
            "SPILL",
            f"No hay registros libres para {temporal}: se guarda en memoria (dirección "
            f"{direccion}), lo que cuesta accesos extra.",
            instrucciones[_inicio_de(intervalos, temporal)].linea,
            None,
            "Divide la expresión en varias sentencias con variables intermedias.",
            fase="registros",
        )
        for temporal, direccion in direcciones_spill.items()
    ]

    return ResultadoRegistros(
        asignacion=asignacion,
        intervalos=intervalos,
        max_registros_simultaneos=max_registros,
        max_temporales_vivas=_max_vivas(intervalos),
        direcciones_spill=direcciones_spill,
        advertencias=advertencias,
    )


def _inicio_de(intervalos: list[Intervalo], temporal: str) -> int:
    return next(i.inicio for i in intervalos if i.temporal == temporal)


def _max_vivas(intervalos: list[Intervalo]) -> int:
    """Máximo de intervalos que se solapan en una misma instrucción.

    Algoritmo de BARRIDO (sweep line), O(n log n): cada intervalo aporta un
    evento "+1" en su inicio y "-1" en su fin; se recorren en orden y se
    guarda el máximo del contador. En la misma posición los inicios van antes
    que los fines porque los intervalos son cerrados (vivo_en usa <=).

    La versión anterior comparaba cada intervalo con todos (O(n²)); el
    análisis de carga la señaló como la parte más cara de la fase de
    registros con programas largos. La prueba la compara con esa versión
    ingenua como ORÁCULO.
    """
    eventos = sorted(
        [(i.inicio, 0) for i in intervalos] + [(i.fin, 1) for i in intervalos]
    )  # (posición, 0 = nace / 1 = muere): 0 ordena antes que 1
    vivas = maximo = 0
    for _posicion, tipo in eventos:
        vivas += 1 if tipo == 0 else -1
        maximo = max(maximo, vivas)
    return maximo
