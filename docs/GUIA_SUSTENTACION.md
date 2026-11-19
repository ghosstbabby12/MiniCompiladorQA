# Guía de sustentación

Cada pregunta tiene una **respuesta corta para decir en voz alta** y un comando
**En vivo** que la demuestra. Todos los comandos se probaron en este repositorio
y suponen que el entorno virtual está activado:

```bash
cd MiniCompiladorQA && source .venv/bin/activate
```

> **Truco para la demostración:** `python -m minicompilador <(echo 'código')`
> compila un programa escrito en el momento, sin crear ningún archivo.

---

## 0. Antes de entrar (5 minutos)

```bash
pytest -q | tail -3                    # 516 passed, cobertura 100 %
docker compose -f docker-compose.yml -f docker-compose.s3.yml up -d --build --wait api
curl -s localhost:8000/salud           # {"estado":"ok",...}
open htmlcov/index.html                # reporte de cobertura listo en el navegador
open http://localhost:8000/docs        # Swagger listo
```

Al terminar: `docker compose -f docker-compose.yml -f docker-compose.s3.yml down -v`.

## 1. Guion de demostración (≈10 minutos)

| Min. | Qué mostrar | Comando |
|---|---|---|
| 0–2 | El programa de la especificación compila e imprime `3` | `python -m minicompilador ejemplos/validos/programa_especificacion.mini` |
| 2–4 | La explicación fase por fase | `… programa_especificacion.mini --explicar \| less` |
| 4–5 | Un error con línea, columna y sugerencia | `python -m minicompilador ejemplos/errores/lexico_modulo_como_identificador.mini` |
| 5–6 | Las pruebas y el quality gate | `pytest -q \| tail -3` y `htmlcov/index.html` |
| 6–7 | Contrato de la API en contenedores | `docker compose up --build --abort-on-container-exit --exit-code-from test-runner` |
| 7–8 | Drift: provocarlo y detectarlo | sección 5, pregunta 5.6 |
| 8–10 | Pipeline: `ci.yml`, `cd.yml` y el rollback | sección 4, pregunta 4.8; sección 5, pregunta 5.3 |

---

## 2. El compilador

**2.1 ¿Cuáles son las fases y qué produce cada una?**
Son seis. El **léxico** produce tokens; el **sintáctico**, el AST; el
**semántico**, la tabla de símbolos y las advertencias; el **intermedio**, el
código de tres direcciones; la de **registros**, la asignación de R0–R3 con
spill; y la **simulación** ejecuta el programa en la CPU. Cada fase usa la
salida de la anterior, y la compilación se detiene en el primer error.
*En vivo:* `python -m minicompilador ejemplos/validos/programa_especificacion.mini --fase 3 --json | python -m json.tool | head -40`
(con `--fase N` se detiene después de la fase N).

**2.2 ¿Por qué el resultado es 3?**
`a - 2 = 3`; `2.5 * 3 = 7.5`; `7.5 % 3 = 1.5`; `5 + 1.5 = 6.5`. Como `c` es
`int`, se trunca a `6` (por eso aparece la advertencia `FLOAT_A_INT`). Como
`6 > 10` es falso, entra al `else`: `6 / 2 = 3`.
*En vivo:* `--explicar`, sección "¿Qué operación hace cada línea y en qué orden?".

**2.3 ¿Cómo implementaron la precedencia sin un generador de parsers?**
Con la jerarquía de funciones del descenso recursivo:
`expresion → comparacion → suma → termino → factor`. Cuanto más abajo está una
función, más fuerte liga su operador: `termino` maneja `* / %` y se llama desde
`suma`, que maneja `+ -`. La asociatividad izquierda sale de usar un bucle
`while` en lugar de recursión por la derecha.
*En vivo:* `pytest -q -k precedencia -o addopts=""`.

**2.4 ¿Qué es el DFS en postorden y por qué se usa?**
Se recorre el árbol visitando primero el hijo izquierdo, luego el derecho y por
último el nodo. Así, cuando llegamos a un operador, sus dos operandos ya están
calculados en temporales. Es exactamente el orden en que se deben emitir las
instrucciones de tres direcciones.
*En vivo:* `--explicar`, sección "DFS (búsqueda en profundidad) en POSTORDEN".

**2.5 ¿Por qué `%a` es un error si `%` es un operador?**
Porque el prefijo `%t` está reservado para las temporales del compilador
(`%t1`, `%t2`). Si `%a` fuera un nombre válido, el usuario podría escribir
`%t1` y chocar con una temporal. El lexer usa el contexto: `7 % 2` es módulo
porque antes hay un operando, mientras que `= %a` es un error.
*En vivo:*
```bash
python -m minicompilador <(echo 'int a = 7 % 2; print(a);')     # 1
python -m minicompilador <(echo 'int a = 7; int b = %a;')       # error léxico, columna 20
```

**2.6 ¿Cómo se asignan los registros? ¿Qué es un spill?**
Con *linear scan*. Primero se calcula cuándo nace y cuándo muere cada
temporal. Luego se recorren en orden: se liberan los registros de las que ya
murieron y se asigna el libre de número más bajo. Si no queda ninguno (solo hay
4), la temporal va a memoria (`MEM[2000]`); eso es el spill. Funciona igual,
pero cuesta más ciclos.
*En vivo:* `python -m minicompilador ejemplos/validos/spill_registros.mini --json | python -c "import json,sys; r=json.load(sys.stdin); print(r['spills'], r['temporales_vivas_max'], r['salida'])"` → `1 5 ['100']`.

**2.7 ¿Cómo detectan un bucle infinito si es indecidible?**
No lo decidimos: ponemos un **límite de ciclos** (100 000 por defecto,
configurable). Si se supera, lo reportamos como "probablemente un bucle
infinito". Es una heurística honesta: el problema de la parada no tiene solución
general.
*En vivo:* `python -m minicompilador ejemplos/errores/ejecucion_bucle_infinito.mini --limite-ciclos 500`.

**2.8 ¿Por qué `-7 / 2` da `-3` y no `-4` como en Python?**
Mini sigue la semántica de C y Java: la división entera trunca hacia cero.
Python redondea hacia −∞. Está implementado una sola vez en `operaciones.py`, y
lo comparten el plegado de constantes y la CPU, para que optimizar nunca cambie
el resultado.
*En vivo:* `python -m minicompilador <(echo 'print(-7 / 2); print(-7 % 2);') 2>/dev/null` → `-3`, `-1`.

**2.9 ¿Por qué no se pliega `5 / 0` en tiempo de compilación?**
Porque el error se perdería o aparecería sin contexto. El plegado deja la
operación tal cual y la CPU lanza `ErrorEjecucion` con la línea exacta. Con el
desbordamiento (`2147483647 + 1`) pasa lo mismo.
*En vivo:* `pytest -q -k "no_se_pliega" -o addopts=""`.

---

## 3. Momento 1: calidad de las pruebas

**3.1 ¿Qué es el patrón AAA?**
*Arrange* (preparar los datos), *Act* (ejecutar una sola acción) y *Assert*
(verificar). Separarlos hace que cada prueba se lea como una especificación y
que se vea qué se está probando. Todas las pruebas tienen los comentarios
`# Arrange / # Act / # Assert`.
*En vivo:* abrir `tests/unit/test_lexer.py`, primera prueba.

**3.2 ¿Qué son las particiones de equivalencia? Dé un ejemplo.**
Son grupos de entradas que el programa trata igual; basta probar un
representante de cada uno. Ejemplos:
* **Lexer:** identificadores válidos, palabras reservadas, variantes de palabras
  reservadas (`If` y `whileX` son identificadores) y nombres inválidos.
* **API:** 200 (solicitud válida y programa correcto), 422 (solicitud válida y
  programa con error) y 400 (solicitud inválida). La tabla está en el docstring
  de `tests/unit/test_api.py`.

*En vivo:* `pytest -q -k "solicitud_invalida or programa_con_error" -o addopts=""`.

**3.3 ¿Qué valores límite probaron?**

| Límite | On point (válido) | Off point (inválido) | Prueba |
|---|---|---|---|
| Longitud de identificador | 31 caracteres | 32 | `-k valor_limite_longitud` |
| Registros | 4 temporales vivas → 0 spills | 5 → 1 spill | `-k cuatro_vs_cinco` |
| Límite de ciclos | `print(1);` con límite 2 | con límite 1 | `-k valor_limite_de_ciclos` |
| Divisor | 1 y −1 | 0 | `-k division_por_cero` |
| `int` de 32 bits | 2147483647 | 2147483648 | `-k valor_limite_del_rango` |
| `hasta_fase` en la API | 1 y 6 | 0 y 7 | `-k "borde or solicitud_invalida"` |
| Anidamiento del parser | 100 | 101 | `-k limite_de_parentesis` |

*En vivo:* `pytest -v -k "valor_limite or cuatro_vs_cinco" -o addopts=""`.

**3.4 ¿Qué es un error off-by-one y cómo lo probaron?**
Es equivocarse por uno en un borde: columnas que empiezan en 0 o en 1, `<`
en lugar de `<=`. Probamos que las columnas son 1-based, que la columna se
reinicia tras un salto de línea, que el error al final de una línea apunta justo
después del último token y que el límite de ciclos permite llegar exactamente
al límite pero no pasarlo.
*En vivo:* `pytest -q -k "columna or off_by_one" -o addopts=""`.

**3.5 ¿Por qué `parametrize`?**
Por DRY: una sola prueba con una tabla de casos, en lugar de copiar la misma
prueba diez veces (WET). Si cambia la lógica de verificación, se cambia en un
solo lugar, y cada caso aparece como una prueba separada en el reporte.
*En vivo:* `pytest -v -k test_reconoce_cada_operador -o addopts="" | head -20`.

**3.6 ¿Por qué `pytest.raises(match=...)` y no solo `pytest.raises`?**
Porque `pytest.raises(ErrorLexico)` pasaría con *cualquier* error léxico,
incluso uno lanzado por otro motivo. Con `match=` además verificamos el mensaje:
que sea el error correcto y que la explicación al usuario sea la esperada.
*En vivo:* `grep -n "pytest.raises" tests/unit/test_lexer.py | head`.

**3.7 ¿Qué es el quality gate y cómo funciona?**
Es una condición que el código debe cumplir para poder fusionarse.
`--cov-fail-under=85` hace que pytest termine con código 1 si la cobertura baja
del 85 %, **aunque todas las pruebas pasen**, y el CI se pone en rojo. Además,
una prueba de configuración impide bajar ese umbral.
*En vivo:*
```bash
pytest tests/unit/test_lexer.py -q | tail -2               # 98 passed… pero "FAIL Required test coverage" (13 %)
pytest tests/unit/test_lexer.py -q > /dev/null; echo "exit: $?"   # 1 → el CI se pondría en rojo
```

**3.8 Tienen 100 % de cobertura: ¿eso significa que no hay bugs?**
No. La cobertura dice qué líneas se **ejecutaron**, no que se **verificaron**
bien. Por eso medimos cobertura de **ramas** (no solo de líneas), usamos
oráculos calculados a mano y aplicamos valores límite. Aun así encontramos bugs
con 100 % de cobertura: el `inf` que rompía el JSON, la idempotencia del script
de boto3 y el `KeyError` del detector de drift.

**3.9 ¿Qué es un oráculo de prueba? ¿Dónde usaron uno?**
Es la fuente del resultado esperado. Usamos tres tipos:
* **Cálculo a mano:** el programa de la especificación da `3`, 108 ciclos y 8
  temporales.
* **Implementación de referencia:** al optimizar `_max_vivas` de O(n²) a
  O(n log n), dejamos la versión lenta en la prueba y comparamos ambas con 25
  casos aleatorios de semilla fija.
* **El esquema JSON:** es el oráculo de la forma de cada reporte.

*En vivo:* `pytest -q -k max_vivas -o addopts=""`.

**3.10 ¿Qué dobles de prueba usaron?**
* **Stub/mock:** `botocore.stub.Stubber` sustituye a S3 y verifica los
  parámetros exactos de `put_object`.
* **Fake:** un almacenamiento en memoria para probar la API sin S3.
* **Stub de error:** un almacenamiento que siempre falla, para probar la
  degradación elegante.

*En vivo:* `pytest -v tests/unit/test_almacenamiento.py -o addopts="" | tail -20`.

---

## 4. Momento 2: API, contenedores, contrato y CI

**4.1 ¿Por qué 422 y no 400 cuando el programa tiene un error?**
Porque son problemas distintos y RFC 9110 los distingue:
* **400**: la *solicitud* está mal (JSON roto, falta `codigo`, `hasta_fase` = 7).
  Lo corrige quien programa el cliente.
* **422**: la solicitud es correcta, pero su contenido, el *programa Mini*, no se
  puede procesar. Lo corrige el autor del programa.

En el 422 el cuerpo es el reporte completo con el error explicado, y también
cumple el esquema.
*En vivo:*
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/compilar -H 'Content-Type: application/json' -d '{"codigo":"print(1);"}'            # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/compilar -H 'Content-Type: application/json' -d '{"codigo":"x = 1;"}'               # 422
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8000/compilar -H 'Content-Type: application/json' -d '{"codigo":"x","hasta_fase":7}'     # 400
```

**4.2 ¿Qué es una prueba de contrato? ¿En qué se diferencia de una unitaria?**
Verifica lo que un *consumidor* puede dar por garantizado: los códigos HTTP y la
forma del JSON. Nuestro `test-runner` **no importa el compilador**: corre en
otro contenedor, habla solo HTTP y valida cada respuesta con el esquema
publicado en `/esquema`. Además, una prueba compara ese esquema con la copia del
repositorio: si alguien cambia el contrato de un solo lado, falla.
*En vivo:* `docker compose up --build --abort-on-container-exit --exit-code-from test-runner; echo "exit: $?"`.

**4.3 ¿Por qué JSON Schema?**
Es un contrato **ejecutable** y estándar (Draft 2020-12): no es documentación
que se desactualiza. Exige todas las claves, prohíbe claves extra, valida tipos
y patrones (`%t1`, `R0`–`R3`) e incluye una regla condicional: si `exito` es
`false`, `errores` no puede estar vacío. También probamos que el esquema
**rechaza** reportes inválidos.
*En vivo:* `pytest -v -k esquema_detecta -o addopts=""`.

**4.4 ¿Por qué un Dockerfile multi-stage?**
La etapa `constructor` instala dependencias con pip; la etapa `produccion` solo
copia el entorno virtual ya instalado. La imagen final no lleva caché de pip,
código fuente ni herramientas de build: es más pequeña y tiene menos superficie
de ataque. Una tercera etapa, `contrato`, es el cliente de pruebas.

**4.5 ¿Por qué un usuario no root?**
Si alguien explota la API, no es root dentro del contenedor. Además, en compose
la API corre con el sistema de archivos de solo lectura y `no-new-privileges`.
El CI verifica que el uid no sea 0.
*En vivo:* `docker run --rm --entrypoint id minicompilador-api:local` → `uid=10001(compilador)`.

**4.6 ¿Cómo sabe el test-runner que la API ya está lista?**
Con el healthcheck: `depends_on: condition: service_healthy`. Compose espera a
que `/salud` responda antes de arrancar las pruebas. Como respaldo, el fixture
reintenta durante 30 s.

**4.7 ¿Qué hace cada job del CI?**
* `lint`: ruff en la misma versión que en local (reglas y formato).
* `tests`: pytest en Python 3.12 y 3.13, con el gate de cobertura.
* `sonar`: SonarCloud, que mide bugs, code smells, duplicación y cobertura del
  código nuevo, y espera su propio quality gate.
* `docker`: imagen, contrato y verificación de usuario no root.
* `infra`: Terraform sobre LocalStack, más las pruebas de drift.

`lint` y `tests` corren en paralelo para dar respuesta rápida. Los demás solo
corren si esos dos pasan.

**4.8 ¿Cómo prueban el propio pipeline?**
Con `tests/unit/test_configuracion_ci.py`: 16 pruebas que leen el YAML y fallan
si alguien borra un job, quita el disparador de pull request, baja el umbral,
escribe un secreto en texto plano, amplía los permisos del token o hace que el
CD promueva antes de verificar.
*En vivo:* `pytest -v tests/unit/test_configuracion_ci.py -o addopts=""`.

---

## 5. Bloque 2: carga, CD e infraestructura

**5.1 ¿Qué miden p50 y p95? ¿Por qué no el promedio?**
p50 es la mediana: la mitad de las solicitudes tardó menos. p95: el 95 % tardó
menos; es lo que sufren los usuarios "con mala suerte". El promedio esconde la
cola: unas pocas solicitudes lentas lo distorsionan. Con 20 usuarios obtuvimos
p50 = 13 ms, p95 = 51 ms y 59 RPS, sin fallos.
*En vivo (30 s):* `locust -f tests/carga/locustfile.py --host http://localhost:8000 --headless -u 20 -r 5 -t 30s --only-summary`.

**5.2 ¿Cuál es el cuello de botella?**
Hay que separar dos cosas, y medimos ambas:
* **Robustez:** es la recursión del parser. Cada nivel de paréntesis consume
  unos 5 marcos de pila y Python corta en 1000. Sin límite, 200 niveles
  provocan `RecursionError`, que sería un 500. Con `PROFUNDIDAD_MAXIMA = 100`
  hay un margen de 2× y el usuario recibe un 422 explicado.
* **Tiempo:** el parser *no* era lo más caro. El perfilado mostró que lo era
  `_max_vivas`, un cálculo O(n²) de la fase de registros. Al pasarlo a
  O(n log n), la compilación del programa largo bajó un 30 %.
* **Capacidad:** un solo proceso uvicorn se satura en ~190 RPS por el GIL. La
  solución es usar varios procesos (`--workers`).

*En vivo:* `python tests/carga/perfil_cuello_botella.py 2>/dev/null`.

**5.3 ¿Cómo funciona el rollback automático?**
`desplegar.sh` sigue estos pasos:
1. Recuerda la imagen que está corriendo y detiene su contenedor sin borrarlo.
2. Arranca la imagen nueva y la verifica: healthcheck de `/salud` y una prueba
   de humo que compila `6 * 7` y exige `42`.
3. Si falla, borra la nueva, reactiva la anterior y termina con exit 1: el
   pipeline queda en rojo, pero el servicio sigue funcionando.

Solo si pasa, el CD promueve la imagen a `:estable`.
*En vivo:*
```bash
docker compose down 2>/dev/null; docker build -q -t minicompilador-api:local --target produccion . >/dev/null
printf 'FROM minicompilador-api:local\nCMD ["python","-c","import sys; sys.exit(1)"]\n' | docker build -q -t minicompilador-api:rota - >/dev/null
./infra/despliegue/desplegar.sh minicompilador-api:local             # ✔ exitoso
INTENTOS=4 ./infra/despliegue/desplegar.sh minicompilador-api:rota   # ✘ → ↩ rollback, exit 1
curl -s localhost:8080/salud; docker rm -f minicompilador-api
```

**5.4 ¿Cómo se manejan los secretos?**
Nunca están en el código: `SONAR_TOKEN`, `DOCKERHUB_USERNAME` y
`DOCKERHUB_TOKEN` se guardan en GitHub Secrets. El de Docker Hub es un token de
acceso, no la contraseña. El token de GitHub tiene permisos de solo lectura.
Las credenciales `test` de LocalStack son ficticias y no sirven en AWS.

**5.5 ¿Declarativo frente a imperativo?**
* **Terraform (declarativo):** se describe *cómo debe quedar*. Terraform guarda
  un estado, calcula el plan y es idempotente por diseño. Si se borra un recurso
  del código, propone eliminarlo.
* **boto3 (imperativo):** se escriben *los pasos*. El orden lo decide quien
  programa, la idempotencia hay que programarla a mano y no sabe deshacer.

Lo vivimos: en `us-east-1`, `create_bucket` sobre un bucket propio que ya existe
no da error, así que nuestra forma de evitar duplicados capturando la excepción
nunca se activaba. Lo encontró una prueba.
*En vivo:* `sed -n 1,25p infra/scripts/crear_bucket_imperativo.py` (tabla comparativa).

**5.6 ¿Qué es el drift y cómo lo prueban?**
Es la diferencia entre la infraestructura declarada y la real, causada por
cambios manuales. La declarada (`infra/estado_deseado.json`) es el oráculo. La
prueba lee el bucket real con boto3, **provoca** cambios manuales y verifica que
se detectan. Una prueba que nunca puede fallar no protege nada.
*En vivo (con el perfil S3 levantado):*
```bash
export AWS_ENDPOINT_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1
python infra/scripts/drift.py                       # ✔ sin drift (exit 0)
python -c "import boto3; from botocore.config import Config; boto3.client('s3', config=Config(s3={'addressing_style':'path'})).put_bucket_versioning(Bucket='minicompilador-reportes', VersioningConfiguration={'Status':'Suspended'})"
python infra/scripts/drift.py; echo "exit: $?"     # ✘ versionado: Enabled ≠ Suspended (exit 2)
./infra/tf.sh plan -detailed-exitcode; echo $?      # Terraform también lo ve (exit 2)
./infra/tf.sh apply -auto-approve                   # remediar
python infra/scripts/drift.py                       # ✔ sin drift
```

**5.7 ¿Qué pasa si S3 se cae?**
El usuario recibe su reporte igual (200 o 422). Guardar es un efecto
secundario, así que la API registra el fallo y responde con la cabecera
`X-Reporte-Guardado: error`. Es una degradación elegante, y está probada con un
doble que siempre falla.
*En vivo:* `pytest -v -k "s3_falla" -o addopts=""`.

---

## 6. Preguntas difíciles (respuestas honestas)

**¿Qué limitaciones tiene el proyecto?**
* Mini tiene un único ámbito global; no hay funciones ni arreglos.
* La verificación de "no inicializada" no sigue el flujo del programa: usa una
  aproximación.
* El CD despliega sobre el runner efímero de GitHub; en producción, el mismo
  script se ejecutaría por SSH en un servidor.
* El workflow de CD no se ha ejecutado todavía en GitHub; su script central sí
  se probó en local en los dos caminos.

**¿Por qué fijaron el provider de AWS en 5.70.x?**
Las versiones nuevas esperan un campo del ciclo de vida del bucket que
LocalStack 3.8 no devuelve: el `apply` esperaba 3 minutos y fallaba. Fijar
versiones es reproducibilidad; el motivo está comentado en `versions.tf`.

**¿Qué bugs encontraron las pruebas?**
1. Un `float` desbordado daba `inf`, que no es JSON válido: la API respondía 500.
2. El script de boto3 no era realmente idempotente en `us-east-1`.
3. El detector de drift se caía con `KeyError` tras borrar el cifrado.
4. Un cálculo O(n²) en la fase de registros, que la medición de rendimiento
   señaló como la parte más cara.

**¿Por qué no usaron el módulo `ast` de Python o un generador de parsers?**
Era requisito del curso, y además tiene valor didáctico: cada decisión del
lexer y del parser es visible, se puede explicar y se puede probar. Un generador
la escondería.
