"""Nodos del Árbol de Sintaxis Abstracta (AST).

¿Por qué "abstracta"? Porque el árbol guarda solo lo que importa para el
significado del programa: no hay nodos para ``;``, ``(`` ni ``{``. La agrupación
que expresaban los paréntesis queda implícita en la FORMA del árbol.

Ejemplo: ``c = a + b * 2;`` produce::

    Asignacion c =
    └── BinOp '+'
        ├── Variable a
        └── BinOp '*'          <- más profundo = se evalúa antes (precedencia)
            ├── Variable b
            └── Numero 2 (int)

Decisiones de diseño:
    * ``@dataclass``: el constructor, ``__repr__`` y ``__eq__`` se generan solos.
    * ``linea``/``columna`` con ``compare=False``: dos árboles son iguales si
      tienen la misma estructura, sin importar dónde estaba escrito el código.
      Así las pruebas comparan árboles sin escribir posiciones.
    * Patrón Visitor (``aceptar``): las fases posteriores (semántico, código
      intermedio) recorren el árbol SIN modificar estas clases (principio
      abierto/cerrado).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

#: Un hijo de un nodo: (rótulo opcional, nodo o lista de nodos).
Hijo = tuple[str | None, "Nodo | list[Nodo]"]


@dataclass
class Nodo:
    """Clase base de todos los nodos. Aporta posición y despacho del Visitor."""

    linea: int = field(default=0, kw_only=True, compare=False)
    columna: int = field(default=0, kw_only=True, compare=False)

    def aceptar(self, visitante: Visitante) -> Any:
        """Doble despacho: ``BinOp.aceptar(v)`` llama a ``v.visitar_binop(self)``.

        El nombre del método se arma con el nombre de la clase en minúsculas,
        así cada nodo encuentra "su" método en el visitante sin usar ``if``/``isinstance``.
        """
        nombre_metodo = f"visitar_{type(self).__name__.lower()}"
        metodo = getattr(visitante, nombre_metodo, visitante.visitar_generico)
        return metodo(self)

    def etiqueta(self) -> str:
        """Texto corto que describe el nodo al imprimir el árbol."""
        return type(self).__name__

    def hijos(self) -> list[Hijo]:
        """Subárboles del nodo, en el orden en que se deben recorrer."""
        return []


class Visitante:
    """Base para recorrer el AST. Las subclases definen ``visitar_<nodo>``."""

    def visitar(self, nodo: Nodo) -> Any:
        return nodo.aceptar(self)

    def visitar_generico(self, nodo: Nodo) -> Any:
        """Se ejecuta si falta el método específico: fallar fuerte ayuda a detectar olvidos."""
        raise NotImplementedError(
            f"{type(self).__name__} no sabe visitar nodos '{type(nodo).__name__}'."
        )


# ----------------------------------------------------------------- expresiones


@dataclass
class Numero(Nodo):
    """Literal: ``5`` (int), ``2.5`` (float) o ``true``/``false`` (bool)."""

    valor: int | float | bool

    @property
    def tipo(self) -> str:
        # Ojo: bool se pregunta ANTES que int porque en Python True es un int.
        if isinstance(self.valor, bool):
            return "bool"
        return "float" if isinstance(self.valor, float) else "int"

    def etiqueta(self) -> str:
        texto = str(self.valor).lower() if self.tipo == "bool" else str(self.valor)
        return f"Numero {texto} ({self.tipo})"


@dataclass
class Variable(Nodo):
    """Uso de una variable dentro de una expresión: ``a``."""

    nombre: str

    def etiqueta(self) -> str:
        return f"Variable {self.nombre}"


@dataclass
class BinOp(Nodo):
    """Operación binaria: ``izquierda op derecha``."""

    izquierda: Nodo
    op: str
    derecha: Nodo

    def etiqueta(self) -> str:
        return f"BinOp '{self.op}'"

    def hijos(self) -> list[Hijo]:
        return [(None, self.izquierda), (None, self.derecha)]


# ------------------------------------------------------------------ sentencias


@dataclass
class Declaracion(Nodo):
    """``int a;`` o ``int a = 5;`` (``valor`` es ``None`` si no se inicializa)."""

    tipo: str
    nombre: str
    valor: Nodo | None = None

    def etiqueta(self) -> str:
        return f"Declaracion {self.tipo} {self.nombre}"

    def hijos(self) -> list[Hijo]:
        return [("valor", self.valor)] if self.valor is not None else []


@dataclass
class Asignacion(Nodo):
    """``a = expresion;``"""

    nombre: str
    valor: Nodo

    def etiqueta(self) -> str:
        return f"Asignacion {self.nombre} ="

    def hijos(self) -> list[Hijo]:
        return [(None, self.valor)]


@dataclass
class If(Nodo):
    """``if (condicion) { entonces } else { sino }``; ``sino`` es ``None`` sin else."""

    condicion: Nodo
    entonces: list[Nodo]
    sino: list[Nodo] | None = None

    def hijos(self) -> list[Hijo]:
        hijos: list[Hijo] = [("condicion", self.condicion), ("entonces", self.entonces)]
        if self.sino is not None:
            hijos.append(("sino", self.sino))
        return hijos


@dataclass
class While(Nodo):
    """``while (condicion) { cuerpo }``"""

    condicion: Nodo
    cuerpo: list[Nodo]

    def hijos(self) -> list[Hijo]:
        return [("condicion", self.condicion), ("cuerpo", self.cuerpo)]


@dataclass
class Print(Nodo):
    """``print(expresion);``"""

    expresion: Nodo

    def hijos(self) -> list[Hijo]:
        return [(None, self.expresion)]


@dataclass
class Programa(Nodo):
    """Raíz del árbol: la lista de sentencias del archivo."""

    sentencias: list[Nodo]

    def hijos(self) -> list[Hijo]:
        return [(None, sentencia) for sentencia in self.sentencias]


# ----------------------------------------------------------- utilidades del AST


def imprimir_arbol(nodo: Nodo) -> str:
    """Devuelve el árbol como texto con sangría y ramas (estilo comando ``tree``).

    Recorrido en PREORDEN (primero el padre, luego los hijos de izquierda a
    derecha): es el orden natural para leer un árbol de arriba hacia abajo.
    """
    lineas = [nodo.etiqueta()]
    _imprimir_hijos(nodo.hijos(), prefijo="", lineas=lineas)
    return "\n".join(lineas)


def _imprimir_hijos(hijos: list[Hijo], prefijo: str, lineas: list[str]) -> None:
    for indice, (rotulo, contenido) in enumerate(hijos):
        es_ultimo = indice == len(hijos) - 1
        rama = "└── " if es_ultimo else "├── "
        # El prefijo de los nietos continúa la línea vertical solo si quedan hermanos.
        prefijo_hijos = prefijo + ("    " if es_ultimo else "│   ")

        if isinstance(contenido, list):  # un bloque: entonces / sino / cuerpo
            vacio = " (vacío)" if not contenido else ""
            lineas.append(f"{prefijo}{rama}{rotulo}{vacio}")
            _imprimir_hijos([(None, n) for n in contenido], prefijo_hijos, lineas)
        else:
            encabezado = f"{rotulo}: " if rotulo else ""
            lineas.append(f"{prefijo}{rama}{encabezado}{contenido.etiqueta()}")
            _imprimir_hijos(contenido.hijos(), prefijo_hijos, lineas)


def nodo_a_dict(nodo: Nodo) -> dict[str, Any]:
    """Convierte el AST en diccionarios anidados (sección ``ast`` del reporte JSON)."""
    resultado: dict[str, Any] = {"nodo": type(nodo).__name__}
    for campo in fields(nodo):
        resultado[campo.name] = _valor_a_json(getattr(nodo, campo.name))
    return resultado


def _valor_a_json(valor: Any) -> Any:
    if isinstance(valor, Nodo):
        return nodo_a_dict(valor)
    if isinstance(valor, list):
        return [_valor_a_json(elemento) for elemento in valor]
    return valor
