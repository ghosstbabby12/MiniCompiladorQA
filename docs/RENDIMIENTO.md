# Rendimiento y cuello de botella

Mediciones del 19-11-2026 en un MacBook Air (10 núcleos) con la API en Docker
(1 proceso uvicorn), guardando cada reporte en S3 (LocalStack). Son cifras de
**una máquina de desarrollo**: sirven para comparar, no como garantía de producción.

## 1. Prueba de carga (Locust)

```bash
docker compose -f docker-compose.yml -f docker-compose.s3.yml up -d --build --wait api
locust -f tests/carga/locustfile.py --host http://localhost:8000 \
       --headless -u 20 -r 5 -t 30s --csv resultados/carga
```

Tareas con peso: 6 programas cortos : 3 largos : 1 con error (de cada 10 solicitudes).

| Escenario            | Solicitudes | Fallos | RPS  | p50    | p95    | máx.   |
|----------------------|------------:|-------:|-----:|-------:|-------:|-------:|
| corto (6)            | 1047        | 0      | 36,0 | 7 ms   | 40 ms  | 90 ms  |
| largo (3)            | 507         | 0      | 17,4 | 24 ms  | 63 ms  | 95 ms  |
| con error, 422 (1)   | 159         | 0      | 5,5  | 6 ms   | 37 ms  | 75 ms  |
| **Total (20 usuarios)** | **1713** | **0**  | **58,9** | **13 ms** | **51 ms** | 95 ms |
| Estrés (100 usuarios) | 5453       | 0      | 187,5 | 200 ms | 360 ms | 600 ms |

**Quality gate de rendimiento** (en `locustfile.py`): exit 1 si los fallos
superan el 1 % o el p95 los 500 ms. Con 20 usuarios: ✔.

**Lectura:** con 20 usuarios el RPS lo limita el tiempo de "pensar" de los
usuarios (0,1–0,5 s), no el servidor. Con 100 usuarios el servidor se
**satura**: el RPS sube solo 3× y la mediana pasa de 13 ms a 200 ms. Las
solicitudes esperan en cola.

## 2. ¿Dónde se va el tiempo? (`tests/carga/perfil_cuello_botella.py`)

Programa largo de la prueba de carga (4595 caracteres, 377 instrucciones TAC,
243 temporales). Mediana de 30 repeticiones:

| Fase                     | Antes   | Después |
|--------------------------|--------:|--------:|
| Léxico                   | 1,90 ms | 1,98 ms |
| Sintáctico               | 0,49 ms | 0,40 ms |
| Semántico                | 0,28 ms | 0,36 ms |
| Código intermedio        | 0,61 ms | 0,55 ms |
| **Asignación de registros** | **2,74 ms** | **0,82 ms** |
| Simulación               | 0,89 ms | 0,76 ms |
| **Total**                | **6,93 ms** | **4,87 ms** |

**Hallazgo:** la fase más cara NO era el parser sino `registros._max_vivas`,
que comparaba cada intervalo con todos los demás (O(n²): ~59 000 comparaciones
con 243 temporales). Se reemplazó por un **barrido** O(n log n). La versión
O(n²) quedó en las pruebas como **oráculo**: 25 casos aleatorios con semilla
fija verifican que ambas dan el mismo resultado.

Además, el reporte del programa largo pesa **220 KB** (tokens 90 KB + AST
71 KB). Serializarlo cuesta ~1 ms, pero es lo que viaja por la red y se guarda
en S3.

## 3. El cuello de botella del parser: profundidad de recursión

El parser es de descenso recursivo: cada nivel de paréntesis llama a
`expresion → comparacion → suma → termino → factor` (~5 marcos de pila de
Python). Python corta a los **1000 marcos**.

| Paréntesis anidados | Marcos de pila | Tiempo   |
|--------------------:|---------------:|---------:|
| 1                   | 18             | 0,02 ms  |
| 50                  | 263            | 0,14 ms  |
| 98                  | 503            | 0,25 ms  |
| 101                 | → `ErrorSintactico` "Anidamiento demasiado profundo" | |
| 200 *(sin límite)*  | → `RecursionError` (en la API sería **HTTP 500**) | |

El tiempo crece lineal y es despreciable: la recursión no es un problema de
**velocidad** sino de **robustez**. Sin `PROFUNDIDAD_MAXIMA = 100`, una sola
solicitud de 200 paréntesis tumbaría la petición con un error interno. Con el
límite hay un margen de 2× y el usuario recibe un 422 con un mensaje que explica
el problema.

## 4. Conclusiones y siguientes pasos

1. **Capacidad:** un proceso satura en ~190 RPS por el GIL de Python (un núcleo
   para el trabajo de CPU). Mitigación sin tocar código: varios procesos con
   `uvicorn --workers N` (o la variable `WEB_CONCURRENCY`), o más réplicas.
2. **Robustez:** el límite de anidamiento convierte un posible 500 en un 422.
   Si se quisiera aceptar más anidamiento, habría que cambiar el parser por uno
   iterativo (precedence climbing con pila explícita), no subir el límite de Python.
3. **Tamaño del reporte:** la mejora más rentable sería permitir pedir un
   reporte "ligero" (sin tokens ni AST), lo que reduce ~73 % los bytes
   transferidos y almacenados.
