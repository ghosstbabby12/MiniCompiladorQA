"""Fase 6 - Traducción a la ISA y simulador de CPU + memoria.

ISA mínima (14 instrucciones)
=============================

==========================  =================================================
Instrucción                 Significado
==========================  =================================================
``LOAD  Rd, [x]``           Rd ← memoria[x]                 (1 lectura)
``STORE [x], Rs``           memoria[x] ← Rs                 (1 escritura)
``MOV   d, s``              d ← s  (cualquier combinación de reg/mem/#inmediato)
``ADD/SUB/MUL/DIV/MOD d, a, b``  d ← a op b
``CMP   d, a, b, COND``     d ← 1 si (a COND b) si no 0. COND: LT GT LE GE EQ NE
``JMP   L``                 salta a la etiqueta L
``JZ    s, L``              salta a L si s es 0/false
``JNZ   s, L``              salta a L si s NO es 0/false
``PRINT s``                 agrega s a la salida
``HALT``                    detiene la CPU
==========================  =================================================

Operandos: ``R0``-``R3`` (registro), ``[a]`` (memoria), ``#5`` (inmediato).

Memoria TIPADA: la memoria es un ``dict`` dirección → valor y conoce el tipo de
cada variable (de la tabla de símbolos). Al escribir en una variable ``int`` un
valor float, se TRUNCA (``int c = 6.5`` → 6); al escribir un int en una
variable ``float``, se PROMUEVE (5 → 5.0). Así la ISA no necesita
instrucciones de conversión.

Costo: cada instrucción cuesta 1 ciclo + ``COSTO_ACCESO_MEMORIA`` ciclos por
cada lectura o escritura en memoria (la memoria es más lenta que un registro).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minicompilador.errores import ErrorEjecucion
from minicompilador.intermedio import (
    Copia,
    Etiqueta,
    Imprimir,
    Instruccion,
    OperacionBinaria,
    Operando,
    Salto,
    SaltoSiFalso,
    es_temporal,
    formatear_operando,
)
from minicompilador.operaciones import evaluar_binaria, verificar_rango
from minicompilador.registros import NUM_REGISTROS, ResultadoRegistros

LIMITE_CICLOS_POR_DEFECTO = 100_000
COSTO_ACCESO_MEMORIA = 2

OPCODES = frozenset(
    {
        "LOAD", "STORE", "MOV", "ADD", "SUB", "MUL", "DIV", "MOD",
        "CMP", "JMP", "JZ", "JNZ", "PRINT", "HALT",
    }
)  # fmt: skip
#: Pseudo-instrucción: marca una etiqueta en el listado; el ensamblador la quita.
ETIQUETA = "ETIQUETA"

OPCODE_ARITMETICO = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "%": "MOD"}
CONDICION_CMP = {"<": "LT", ">": "GT", "<=": "LE", ">=": "GE", "==": "EQ", "!=": "NE"}
OPERADOR_DE = {v: k for k, v in {**OPCODE_ARITMETICO, **CONDICION_CMP}.items()}


# ---------------------------------------------------------------------------
# Operandos e instrucciones de la ISA
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Registro:
    numero: int

    def __str__(self) -> str:
        return f"R{self.numero}"


@dataclass(frozen=True)
class Memoria:
    nombre: str  # variable o temporal con spill; el ensamblador lo traduce a dirección

    def __str__(self) -> str:
        return f"[{self.nombre}]"


@dataclass(frozen=True)
class Inmediato:
    valor: int | float | bool

    def __str__(self) -> str:
        return f"#{formatear_operando(self.valor)}"


@dataclass(frozen=True)
class RefEtiqueta:
    nombre: str

    def __str__(self) -> str:
        return self.nombre


OperandoCPU = Registro | Memoria | Inmediato | RefEtiqueta


@dataclass(frozen=True)
class InstruccionCPU:
    opcode: str
    operandos: tuple[OperandoCPU, ...] = ()
    condicion: str | None = None  # solo para CMP
    linea: int = field(default=0, compare=False)  # línea del código Mini

    def __str__(self) -> str:
        if self.opcode == ETIQUETA:
            return f"{self.operandos[0]}:"
        partes = [str(operando) for operando in self.operandos]
        if self.condicion:
            partes.append(self.condicion)
        return f"{self.opcode} {', '.join(partes)}".rstrip()


# ---------------------------------------------------------------------------
# Traducción TAC → ISA (selección de instrucciones)
# ---------------------------------------------------------------------------


def traducir_a_cpu(
    instrucciones: list[Instruccion], registros: ResultadoRegistros
) -> list[InstruccionCPU]:
    """Convierte cada instrucción TAC en 1-2 instrucciones de la ISA.

    Patrón para ``%t = a op b`` cuando ``%t`` tiene registro Rd:
        el primer operando se lleva a Rd (``LOAD`` si está en memoria, ``MOV``
        si es inmediato) y luego se opera sobre Rd. Ej: ``%t1 = b * 2`` →
        ``LOAD R0, [b]`` + ``MUL R0, R0, #2``.
    Si ``%t`` hizo spill, la operación escribe directo en memoria (más costoso).
    """

    def ubicar(operando: Operando) -> Registro | Memoria | Inmediato:
        if es_temporal(operando):
            registro = registros.registro_de(operando)
            return Registro(int(registro[1:])) if registro else Memoria(operando)
        if isinstance(operando, str):
            return Memoria(operando)
        return Inmediato(operando)

    codigo: list[InstruccionCPU] = []
    for instruccion in instrucciones:
        linea = instruccion.linea
        match instruccion:
            case OperacionBinaria(destino=destino, izquierda=izq, op=op, derecha=der):
                d, a, b = ubicar(destino), ubicar(izq), ubicar(der)
                if isinstance(d, Registro) and not isinstance(a, Registro):
                    carga = "LOAD" if isinstance(a, Memoria) else "MOV"
                    codigo.append(InstruccionCPU(carga, (d, a), linea=linea))
                    a = d
                if op in CONDICION_CMP:
                    codigo.append(InstruccionCPU("CMP", (d, a, b), CONDICION_CMP[op], linea=linea))
                else:
                    codigo.append(InstruccionCPU(OPCODE_ARITMETICO[op], (d, a, b), linea=linea))
            case Copia(destino=destino, fuente=fuente):
                origen = ubicar(fuente)
                opcode = "STORE" if isinstance(origen, Registro) else "MOV"
                codigo.append(InstruccionCPU(opcode, (Memoria(destino), origen), linea=linea))
            case Etiqueta(nombre=nombre):
                codigo.append(InstruccionCPU(ETIQUETA, (RefEtiqueta(nombre),), linea=linea))
            case Salto(etiqueta=etiqueta):
                codigo.append(InstruccionCPU("JMP", (RefEtiqueta(etiqueta),), linea=linea))
            case SaltoSiFalso(condicion=condicion, etiqueta=etiqueta):
                operandos = (ubicar(condicion), RefEtiqueta(etiqueta))
                codigo.append(InstruccionCPU("JZ", operandos, linea=linea))
            case Imprimir(valor=valor):
                codigo.append(InstruccionCPU("PRINT", (ubicar(valor),), linea=linea))
            case _:
                raise ValueError(f"Instrucción TAC sin traducción: {instruccion!r}")
    codigo.append(InstruccionCPU("HALT"))
    return codigo


# ---------------------------------------------------------------------------
# Simulador
# ---------------------------------------------------------------------------


@dataclass
class ResultadoCPU:
    salida: list[str]
    memoria_final: dict[str, Any]
    registros: list[Any]
    ciclos: int
    lecturas_memoria: int
    escrituras_memoria: int
    instrucciones_ejecutadas: int

    def metricas(self) -> dict[str, int]:
        return {
            "ciclos": self.ciclos,
            "lecturas_memoria": self.lecturas_memoria,
            "escrituras_memoria": self.escrituras_memoria,
            "instrucciones_ejecutadas": self.instrucciones_ejecutadas,
        }


def formatear_valor(valor: Any) -> str:
    """Cómo muestra PRINT un valor: ``true``/``false`` para bool."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def _cero_de(tipo: str) -> int | float | bool:
    return {"int": 0, "float": 0.0, "bool": False}[tipo]


class CPU:
    """CPU de 4 registros con memoria tipada, contadores y límite de ciclos."""

    def __init__(
        self,
        limite_ciclos: int = LIMITE_CICLOS_POR_DEFECTO,
        costo_acceso_memoria: int = COSTO_ACCESO_MEMORIA,
    ) -> None:
        self.limite_ciclos = limite_ciclos
        self.costo_acceso_memoria = costo_acceso_memoria
        self._reiniciar({}, {})

    def _reiniciar(self, direcciones: dict[str, int], tipos: dict[str, str]) -> None:
        self.registros: list[Any] = [0] * NUM_REGISTROS
        self.memoria: dict[int, Any] = {}
        self.direcciones = direcciones
        self.tipos = tipos
        self.salida: list[str] = []
        self.ciclos = 0
        self.lecturas = 0
        self.escrituras = 0
        self.instrucciones_ejecutadas = 0

    # ------------------------------------------------------------------ API

    def ejecutar(
        self,
        programa: list[InstruccionCPU],
        direcciones: dict[str, int],
        tipos: dict[str, str],
    ) -> ResultadoCPU:
        """Ejecuta el programa.

        Args:
            programa: instrucciones (puede incluir pseudo-instrucciones ETIQUETA).
            direcciones: nombre → dirección (variables y temporales con spill).
            tipos: nombre → tipo de cada VARIABLE (para la memoria tipada).

        Raises:
            ErrorEjecucion: división por cero o límite de ciclos superado. El
                estado parcial (salida, métricas) queda disponible en
                ``resultado()`` para el reporte.
            ValueError: programa mal formado (bug del traductor, no del usuario).
        """
        self._reiniciar(direcciones, tipos)
        codigo, etiquetas = self._ensamblar(programa)
        for nombre, tipo in tipos.items():
            self.memoria[direcciones[nombre]] = _cero_de(tipo)  # 'int c;' vale 0

        pc = 0  # contador de programa: índice de la próxima instrucción
        while pc < len(codigo):
            instruccion = codigo[pc]
            pc += 1
            accesos_previos = self.lecturas + self.escrituras
            try:
                salto = self._ejecutar_instruccion(instruccion, etiquetas)
            except OverflowError as desbordamiento:
                raise ErrorEjecucion(
                    f"Desbordamiento en la línea {instruccion.linea}: {desbordamiento}.",
                    instruccion.linea or None,
                    sugerencia="Un int de Mini va de -2147483648 a 2147483647; usa valores "
                    "más pequeños o revisa que el bucle termine antes.",
                ) from None
            self.instrucciones_ejecutadas += 1
            accesos = self.lecturas + self.escrituras - accesos_previos
            self.ciclos += 1 + self.costo_acceso_memoria * accesos

            # Valor límite: llegar EXACTAMENTE al límite está permitido; pasarlo no.
            if self.ciclos > self.limite_ciclos:
                raise ErrorEjecucion(
                    f"Se superó el límite de {self.limite_ciclos} ciclos: probablemente hay "
                    "un bucle infinito (la condición del while nunca se vuelve falsa).",
                    instruccion.linea or None,
                    sugerencia="Revisa que el cuerpo del while modifique la variable de la "
                    "condición, o aumenta el límite con --limite-ciclos.",
                )
            if instruccion.opcode == "HALT":
                break
            if salto is not None:
                pc = salto
        return self.resultado()

    def resultado(self) -> ResultadoCPU:
        """Estado actual (también útil tras un error, para el reporte parcial)."""
        return ResultadoCPU(
            salida=list(self.salida),
            memoria_final={n: self.memoria.get(self.direcciones[n]) for n in self.tipos},
            registros=list(self.registros),
            ciclos=self.ciclos,
            lecturas_memoria=self.lecturas,
            escrituras_memoria=self.escrituras,
            instrucciones_ejecutadas=self.instrucciones_ejecutadas,
        )

    # ----------------------------------------------------------- ensamblador

    def _ensamblar(
        self, programa: list[InstruccionCPU]
    ) -> tuple[list[InstruccionCPU], dict[str, int]]:
        """Quita las etiquetas, recuerda a qué índice apunta cada una y valida."""
        codigo: list[InstruccionCPU] = []
        etiquetas: dict[str, int] = {}
        for instruccion in programa:
            if instruccion.opcode == ETIQUETA:
                etiquetas[instruccion.operandos[0].nombre] = len(codigo)
            elif instruccion.opcode in OPCODES:
                codigo.append(instruccion)
            else:
                raise ValueError(f"Opcode desconocido: {instruccion.opcode}")
        for instruccion in codigo:
            for operando in instruccion.operandos:
                if isinstance(operando, RefEtiqueta) and operando.nombre not in etiquetas:
                    raise ValueError(f"Etiqueta no definida: {operando.nombre}")
                if isinstance(operando, Registro) and not 0 <= operando.numero < NUM_REGISTROS:
                    raise ValueError(f"La CPU solo tiene R0-R{NUM_REGISTROS - 1}: {operando}")
                if isinstance(operando, Memoria) and operando.nombre not in self.direcciones:
                    raise ValueError(f"Sin dirección de memoria para {operando}")
        return codigo, etiquetas

    # ------------------------------------------------------------ ejecución

    def _leer(self, operando: OperandoCPU) -> Any:
        match operando:
            case Registro(numero=numero):
                return self.registros[numero]
            case Inmediato(valor=valor):
                return valor
            case Memoria(nombre=nombre):
                self.lecturas += 1
                return self.memoria.get(self.direcciones[nombre], 0)
        raise ValueError(f"Operando no legible: {operando}")

    def _escribir(self, operando: OperandoCPU, valor: Any) -> None:
        match operando:
            case Registro(numero=numero):
                self.registros[numero] = valor
            case Memoria(nombre=nombre):
                self.escrituras += 1
                self.memoria[self.direcciones[nombre]] = self._ajustar_tipo(nombre, valor)
            case _:
                raise ValueError(f"No se puede escribir en {operando}")

    def _ajustar_tipo(self, nombre: str, valor: Any) -> Any:
        """Memoria tipada: trunca float→int y promueve int→float según la variable."""
        tipo = self.tipos.get(nombre)  # las temporales con spill no tienen tipo
        if tipo == "int" and isinstance(valor, float):
            return verificar_rango(int(valor))  # int() trunca hacia cero, como C
        if tipo == "float" and isinstance(valor, int) and not isinstance(valor, bool):
            return float(valor)
        return valor

    def _ejecutar_instruccion(
        self, instruccion: InstruccionCPU, etiquetas: dict[str, int]
    ) -> int | None:
        """Ejecuta UNA instrucción. Devuelve el nuevo pc si hay salto."""
        op = instruccion.opcode
        args = instruccion.operandos
        match op:
            case "LOAD" | "STORE" | "MOV":
                self._escribir(args[0], self._leer(args[1]))
            case "ADD" | "SUB" | "MUL" | "DIV" | "MOD" | "CMP":
                simbolo = OPERADOR_DE[instruccion.condicion if op == "CMP" else op]
                izquierda, derecha = self._leer(args[1]), self._leer(args[2])
                try:
                    resultado = evaluar_binaria(simbolo, izquierda, derecha)
                except ZeroDivisionError:
                    nombre_op = "División" if op == "DIV" else "Módulo"
                    raise ErrorEjecucion(
                        f"{nombre_op} por cero en la línea {instruccion.linea}: se intentó "
                        f"calcular {formatear_valor(izquierda)} {simbolo} 0.",
                        instruccion.linea or None,
                        sugerencia="Verifica con un if que el divisor sea distinto de 0 "
                        "antes de dividir.",
                    ) from None
                self._escribir(args[0], resultado)
            case "JMP":
                return etiquetas[args[0].nombre]
            case "JZ":
                return etiquetas[args[1].nombre] if not self._leer(args[0]) else None
            case "JNZ":
                return etiquetas[args[1].nombre] if self._leer(args[0]) else None
            case "PRINT":
                self.salida.append(formatear_valor(self._leer(args[0])))
        return None  # HALT y las demás no saltan
