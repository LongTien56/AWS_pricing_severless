import json
import boto3
from boto3.dynamodb.conditions import Key

# Cấu hình S3 và DynamoDB (điều chỉnh tên theo môi trường của bạn)
S3_BUCKET = "generated-bom-files"  # Tên S3 bucket của bạn
DYNAMODB_TABLE = "generated_bom_file_metadata"  # Tên bảng DynamoDB của bạn

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
metadata_table = dynamodb.Table(DYNAMODB_TABLE)

def lambda_handler(event, context):
    try:
        # 1. Lấy thông tin user từ custom authorizer trong event["requestContext"]["authorizer"]
        authorizer = event.get("requestContext", {}).get("authorizer", {})
        user_email = authorizer.get("lambda", {}).get("email")
        if not user_email:
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "User not authenticated"})
            }
        
        # 2. Query bảng DynamoDB theo user_email (là partition key)
        response = metadata_table.query(
            KeyConditionExpression=Key("user_email").eq(user_email)
        )
        items = response.get("Items", [])
        
        # 3. Với mỗi mục, tạo pre-signed URL mới
        for item in items:
            s3_key = item.get("s3_key")
            if s3_key:
                presigned_url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET, "Key": s3_key},
                    ExpiresIn=3600  # URL có hiệu lực 1 giờ
                )
                item["presigned_url"] = presigned_url
        
        # 4. Trả về danh sách file dưới dạng JSON
        return {
            "statusCode": 200,
            "body": json.dumps({"files": items})
        }
        
    except Exception as e:
        import traceback
        error_message = traceback.format_exc()
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e), "trace": error_message})
        }
