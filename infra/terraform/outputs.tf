output "bucket" {
  description = "Nombre del bucket (va en la variable MINICOMPILADOR_BUCKET de la API)"
  value       = aws_s3_bucket.reportes.bucket
}

output "arn" {
  description = "ARN del bucket"
  value       = aws_s3_bucket.reportes.arn
}
