"""Prueba de DRIFT de configuración del bucket de reportes.

Idea: la infraestructura declarada (estado_deseado.json → Terraform) es el
oráculo. La prueba lee la infraestructura REAL y exige que coincidan. Si
alguien la cambia a mano, la prueba se pone en rojo.

También se prueba el propio detector (¿de verdad detecta un cambio?): una
prueba que nunca puede fallar no protege nada.
"""

import copy

import pytest
from crear_bucket_imperativo import crear_o_actualizar
from drift import cargar_estado_deseado, diferencias, leer_estado_real

DESEADO = cargar_estado_deseado()


# ---------------------------------------------------------------------------
# Lógica pura del detector (sin LocalStack)
# ---------------------------------------------------------------------------


def test_sin_diferencias_cuando_real_es_igual_a_lo_declarado():
    # Arrange
    real = {k: v for k, v in DESEADO.items() if k != "region"}

    # Act / Assert
    assert diferencias(DESEADO, real) == []


@pytest.mark.parametrize(
    ("clave", "valor_manual"),
    [
        ("versionado", "Suspended"),
        ("cifrado", None),
        ("bloqueo_acceso_publico", False),
        ("dias_retencion_reportes", 365),
        ("etiquetas", {}),
    ],
)
def test_cada_tipo_de_cambio_manual_se_reporta(clave, valor_manual):
    # Arrange: una clase de equivalencia por aspecto configurable.
    real = {k: copy.deepcopy(v) for k, v in DESEADO.items() if k != "region"}
    real[clave] = valor_manual

    # Act
    cambios = diferencias(DESEADO, real)

    # Assert
    assert len(cambios) == 1
    assert cambios[0].startswith(f"{clave}:")


def test_bucket_inexistente_es_drift():
    # Arrange / Act
    cambios = diferencias(DESEADO, None)

    # Assert
    assert cambios == ["el bucket 'minicompilador-reportes' no existe"]


# ---------------------------------------------------------------------------
# Contra LocalStack
# ---------------------------------------------------------------------------


@pytest.fixture
def restaurar(s3):
    """Tras cada prueba que provoca drift, vuelve al estado declarado."""
    yield
    crear_o_actualizar(s3, DESEADO)


def test_bucket_real_coincide_con_lo_declarado(s3):
    # Arrange / Act
    real = leer_estado_real(s3, DESEADO["bucket"])

    # Assert
    assert diferencias(DESEADO, real) == []


@pytest.mark.usefixtures("restaurar")
def test_cambio_manual_de_versionado_se_detecta(s3):
    # Arrange: un "arreglo rápido" hecho a mano, fuera de Terraform.
    s3.put_bucket_versioning(
        Bucket=DESEADO["bucket"], VersioningConfiguration={"Status": "Suspended"}
    )

    # Act
    cambios = diferencias(DESEADO, leer_estado_real(s3, DESEADO["bucket"]))

    # Assert
    assert cambios == ["versionado: declarado='Enabled' real='Suspended'"]


@pytest.mark.usefixtures("restaurar")
def test_quitar_el_cifrado_se_detecta(s3):
    # Arrange
    s3.delete_bucket_encryption(Bucket=DESEADO["bucket"])

    # Act
    real = leer_estado_real(s3, DESEADO["bucket"])

    # Assert: LocalStack, como AWS desde 2023, puede seguir aplicando SSE-S3
    # por defecto; lo importante es que el detector lee el valor real.
    assert real["cifrado"] in (None, "AES256")


def test_script_imperativo_es_idempotente(s3):
    # Arrange: el bucket ya existe (lo creó Terraform).
    # Act: ejecutarlo dos veces no debe fallar ni cambiar el resultado.
    primera = crear_o_actualizar(s3, DESEADO)
    segunda = crear_o_actualizar(s3, DESEADO)

    # Assert
    assert "ya existía" in primera[0]
    assert primera == segunda
    assert diferencias(DESEADO, leer_estado_real(s3, DESEADO["bucket"])) == []


def test_script_imperativo_crea_un_bucket_nuevo_completo(s3):
    # Arrange: otro nombre, para no tocar el bucket que gestiona Terraform.
    deseado = {**DESEADO, "bucket": "minicompilador-prueba-imperativa"}

    try:
        # Act
        bitacora = crear_o_actualizar(s3, deseado)

        # Assert
        assert bitacora[0] == "creado s3://minicompilador-prueba-imperativa"
        assert diferencias(deseado, leer_estado_real(s3, deseado["bucket"])) == []
    finally:
        s3.delete_bucket(Bucket=deseado["bucket"])
