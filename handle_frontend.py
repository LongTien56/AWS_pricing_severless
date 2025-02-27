import json
import boto3

S3_BUCKET = "your-frontend-bucket"

s3 = boto3.client("s3")

def lambda_handler(event, context):
    try:
        response = s3.get_object(Bucket=S3_BUCKET, Key="index.html")
        html_content = response["Body"].read().decode("utf-8")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "text/html"
            },
            "body": html_content
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
