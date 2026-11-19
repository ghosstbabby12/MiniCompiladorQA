"""MiniCompilador QA: compilador didáctico del lenguaje Mini.

El compilador recorre 6 fases en orden (ver ``errores.FASES``):
léxico → sintáctico → semántico → intermedio → registros → simulación.
Cada fase vive en su propio módulo para poder probarla y explicarla por separado.
"""

__version__ = "0.1.0"
