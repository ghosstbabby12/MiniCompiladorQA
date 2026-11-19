# ===========================================================================
# Infraestructura como código (DECLARATIVA): el bucket de reportes.
#
# Aquí describimos CÓMO DEBE QUEDAR la infraestructura, no los pasos para
# crearla. Terraform compara este estado deseado con el real y calcula el
# plan (crear / modificar / no hacer nada). Compárese con el enfoque
# IMPERATIVO de infra/scripts/crear_bucket_imperativo.py.
#
# Los valores salen de ../estado_deseado.json: la misma fuente de verdad que
# usan el script de boto3 y la prueba de drift (si cambia, cambia en todos).
# ===========================================================================

locals {
  deseado   = jsondecode(file("${path.module}/../estado_deseado.json"))
  etiquetas = merge(local.deseado.etiquetas, { entorno = var.entorno })
}

# LocalStack imita la API de AWS en local: credenciales falsas y endpoints
# propios. Para AWS real bastaría con quitar este bloque de configuración.
provider "aws" {
  region                      = local.deseado.region
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true

  endpoints {
    s3 = var.endpoint_localstack
  }
}

resource "aws_s3_bucket" "reportes" {
  bucket = local.deseado.bucket
  tags   = local.etiquetas
}

# Versionado: si un reporte se sobrescribe o borra, la versión anterior se conserva.
resource "aws_s3_bucket_versioning" "reportes" {
  bucket = aws_s3_bucket.reportes.id

  versioning_configuration {
    status = local.deseado.versionado
  }
}

# Cifrado en reposo por defecto para todo objeto nuevo.
resource "aws_s3_bucket_server_side_encryption_configuration" "reportes" {
  bucket = aws_s3_bucket.reportes.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = local.deseado.cifrado
    }
  }
}

# Los reportes contienen código de los usuarios: nunca deben ser públicos.
resource "aws_s3_bucket_public_access_block" "reportes" {
  bucket                  = aws_s3_bucket.reportes.id
  block_public_acls       = local.deseado.bloqueo_acceso_publico
  block_public_policy     = local.deseado.bloqueo_acceso_publico
  ignore_public_acls      = local.deseado.bloqueo_acceso_publico
  restrict_public_buckets = local.deseado.bloqueo_acceso_publico
}

# Ciclo de vida: los reportes caducan solos (costo y privacidad controlados).
resource "aws_s3_bucket_lifecycle_configuration" "reportes" {
  bucket = aws_s3_bucket.reportes.id

  rule {
    id     = "expirar-reportes"
    status = "Enabled"

    filter {
      prefix = "reportes/"
    }

    expiration {
      days = local.deseado.dias_retencion_reportes
    }

    noncurrent_version_expiration {
      noncurrent_days = local.deseado.dias_retencion_reportes
    }
  }

  # El ciclo de vida exige que el versionado esté configurado antes.
  depends_on = [aws_s3_bucket_versioning.reportes]
}
