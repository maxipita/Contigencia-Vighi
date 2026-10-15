resource "aws_s3_bucket" "archivos" {
  bucket = local.bucket_datos
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "archivos" {
  bucket = aws_s3_bucket.archivos.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archivos" {
  bucket = aws_s3_bucket.archivos.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "archivos" {
  bucket                  = aws_s3_bucket.archivos.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "archivos" {
  bucket = aws_s3_bucket.archivos.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "SoloTLS"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.archivos.arn, "${aws_s3_bucket.archivos.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.archivos]
}

resource "aws_s3_bucket_lifecycle_configuration" "archivos" {
  bucket = aws_s3_bucket.archivos.id
  rule {
    id     = "versiones-viejas"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
  depends_on = [aws_s3_bucket_versioning.archivos]
}
