"""Friendly names for AWS product codes.

When a CUR lacks the human ``product_servicename`` column, the service breakdown
falls back to the product code (``AmazonRDS``, ``AWSQueueService``). This maps the
common codes to readable names. Unmapped codes pass through unchanged.
"""

from __future__ import annotations

PRODUCT_CODE_NAMES: dict[str, str] = {
    "AmazonEC2": "Amazon EC2",
    "AmazonRDS": "Amazon RDS",
    "AmazonS3": "Amazon S3",
    "AWSLambda": "AWS Lambda",
    "AmazonVPC": "Amazon VPC",
    "AmazonCloudFront": "Amazon CloudFront",
    "AmazonCloudWatch": "Amazon CloudWatch",
    "AmazonElastiCache": "Amazon ElastiCache",
    "AmazonAthena": "Amazon Athena",
    "AmazonDynamoDB": "Amazon DynamoDB",
    "AmazonRoute53": "Amazon Route 53",
    "AmazonECR": "Amazon ECR",
    "AmazonECS": "Amazon ECS",
    "AmazonEKS": "Amazon EKS",
    "AmazonES": "Amazon OpenSearch",
    "AmazonRedshift": "Amazon Redshift",
    "AmazonSNS": "Amazon SNS",
    "AWSQueueService": "Amazon SQS",
    "AWSSecretsManager": "AWS Secrets Manager",
    "AWSGlue": "AWS Glue",
    "AWSCloudTrail": "AWS CloudTrail",
    "AWSDataTransfer": "AWS Data Transfer",
    "AWSELB": "Elastic Load Balancing",
    "AmazonApiGateway": "Amazon API Gateway",
    "AmazonKinesis": "Amazon Kinesis",
    "AmazonSageMaker": "Amazon SageMaker",
    "awskms": "AWS KMS",
}
