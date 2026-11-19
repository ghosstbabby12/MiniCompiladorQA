"""Modo explicación: traduce el resultado de la compilación a lenguaje sencillo.

Pensado para la sustentación: responde, en orden, las preguntas típicas
(¿hasta qué fase llegó?, ¿qué hace cada línea y en qué orden?, ¿qué algoritmo
recorrió el árbol?, ¿cuántas temporales y registros?, ¿qué instrucciones de
procesador y memoria generó?, ¿por qué falló?).
"""

from __future__ import annotations

from collections import defaultdict

from minicompilador.ast_nodos import imprimir_arbol
from minicompilador.cpu import ETIQUETA, OPERADOR_DE, InstruccionCPU, Memoria
from minicompilador.errores import FASES, NOMBRES_FASES, ErrorCompilador
from minicompilador.intermedio import (
    Copia,
    Etiqueta,
    Imprimir,
    Instruccion,
    OperacionBinaria,
    Salto,
    SaltoSiFalso,
)
from minicompilador.lexer import TipoToken
from minicompilador.registros import NUM_REGISTROS
from minicompilador.reporte import Compilacion

NOMBRE_OPERACION = {
    "+": "suma",
    "-": "resta",
    "*": "multiplicación",
    "/": "división",
    "%": "módulo (resto de la división)",
    "<": "comparación 'menor que'",
    ">": "comparación 'mayor que'",
    "<=": "comparación 'menor o igual'",
    ">=": "comparación 'mayor o igual'",
    "==": "comparación 'igual a'",
    "!=": "comparación 'distinto de'",
}

POR_QUE_FALLA = {
    "lexico": "El analizador léxico lee el texto carácter por carácter para formar "
    "'palabras' (tokens). Encontró algo que no corresponde a ninguna palabra de Mini.",
    "sintactico": "Todas las palabras son válidas, pero su ORDEN no respeta la gramática "
    "de Mini (como una frase con las palabras correctas mal ordenadas).",
    "semantico": "La frase es gramaticalmente correcta pero no tiene SENTIDO: por ejemplo "
    "usa una variable que no existe o mezcla tipos incompatibles.",
    "simulacion": "El programa compiló sin problemas, pero falló al EJECUTARSE en la CPU "
    "simulada: el problema depende de los valores en tiempo de ejecución.",
}


def _titulo(numero: int, texto: str) -> list[str]:
    return ["", f"{numero}. {texto}", "─" * (len(texto) + 3)]


def explicar(compilacion: Compilacion) -> str:
    c = compilacion
    lineas: list[str] = ["═" * 60, "  MiniCompilador QA · modo explicación", "═" * 60]
    lineas += _seccion_fases(c)
    numero = 2
    if c.tokens is not None:
        lineas += _seccion_lexico(c, numero)
        numero += 1
    if c.programa is not None:
        lineas += _titulo(numero, "Árbol de sintaxis abstracta (AST)")
        lineas += ["   " + linea for linea in imprimir_arbol(c.programa).splitlines()]
        numero += 1
    if c.semantico is not None:
        lineas += _seccion_tabla(c, numero)
        numero += 1
    if c.intermedio is not None:
        lineas += _seccion_lineas(c, numero)
        lineas += _seccion_recorrido(c, numero + 1)
        lineas += _seccion_temporales(c, numero + 2)
        numero += 3
    if c.registros is not None:
        lineas += _seccion_registros(c, numero)
        lineas += _seccion_cpu(c, numero + 1)
        numero += 2
    if c.cpu is not None:
        lineas += _seccion_ejecucion(c, numero)
        numero += 1
    if c.advertencias:
        lineas += _titulo(numero, f"Advertencias ({len(c.advertencias)})")
        for adv in c.advertencias:
            lineas.append(f"   ⚠ [{adv.codigo}] línea {adv.linea}: {adv.mensaje}")
            lineas.append(f"     → {adv.sugerencia}")
        numero += 1
    if c.error is not None:
        lineas += _seccion_error(c.codigo, c.error, numero)
    return "\n".join(lineas) + "\n"


# ---------------------------------------------------------------------------


def _seccion_fases(c: Compilacion) -> list[str]:
    lineas = _titulo(1, "¿Hasta qué fase llegó la compilación?")
    for indice, fase in enumerate(FASES, start=1):
        if fase in c.fases_completadas:
            estado = "✔ completada"
        elif c.error is not None and c.error.fase == fase:
            estado = "✘ ERROR (aquí se detuvo)"
        elif indice > c.hasta_fase:
            estado = "– omitida (--fase)"
        else:
            estado = "– no se ejecutó"
        lineas.append(f"   {indice}. {NOMBRES_FASES[fase]:<24} {estado}")
    resultado = "ÉXITO" if c.exito else f"FALLÓ en la fase {NOMBRES_FASES[c.fase_alcanzada]}"
    lineas.append(f"   Resultado: {resultado}.")
    return lineas


def _seccion_lexico(c: Compilacion, numero: int) -> list[str]:
    tokens = [t for t in c.tokens if t.tipo is not TipoToken.EOF]
    conteo: dict[str, int] = defaultdict(int)
    for token in tokens:
        conteo[token.tipo.value] += 1
    resumen = ", ".join(f"{tipo}×{n}" for tipo, n in sorted(conteo.items()))
    return _titulo(numero, "Análisis léxico") + [
        f"   Se reconocieron {len(tokens)} tokens (más el marcador EOF).",
        f"   Por tipo: {resumen or 'ninguno'}.",
    ]


def _seccion_tabla(c: Compilacion, numero: int) -> list[str]:
    lineas = _titulo(numero, "Tabla de símbolos")
    if not len(c.semantico.tabla):
        return lineas + ["   (no se declararon variables)"]
    lineas.append(f"   {'Nombre':<14}{'Tipo':<8}{'Dirección':<11}Inicializada")
    for s in c.semantico.tabla:
        inicial = "sí" if s.inicializada else "no"
        lineas.append(f"   {s.nombre:<14}{s.tipo:<8}{s.direccion:<11}{inicial}")
    return lineas


def _describir_tac(instruccion: Instruccion) -> str:
    match instruccion:
        case OperacionBinaria(op=op):
            return NOMBRE_OPERACION[op]
        case Copia(destino=destino):
            return f"se guarda el valor en la variable '{destino}'"
        case SaltoSiFalso(etiqueta=etiqueta):
            return f"si la condición es falsa, salta a {etiqueta}"
        case Salto(etiqueta=etiqueta):
            return f"salta a {etiqueta}"
        case Etiqueta():
            return "marca un destino de salto"
        case Imprimir():
            return "muestra el valor en pantalla"
    return ""  # pragma: no cover - todas las instrucciones TAC están cubiertas


def _seccion_lineas(c: Compilacion, numero: int) -> list[str]:
    lineas = _titulo(numero, "¿Qué operación hace cada línea y en qué orden?")
    lineas += [
        "   Precedencia en Mini: primero * / %, luego + -, al final < > <= >= == !=.",
        "   Los paréntesis fuerzan el orden. Lo más profundo del árbol se calcula primero.",
    ]
    fuente = c.codigo.splitlines()
    por_linea: dict[int, list[Instruccion]] = defaultdict(list)
    for instruccion in c.intermedio.instrucciones:
        por_linea[instruccion.linea].append(instruccion)
    for numero_linea in sorted(por_linea):
        lineas.append("")
        lineas.append(f"   Línea {numero_linea}: {fuente[numero_linea - 1].strip()}")
        for paso, instruccion in enumerate(por_linea[numero_linea], start=1):
            lineas.append(f"     {paso}) {str(instruccion):<24} ← {_describir_tac(instruccion)}")
    if not por_linea:
        lineas.append("   (el programa no genera operaciones)")
    return lineas


def _seccion_recorrido(c: Compilacion, numero: int) -> list[str]:
    recorrido = c.intermedio.recorrido
    muestra = " → ".join(recorrido[:12]) + (" → ..." if len(recorrido) > 12 else "")
    return _titulo(numero, "¿Qué algoritmo recorrió el árbol?") + [
        "   DFS (búsqueda en profundidad) en POSTORDEN, con el patrón Visitor:",
        "   primero se visitan los hijos (izquierdo y derecho) y al final el nodo.",
        "   Así, al generar una operación, sus operandos ya están calculados.",
        f"   Nodos visitados: {len(recorrido)}. Orden: {muestra}",
    ]


def _seccion_temporales(c: Compilacion, numero: int) -> list[str]:
    inter = c.intermedio
    lineas = _titulo(numero, f"Variables temporales: {inter.total_temporales}")
    lineas.append(
        "   Las crea nueva_temporal() con el prefijo %t, que el usuario no puede escribir"
    )
    lineas.append("   (el lexer rechaza '%a'): por eso nunca chocan con variables del programa.")
    for temporal, definicion in inter.definiciones_temporales.items():
        lineas.append(f"   {temporal:<5} se define como  {definicion}")
    if inter.optimizaciones:
        lineas.append("   Plegado de constantes (calculado al compilar, sin instrucción):")
        lineas += [f"     • {texto}" for texto in inter.optimizaciones]
    return lineas


def _seccion_registros(c: Compilacion, numero: int) -> list[str]:
    regs = c.registros
    lineas = _titulo(numero, "Asignación de registros (linear scan)")
    lineas += [
        f"   La CPU tiene {NUM_REGISTROS} registros (R0-R3).",
        f"   Máximo de registros usados al mismo tiempo: {regs.max_registros_simultaneos}.",
        f"   Máximo de temporales vivas al mismo tiempo: {regs.max_temporales_vivas}.",
        f"   Spills (temporales enviadas a memoria): {regs.spills}.",
    ]
    for intervalo in regs.intervalos:
        ubicacion = regs.asignacion[intervalo.temporal]
        lineas.append(
            f"   {intervalo.temporal:<5} → {ubicacion:<10} vive de la instrucción "
            f"{intervalo.inicio} a la {intervalo.fin}"
        )
    return lineas


def _describir_cpu(i: InstruccionCPU) -> str:
    ops = [str(o) for o in i.operandos]
    match i.opcode:
        case "LOAD":
            return f"lee {ops[1]} de memoria y lo pone en {ops[0]}"
        case "STORE":
            return f"escribe {ops[1]} en memoria, en {ops[0]}"
        case "MOV":
            return f"copia {ops[1]} en {ops[0]}"
        case "ADD" | "SUB" | "MUL" | "DIV" | "MOD":
            simbolo = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "MOD": "%"}[i.opcode]
            return f"{ops[0]} ← {ops[1]} {simbolo} {ops[2]}"
        case "CMP":
            simbolo = OPERADOR_DE[i.condicion]
            return f"{ops[0]} ← 1 si {ops[1]} {simbolo} {ops[2]} ({i.condicion}), si no 0"
        case "JZ":
            return f"si {ops[0]} es 0 (falso) salta a {ops[1]}"
        case "JNZ":
            return f"si {ops[0]} no es 0 salta a {ops[1]}"
        case "JMP":
            return f"salta a {ops[0]}"
        case "PRINT":
            return f"imprime {ops[0]}"
        case "HALT":
            return "detiene la CPU"
    return ""  # pragma: no cover


def _seccion_cpu(c: Compilacion, numero: int) -> list[str]:
    codigo = c.codigo_cpu
    reales = [i for i in codigo if i.opcode != ETIQUETA]
    de_memoria = [i for i in reales if any(isinstance(o, Memoria) for o in i.operandos)]
    lineas = _titulo(numero, "Instrucciones de procesador y memoria generadas")
    lineas.append(
        f"   {len(reales)} instrucciones; {len(de_memoria)} acceden a memoria "
        "([x] = memoria, Rn = registro, #n = constante)."
    )
    for instruccion in codigo:
        if instruccion.opcode == ETIQUETA:
            lineas.append(f"   {instruccion}")
        else:
            lineas.append(f"     {str(instruccion):<26} ; {_describir_cpu(instruccion)}")
    return lineas


def _seccion_ejecucion(c: Compilacion, numero: int) -> list[str]:
    cpu = c.cpu
    salida = ", ".join(cpu.salida) if cpu.salida else "(nada)"
    memoria = ", ".join(f"{n}={v}" for n, v in cpu.memoria_final.items()) or "(vacía)"
    return _titulo(numero, "Ejecución en la CPU simulada") + [
        f"   Salida del programa: {salida}",
        f"   Memoria final: {memoria}",
        f"   Instrucciones ejecutadas: {cpu.instrucciones_ejecutadas}",
        f"   Lecturas de memoria: {cpu.lecturas_memoria} · Escrituras: {cpu.escrituras_memoria}",
        f"   Ciclos: {cpu.ciclos} (1 por instrucción + 2 por cada acceso a memoria)",
    ]


def _seccion_error(codigo: str, error: ErrorCompilador, numero: int) -> list[str]:
    lineas = _titulo(numero, "Análisis del error")
    posicion = f"línea {error.linea}" if error.linea else "sin posición"
    if error.columna:
        posicion += f", columna {error.columna}"
    lineas += [
        f"   Fase: {NOMBRES_FASES[error.fase]} · Tipo: {error.tipo} · {posicion}",
    ]
    fuente = codigo.splitlines()
    if error.linea and error.linea <= len(fuente):
        texto = fuente[error.linea - 1]
        lineas.append(f"   {error.linea:>4} | {texto}")
        if error.columna:
            # La columna es 1-based: el '^' va debajo del carácter número 'columna'.
            lineas.append(f"        | {' ' * (error.columna - 1)}^")
    lineas += [
        f"   Qué pasó: {error.mensaje}",
        f"   Por qué:  {POR_QUE_FALLA[error.fase]}",
        f"   Cómo corregirlo: {error.sugerencia or 'revisa la especificación de Mini.'}",
    ]
    return lineas
