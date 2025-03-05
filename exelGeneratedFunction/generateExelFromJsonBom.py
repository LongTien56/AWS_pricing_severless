import json
import uuid
from datetime import datetime
from io import BytesIO
import pandas as pd
import xlsxwriter
import boto3
import base64

# Cấu hình S3 và DynamoDB
S3_BUCKET = "generated-bom-files"                # Thay bằng tên S3 bucket của bạn
DYNAMODB_TABLE = "generated_bom_file_metadata"    # Thay bằng tên bảng DynamoDB của bạn

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
metadata_table = dynamodb.Table(DYNAMODB_TABLE)

def lambda_handler(event, context):
    try:
        # 1. Lấy thông tin người dùng từ context của custom authorizer
        authorizer = event.get("requestContext", {}).get("authorizer", {})
        user_email = authorizer.get("lambda", {}).get("email")
        if not user_email:
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "User not authenticated"})
            }
        
        # 2. Nhận dữ liệu từ request body (JSON)
        body = event.get("body", "")
        if event.get("isBase64Encoded", False):
            body = base64.b64decode(body).decode("utf-8")
        data = json.loads(body)
        
        # Lấy customerName từ payload
        customer_name = data.get("customerName", "").strip()
        if not customer_name:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Customer name is required"})
            }
        
        json_data = data.get("jsonData")
        if not json_data:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No JSON data provided"})
            }
        
        # 3. Xử lý dữ liệu JSON để tạo file Excel
        services = json_data.get("Groups", {}).get("Services", [])
        excel_data = {
            "Region": [],
            "Service": [],
            "Monthly ($)": [],
            "First 12 Month Total ($)": [],
            "Config Summary": []
        }
        for service in services:
            region = service.get("Region", "N/A")
            service_name = service.get("Service Name", "")
            monthly = float(service.get("Service Cost", {}).get("monthly", 0))
            monthly_cost = f"${monthly:,.2f}"
            yearly_cost = f"${monthly * 12:,.2f}"
            excel_data["Region"].append(region)
            excel_data["Service"].append(service_name)
            excel_data["Monthly ($)"].append(monthly_cost)
            excel_data["First 12 Month Total ($)"].append(yearly_cost)
            detail = ", ".join([f"{k}: {v}" for k, v in service.get("Properties", {}).items()])
            excel_data["Config Summary"].append(detail)
        
        df = pd.DataFrame(excel_data)
        total_monthly = f"${sum([float(x.replace('$','').replace(',','')) for x in df['Monthly ($)']]):.2f}"
        total_12_month = f"${sum([float(x.replace('$','').replace(',','')) for x in df['First 12 Month Total ($)']]):.2f}"
        total_row = ["", "", total_monthly, total_12_month, ""]
        calculator_row = ["", "", "", "", ""]
        df.loc[len(df)] = total_row
        df.loc[len(df)] = calculator_row
        
        # 4. Tạo file Excel trong bộ nhớ
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, sheet_name="EST", index=False)
            workbook = writer.book
            worksheet = writer.sheets["EST"]
            yellow_format = workbook.add_format({
                "bg_color": "#FFFF00",
                "bold": True,
                "border": 1,
                "align": "center",
                "valign": "vcenter"
            })
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, yellow_format)
        output.seek(0)
        
        # 5. Tạo tên file và S3 key dựa trên customer name (thay vì file_uuid đơn thuần)
        # Chúng ta có thể làm: "<customer_name>_<uuid>.xlsx"
        file_uuid = str(uuid.uuid4())
        # Loại bỏ ký tự không hợp lệ cho tên file (nếu cần)
        safe_customer_name = "".join(c for c in customer_name if c.isalnum() or c in (' ', '_')).strip().replace(" ", "_")
        s3_key = f"{user_email}/{safe_customer_name}_{file_uuid}.xlsx"
        
        # Upload file Excel lên S3
        s3_client.upload_fileobj(output, S3_BUCKET, s3_key)
        
        # 6. Lưu metadata vào DynamoDB
        metadata_item = {
            "user_email": user_email,
            "file_id": file_uuid,
            "customer_name": customer_name,
            "s3_key": s3_key,
            "s3_url": f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        metadata_table.put_item(Item=metadata_item)
        
        # 7. Tạo pre-signed URL để tải file (URL có hiệu lực 1 giờ)
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": s3_key},
            ExpiresIn=3600
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Excel file generated and stored successfully",
                "file_url": presigned_url
            })
        }
        
    except Exception as e:
        import traceback
        error_message = traceback.format_exc()
        print("Exception:", error_message)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
