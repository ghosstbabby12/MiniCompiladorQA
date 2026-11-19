# MiniCompilador QA

Compilador didáctico del lenguaje **Mini**, escrito a mano en Python 3.12 puro
(sin PLY, Lark, ANTLR ni el módulo `ast`), para el curso **Pruebas y
Mantenimiento de Software**. El proyecto sirve a la vez de ejemplo de compilador
de 6 fases y de ejemplo de prácticas de calidad: pruebas, contrato, CI/CD e
infraestructura como código.

| | |
|---|---|
| Pruebas unitarias | **516**, cobertura **100 %** de líneas y ramas (quality gate: 85 %) |
| Pruebas de contrato (HTTP + JSON Schema) | **36** |
| Pruebas de infraestructura (drift) | **12** |
| Carga, 20 usuarios | **59 RPS**, p50 **13 ms**, p95 **51 ms**, 0 fallos ([detalle](docs/RENDIMIENTO.md)) |

## El lenguaje Mini en 30 segundos

```c
// ejemplos/validos/programa_especificacion.mini
int a = 5;
float b = 2.5;
int c;
c = a + b * (a - 2) % 3;     // 5 + (2.5 * 3) % 3 = 5 + 1.5 = 6.5 → int → 6
if (c > 10) {
    print(c);
} else {
    c = c / 2;               // 3
    print(c);
}
while (a > 0) {
    a = a - 1;
}
```

* Tipos `int` (32 bits, como en C y Java), `float` (finito) y `bool`.
  Palabras reservadas: `if else while print true false`.
* Precedencia: `* / %` > `+ -` > relacionales (que no se pueden encadenar).
* Identificadores `[A-Za-z_][A-Za-z0-9_]*` de **máximo 31** caracteres.
* `%` es solo el operador módulo: `%a` es un error léxico, porque el prefijo
  `%t` está reservado para las temporales del compilador.
* La división entera y el módulo truncan hacia cero, como en C
  (`-7 / 2 = -3`, `-7 % 2 = -1`).

## Inicio rápido

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

python -m minicompilador ejemplos/validos/programa_especificacion.mini             # imprime 3
python -m minicompilador ejemplos/validos/programa_especificacion.mini --explicar   # paso a paso
python -m minicompilador ejemplos/validos/programa_especificacion.mini --fase 4 --json

pytest                      # 516 pruebas + cobertura + quality gate (htmlcov/index.html)
ruff check src tests infra && ruff format --check src tests infra
```

Códigos de salida del CLI: `0` = todo bien, `1` = el programa Mini tiene un
error, `2` = el CLI se usó mal.

## Las 6 fases

```
código .mini
  │ 1. léxico       lexer.py        autómata escrito a mano → tokens (línea, columna)
  │ 2. sintáctico   parser.py       descenso recursivo LL(1) → AST (ast_nodos.py)
  │ 3. semántico    semantico.py    tabla de símbolos, tipos, advertencias
  │ 4. intermedio   intermedio.py   código de 3 direcciones (%t1…), DFS postorden, plegado
  │ 5. registros    registros.py    linear scan con 4 registros (R0–R3) y spill a memoria
  ▼ 6. simulación   cpu.py          ISA de 14 instrucciones, memoria, ciclos, errores
reporte JSON (reporte.py) ── validado con esquemas/reporte.schema.json
```

Cada error es un `ErrorLexico`, `ErrorSintactico`, `ErrorSemantico` o
`ErrorEjecucion` (todos derivan de `ErrorCompilador`) con fase, línea, columna,
mensaje y sugerencia. Diagramas y decisiones de diseño:
[docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## API

```bash
docker compose up -d --build --wait api
curl -s -X POST localhost:8000/compilar -H 'Content-Type: application/json' \
     -d '{"codigo":"print(6 * 7);"}'
# Swagger: http://localhost:8000/docs
docker compose down
```

| Endpoint | Respuesta |
|---|---|
| `GET /salud` | `200 {"estado":"ok","version":...}` |
| `GET /esquema` | `200` el JSON Schema del reporte (el contrato) |
| `POST /compilar` | `200` compiló y se ejecutó · `422` el **programa** tiene un error (el cuerpo es el reporte) · `400` la **solicitud** está mal |
| `POST /explicar` | lo mismo, pero en texto plano paso a paso |

## Pruebas

| Nivel | Dónde | Cómo se ejecuta |
|---|---|---|
| Unitarias y de componente | `tests/unit` | `pytest` |
| Contrato (HTTP real + JSON Schema) | `tests/api` | `docker compose up --build --abort-on-container-exit --exit-code-from test-runner` |
| Infraestructura (drift) | `tests/infra` | ver *Infraestructura* |
| Carga | `tests/carga` | `locust -f tests/carga/locustfile.py --host http://localhost:8000 --headless -u 20 -r 5 -t 30s` |

Todas las pruebas siguen el patrón **AAA** y usan particiones de equivalencia,
valores límite (31/32 caracteres, 4/5 registros, límite de ciclos, divisor 0,
2147483647/2147483648), `parametrize` y `pytest.raises(match=...)`.

## CI/CD

* **CI** ([ci.yml](.github/workflows/ci.yml)), en cada push y pull request:
  `lint` (ruff) y `tests` (Python 3.12 y 3.13, gate del 85 %) corren en
  paralelo. Si ambos pasan, siguen `sonar` (SonarCloud), `docker` (imagen +
  contrato) e `infra` (Terraform + drift).
* **CD** ([cd.yml](.github/workflows/cd.yml)), cuando CI pasa en `main`:
  1. publica la imagen `:<sha>` en Docker Hub (con credenciales de Secrets);
  2. la despliega con healthcheck y una prueba de humo, y hace **rollback
     automático** si falla;
  3. si pasó, la promueve a `:estable`.

Secrets necesarios: `SONAR_TOKEN`, `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN`.
En SonarCloud hay que desactivar *Automatic Analysis*.

## Infraestructura (LocalStack + Terraform)

```bash
docker compose -f docker-compose.yml -f docker-compose.s3.yml up -d --build --wait api
# localstack → terraform apply → api (guarda cada reporte en s3://minicompilador-reportes)

./infra/tf.sh plan -detailed-exitcode                                  # 0 = sin drift
AWS_ENDPOINT_URL=http://localhost:4566 python infra/scripts/drift.py   # 0 = sin drift, 2 = drift
LOCALSTACK_URL=http://localhost:4566 AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test \
  pytest tests/infra -o addopts=""
```

El estado deseado del bucket vive en un solo archivo,
[infra/estado_deseado.json](infra/estado_deseado.json), que leen Terraform
(enfoque declarativo), [crear_bucket_imperativo.py](infra/scripts/crear_bucket_imperativo.py)
(enfoque imperativo, con boto3) y la prueba de drift.

## Estructura

```
src/minicompilador/   lexer, parser, ast_nodos, semantico, intermedio, registros, cpu,
                      operaciones, errores, reporte, explicador, cli, api, almacenamiento
  esquemas/           reporte.schema.json (JSON Schema 2020-12)
ejemplos/             validos/ y errores/ (un ejemplo por tipo de error; el prefijo indica la fase)
tests/                unit/  api/  infra/  carga/
infra/                terraform/  scripts/ (boto3, drift)  despliegue/ (rollback)  tf.sh
.github/workflows/    ci.yml  cd.yml
docs/                 GUIA_SUSTENTACION.md  ARQUITECTURA.md  RENDIMIENTO.md
Dockerfile            multi-stage: constructor → contrato → produccion (usuario no root)
```

## Documentación

* [Guía de sustentación](docs/GUIA_SUSTENTACION.md): preguntas probables,
  respuestas y el comando para demostrar cada una en vivo.
* [Arquitectura](docs/ARQUITECTURA.md): diagramas de las fases, del pipeline y
  de la infraestructura.
* [Rendimiento](docs/RENDIMIENTO.md): resultados de la carga y análisis del
  cuello de botella.
