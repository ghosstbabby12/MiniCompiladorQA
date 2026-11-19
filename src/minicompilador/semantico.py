"""Fase 3 - Análisis semántico.

El parser garantiza que el programa tiene la FORMA correcta; esta fase revisa
que tenga SENTIDO. Ejemplo: ``x = y + 1;`` es gramatical, pero si ``y`` nunca
fue declarada, el programa no significa nada.

Qué hace:
    1. Construye la TABLA DE SÍMBOLOS: por cada variable guarda nombre, tipo,
       dirección de memoria, si está inicializada y dónde se declaró.
    2. INFIERE EL TIPO de cada expresión (int, float o bool) y verifica que las
       operaciones y asignaciones sean compatibles.
    3. Emite ADVERTENCIAS de posibles bugs y de buenas prácticas.

Errores (detienen la compilación):
    variable no declarada · redeclaración · palabra reservada como nombre ·
    bool en operación aritmética · comparar bool con número · asignar bool↔número

Advertencias (la compilación continúa), con su código estable:
    FLOAT_A_INT · NO_INICIALIZADA · NO_USADA · CONDICION_NO_BOOLEANA ·
    NOMBRE_BUILTIN · NOMBRE_CORTO · NO_SNAKE_CASE

Simplificaciones deliberadas (fáciles de explicar):
    * Mini tiene un ÚNICO ámbito global: una variable declarada dentro de un
      bloque existe en todo el programa.
    * La verificación de inicialización NO sigue el flujo de control: basta con
      que exista una asignación previa en el texto (aunque esté dentro de un if).
"""

from __future__ import annotations

import builtins
import re
from dataclasses import dataclass, field
from typing import Any

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
from minicompilador.errores import Advertencia, ErrorSemantico
from minicompilador.lexer import PALABRAS_RESERVADAS
from minicompilador.operaciones import OPERADORES_ARITMETICOS

#: Nombres que en Python son funciones/tipos integrados (``list``, ``dict``,
#: ``str``, ``len``...). Usarlos como variables "tapa" el builtin: es un mal
#: hábito que causa bugs al migrar el código. Se calculan desde el propio
#: intérprete en lugar de escribir una lista a mano que podría quedar incompleta.
NOMBRES_BUILTIN = frozenset(
    nombre for nombre in dir(builtins) if nombre.islower() and not nombre.startswith("_")
)

#: snake_case: minúsculas, dígitos y guion bajo (``contador_total``).
PATRON_SNAKE_CASE = re.compile(r"^[a-z_][a-z0-9_]*$")


def a_snake_case(nombre: str) -> str:
    """``miVariable`` → ``mi_variable``; ``TOTAL`` → ``total`` (para sugerencias)."""
    con_guiones = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", nombre)
    return con_guiones.lower()


# ---------------------------------------------------------------------------
# Tabla de símbolos
# ---------------------------------------------------------------------------


@dataclass
class Simbolo:
    """Una entrada de la tabla de símbolos."""

    nombre: str
    tipo: str
    direccion: int
    linea: int
    columna: int
    inicializada: bool = False
    usada: bool = False

    def a_dict(self) -> dict[str, Any]:
        return {
            "tipo": self.tipo,
            "direccion": self.direccion,
            "inicializada": self.inicializada,
            "usada": self.usada,
            "linea": self.linea,
            "columna": self.columna,
        }


class TablaSimbolos:
    """Diccionario nombre → ``Simbolo`` que además reparte direcciones de memoria.

    Cada variable ocupa una "palabra" de 4 bytes a partir de la dirección 1000:
    la 1.ª variable vive en 1000, la 2.ª en 1004, la n-ésima en 1000 + 4·(n-1).
    """

    DIRECCION_BASE = 1000
    TAMANO_PALABRA = 4

    def __init__(self) -> None:
        self._simbolos: dict[str, Simbolo] = {}

    def declarar(
        self, nombre: str, tipo: str, linea: int, columna: int, inicializada: bool
    ) -> Simbolo:
        direccion = self.DIRECCION_BASE + self.TAMANO_PALABRA * len(self._simbolos)
        simbolo = Simbolo(nombre, tipo, direccion, linea, columna, inicializada)
        self._simbolos[nombre] = simbolo
        return simbolo

    def buscar(self, nombre: str) -> Simbolo | None:
        return self._simbolos.get(nombre)

    def __contains__(self, nombre: object) -> bool:
        return nombre in self._simbolos

    def __len__(self) -> int:
        return len(self._simbolos)

    def __iter__(self):
        return iter(self._simbolos.values())

    def a_dict(self) -> dict[str, dict[str, Any]]:
        """Sección ``tabla_simbolos`` del reporte (en orden de declaración)."""
        return {nombre: simbolo.a_dict() for nombre, simbolo in self._simbolos.items()}


@dataclass
class ResultadoSemantico:
    tabla: TablaSimbolos
    advertencias: list[Advertencia] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Analizador (patrón Visitor)
# ---------------------------------------------------------------------------


class AnalizadorSemantico(Visitante):
    """Recorre el AST verificando tipos y declaraciones.

    Los métodos ``visitar_<expresion>`` DEVUELVEN el tipo inferido
    (``"int"``, ``"float"`` o ``"bool"``); los de sentencias no devuelven nada.
    """

    def __init__(self) -> None:
        self.tabla = TablaSimbolos()
        self.advertencias: list[Advertencia] = []
        self._contadores: set[str] = set()
        self._avisadas_sin_inicializar: set[str] = set()

    def analizar(self, programa: Programa) -> ResultadoSemantico:
        """Punto de entrada. Lanza ``ErrorSemantico`` en el primer error."""
        self.visitar(programa)
        return ResultadoSemantico(self.tabla, self.advertencias)

    def _advertir(self, codigo: str, mensaje: str, nodo: Nodo, sugerencia: str) -> None:
        self.advertencias.append(Advertencia(codigo, mensaje, nodo.linea, nodo.columna, sugerencia))

    # ------------------------------------------------------------ sentencias

    def visitar_programa(self, nodo: Programa) -> None:
        # Pre-pasada: las variables que aparecen en la condición de un while son
        # "contadores" y se les permite un nombre de una letra (i, n, a...).
        self._contadores = _variables_en_condiciones_de_while(nodo)
        for sentencia in nodo.sentencias:
            self.visitar(sentencia)
        for simbolo in self.tabla:
            if not simbolo.usada:
                self.advertencias.append(
                    Advertencia(
                        "NO_USADA",
                        f"La variable '{simbolo.nombre}' se declara pero su valor nunca se lee.",
                        simbolo.linea,
                        simbolo.columna,
                        "Elimínala o úsala; las variables muertas confunden al lector.",
                    )
                )

    def visitar_declaracion(self, nodo: Declaracion) -> None:
        if nodo.nombre in PALABRAS_RESERVADAS:
            raise ErrorSemantico(
                f"'{nodo.nombre}' es una palabra reservada de Mini y no puede usarse como "
                "nombre de variable.",
                nodo.linea,
                nodo.columna,
                sugerencia=f"Usa otro nombre, por ejemplo 'mi_{nodo.nombre}'.",
            )
        previo = self.tabla.buscar(nodo.nombre)
        if previo is not None:
            raise ErrorSemantico(
                f"La variable '{nodo.nombre}' ya fue declarada en la línea {previo.linea}.",
                nodo.linea,
                nodo.columna,
                sugerencia=f"Para cambiar su valor escribe '{nodo.nombre} = ...;' sin el tipo.",
            )
        # El valor se analiza ANTES de declarar: así 'int a = a + 1;' es un error
        # (la 'a' de la derecha todavía no existe), como en C.
        if nodo.valor is not None:
            tipo_valor = self.visitar(nodo.valor)
            self._verificar_asignable(nodo.tipo, tipo_valor, nodo.nombre, nodo)
        self.tabla.declarar(
            nodo.nombre, nodo.tipo, nodo.linea, nodo.columna, inicializada=nodo.valor is not None
        )
        self._revisar_nombre(nodo)

    def visitar_asignacion(self, nodo: Asignacion) -> None:
        simbolo = self._buscar_o_fallar(nodo.nombre, nodo)
        tipo_valor = self.visitar(nodo.valor)
        self._verificar_asignable(simbolo.tipo, tipo_valor, nodo.nombre, nodo)
        simbolo.inicializada = True

    def visitar_if(self, nodo: If) -> None:
        self._verificar_condicion(nodo.condicion, "if")
        for sentencia in nodo.entonces:
            self.visitar(sentencia)
        for sentencia in nodo.sino or []:
            self.visitar(sentencia)

    def visitar_while(self, nodo: While) -> None:
        self._verificar_condicion(nodo.condicion, "while")
        for sentencia in nodo.cuerpo:
            self.visitar(sentencia)

    def visitar_print(self, nodo: Print) -> None:
        self.visitar(nodo.expresion)

    # ----------------------------------------------------------- expresiones

    def visitar_numero(self, nodo: Numero) -> str:
        return nodo.tipo

    def visitar_variable(self, nodo: Variable) -> str:
        simbolo = self._buscar_o_fallar(nodo.nombre, nodo)
        simbolo.usada = True
        if not simbolo.inicializada and nodo.nombre not in self._avisadas_sin_inicializar:
            self._avisadas_sin_inicializar.add(nodo.nombre)  # avisar solo una vez
            self._advertir(
                "NO_INICIALIZADA",
                f"La variable '{nodo.nombre}' se usa antes de recibir un valor "
                "(en la simulación valdrá 0).",
                nodo,
                f"Inicialízala al declararla: {simbolo.tipo} {nodo.nombre} = 0;",
            )
        return simbolo.tipo

    def visitar_binop(self, nodo: BinOp) -> str:
        tipo_izq = self.visitar(nodo.izquierda)
        tipo_der = self.visitar(nodo.derecha)
        hay_bool = "bool" in (tipo_izq, tipo_der)

        if nodo.op in OPERADORES_ARITMETICOS:
            if hay_bool:
                raise ErrorSemantico(
                    f"El operador '{nodo.op}' no acepta valores bool "
                    f"(se recibió {tipo_izq} {nodo.op} {tipo_der}).",
                    nodo.linea,
                    nodo.columna,
                    sugerencia="Las operaciones aritméticas solo admiten int y float.",
                )
            # Promoción numérica: si algún operando es float, el resultado es float.
            return "float" if "float" in (tipo_izq, tipo_der) else "int"

        if nodo.op in ("==", "!="):
            if (tipo_izq == "bool") != (tipo_der == "bool"):
                raise ErrorSemantico(
                    f"No se puede comparar {tipo_izq} con {tipo_der} usando '{nodo.op}'.",
                    nodo.linea,
                    nodo.columna,
                    sugerencia="Compara bool con bool, o números con números.",
                )
            return "bool"

        # <, >, <=, >= : solo tienen sentido entre números.
        if hay_bool:
            raise ErrorSemantico(
                f"El operador '{nodo.op}' no tiene sentido con valores bool.",
                nodo.linea,
                nodo.columna,
                sugerencia="Usa '==' o '!=' para comparar valores bool.",
            )
        return "bool"

    # ------------------------------------------------------------- auxiliares

    def _buscar_o_fallar(self, nombre: str, nodo: Nodo) -> Simbolo:
        simbolo = self.tabla.buscar(nombre)
        if simbolo is None:
            raise ErrorSemantico(
                f"La variable '{nombre}' no ha sido declarada.",
                nodo.linea,
                nodo.columna,
                sugerencia=f"Declárala antes de usarla, por ejemplo: int {nombre} = 0;",
            )
        return simbolo

    def _verificar_asignable(self, destino: str, origen: str, nombre: str, nodo: Nodo) -> None:
        """Reglas de compatibilidad ``destino ← origen``.

        ============  =========  =========  ==========
        destino\\orig  int        float      bool
        ============  =========  =========  ==========
        int           ok         ADVIERTE   ERROR
        float         ok (prom.) ok         ERROR
        bool          ERROR      ERROR      ok
        ============  =========  =========  ==========
        """
        if destino == origen or (destino == "float" and origen == "int"):
            return
        if destino == "int" and origen == "float":
            self._advertir(
                "FLOAT_A_INT",
                f"Se asigna un valor float a '{nombre}' (int): se perderán los decimales "
                "(el valor se trunca).",
                nodo,
                f"Declara '{nombre}' como float si necesitas los decimales.",
            )
            return
        raise ErrorSemantico(
            f"No se puede asignar un valor {origen} a la variable '{nombre}' de tipo {destino}.",
            nodo.linea,
            nodo.columna,
            sugerencia="Mini no convierte automáticamente entre bool y números.",
        )

    def _verificar_condicion(self, condicion: Nodo, palabra: str) -> None:
        if self.visitar(condicion) != "bool":
            self._advertir(
                "CONDICION_NO_BOOLEANA",
                f"La condición del '{palabra}' es numérica: se considera verdadera si es "
                "distinta de 0.",
                condicion,
                "Escribe la comparación explícita, por ejemplo (x != 0).",
            )

    def _revisar_nombre(self, nodo: Declaracion) -> None:
        """Advertencias de estilo sobre el nombre recién declarado."""
        nombre = nodo.nombre
        if nombre in NOMBRES_BUILTIN:
            self._advertir(
                "NOMBRE_BUILTIN",
                f"'{nombre}' es el nombre de una función integrada de Python; usarlo como "
                "variable la oculta y confunde al lector.",
                nodo,
                f"Usa un nombre más específico, por ejemplo '{nombre}_valores'.",
            )
        # Valor límite: 1 carácter advierte (on point), 2 caracteres ya no (off point).
        if len(nombre) == 1 and nombre not in self._contadores:
            self._advertir(
                "NOMBRE_CORTO",
                f"El nombre '{nombre}' tiene una sola letra y no es un contador de bucle.",
                nodo,
                "Usa un nombre que describa el dato, por ejemplo 'total' o 'promedio'.",
            )
        if not PATRON_SNAKE_CASE.match(nombre):
            self._advertir(
                "NO_SNAKE_CASE",
                f"El nombre '{nombre}' no sigue la convención snake_case.",
                nodo,
                f"Renómbralo como '{a_snake_case(nombre)}'.",
            )


def _variables_en_condiciones_de_while(nodo: Nodo) -> set[str]:
    """Recorre todo el árbol y junta las variables usadas en condiciones de while."""
    encontradas: set[str] = set()
    if isinstance(nodo, While):
        encontradas |= _variables_en_expresion(nodo.condicion)
    for _, hijo in nodo.hijos():
        for subnodo in hijo if isinstance(hijo, list) else [hijo]:
            encontradas |= _variables_en_condiciones_de_while(subnodo)
    return encontradas


def _variables_en_expresion(nodo: Nodo) -> set[str]:
    if isinstance(nodo, Variable):
        return {nodo.nombre}
    if isinstance(nodo, BinOp):
        return _variables_en_expresion(nodo.izquierda) | _variables_en_expresion(nodo.derecha)
    return set()


def analizar(programa: Programa) -> ResultadoSemantico:
    """Atajo funcional para la fase semántica."""
    return AnalizadorSemantico().analizar(programa)
