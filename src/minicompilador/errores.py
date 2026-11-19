"""Jerarquía de errores del compilador.

¿Por qué una jerarquía y no un solo ``Exception``?
    - Cada fase lanza su propio tipo de error, así el orquestador sabe *en qué
      fase* se detuvo la compilación sin tener que analizar el texto del mensaje.
    - Las pruebas pueden verificar el tipo exacto con ``pytest.raises(ErrorLexico)``
      (una prueba más precisa que capturar cualquier excepción).
    - Quien quiera atrapar "cualquier error de compilación" usa la clase base
      ``ErrorCompilador`` (principio de sustitución de Liskov).

    ErrorCompilador
    ├── ErrorLexico       (fase 1)
    ├── ErrorSintactico   (fase 2)
    ├── ErrorSemantico    (fase 3)
    └── ErrorEjecucion    (fase 6, simulador de CPU)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Orden oficial de las fases. Se usa en el reporte para indicar hasta dónde
#: llegó la compilación y en el CLI para ``--fase N``.
FASES: tuple[str, ...] = (
    "lexico",
    "sintactico",
    "semantico",
    "intermedio",
    "registros",
    "simulacion",
)

#: Nombre legible de cada fase (para mensajes en pantalla).
NOMBRES_FASES: dict[str, str] = {
    "lexico": "Léxico",
    "sintactico": "Sintáctico",
    "semantico": "Semántico",
    "intermedio": "Código intermedio",
    "registros": "Asignación de registros",
    "simulacion": "Simulación",
}


class ErrorCompilador(Exception):
    """Error base: toda falla del compilador sabe su fase, posición y solución.

    Args:
        mensaje: qué salió mal y *por qué* ocurrió.
        linea: línea (empezando en 1) donde se detectó; ``None`` si no aplica.
        columna: columna (empezando en 1) donde se detectó; ``None`` si no aplica.
        sugerencia: cómo corregirlo. Un buen mensaje de error enseña, no solo acusa.
    """

    #: Las subclases sobrescriben este atributo; es la "etiqueta" de la fase.
    fase: str = "compilador"

    def __init__(
        self,
        mensaje: str,
        linea: int | None = None,
        columna: int | None = None,
        sugerencia: str | None = None,
    ) -> None:
        self.mensaje = mensaje
        self.linea = linea
        self.columna = columna
        self.sugerencia = sugerencia
        # Pasamos el texto formateado a Exception para que str(error) sea útil
        # y para que pytest.raises(..., match=...) pueda buscar en él.
        super().__init__(self._formatear())

    @property
    def tipo(self) -> str:
        """Nombre de la clase concreta (``ErrorLexico``, ``ErrorSintactico``...)."""
        return type(self).__name__

    def _formatear(self) -> str:
        nombre_fase = NOMBRES_FASES.get(self.fase, self.fase)
        posicion = ""
        if self.linea is not None:
            posicion = f" línea {self.linea}"
            if self.columna is not None:
                posicion += f", columna {self.columna}"
        texto = f"[{nombre_fase}]{posicion}: {self.mensaje}"
        if self.sugerencia:
            texto += f" Sugerencia: {self.sugerencia}"
        return texto

    def a_dict(self) -> dict[str, Any]:
        """Representación serializable a JSON, usada en la sección ``errores`` del reporte."""
        return {
            "fase": self.fase,
            "tipo": self.tipo,
            "mensaje": self.mensaje,
            "linea": self.linea,
            "columna": self.columna,
            "sugerencia": self.sugerencia,
        }


class ErrorLexico(ErrorCompilador):
    """Carácter o palabra que no forma un token válido (ej. ``@``, ``%a``)."""

    fase = "lexico"


class ErrorSintactico(ErrorCompilador):
    """Los tokens son válidos pero su orden no respeta la gramática (ej. falta ``;``)."""

    fase = "sintactico"


class ErrorSemantico(ErrorCompilador):
    """La frase es gramatical pero no tiene sentido (ej. variable no declarada)."""

    fase = "semantico"


class ErrorEjecucion(ErrorCompilador):
    """Falla durante la simulación (ej. división por cero, bucle infinito)."""

    fase = "simulacion"


@dataclass(frozen=True)
class Advertencia:
    """Problema que NO detiene la compilación (buenas prácticas, posibles bugs).

    A diferencia de un error, una advertencia no es una excepción: se acumula
    en una lista y el compilador sigue. ``codigo`` es un identificador estable
    (ej. ``FLOAT_A_INT``) para que las pruebas y herramientas no dependan del
    texto del mensaje, que puede cambiar.
    """

    codigo: str
    mensaje: str
    linea: int | None = None
    columna: int | None = None
    sugerencia: str | None = None
    fase: str = "semantico"

    def a_dict(self) -> dict[str, Any]:
        return {
            "fase": self.fase,
            "codigo": self.codigo,
            "mensaje": self.mensaje,
            "linea": self.linea,
            "columna": self.columna,
            "sugerencia": self.sugerencia,
        }
