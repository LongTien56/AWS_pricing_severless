import json
import uuid
from datetime import datetime
from io import BytesIO
import pandas as pd
import boto3
import base64
import xlsxwriter

# Cấu hình S3 và DynamoDB (chỉnh sửa tên theo môi trường của bạn)
S3_BUCKET = "generated-bom-files"               # Thay bằng tên S3 bucket của bạn
DYNAMODB_TABLE = "generated_bom_files_metadata"       # Thay bằng tên DynamoDB table của bạn

# Khởi tạo client S3 và DynamoDB resource
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
metadata_table = dynamodb.Table(DYNAMODB_TABLE)

def lambda_handler(event, context):
    try:
        # 1. Lấy thông tin người dùng từ custom authorizer (ví dụ: email) trong context của API Gateway
        # Thông tin này sẽ được truyền trong event["requestContext"]["authorizer"]
        authorizer_context = event["requestContext"]["authorizer"]
        user_email = authorizer_context.get("email")
        if not user_email:
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "User not authenticated"})
            }
        
        # 2. Nhận dữ liệu từ request body (giả sử gửi dưới dạng JSON)
        body = event.get("body", "")
        if event.get("isBase64Encoded", False):
            body = base64.b64decode(body).decode("utf-8")
        data = json.loads(body)
        json_data = data.get("jsonData")
        if not json_data:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No JSON data provided"})
            }
        
        # 3. Xử lý dữ liệu JSON để tạo file Excel
        services = json_data.get("Groups", {}).get("Services", [])
        excel_data = {
            'Region': [],
            'Service': [],
            'Monthly ($)': [],
            'First 12 Month Total ($)': [],
            'Config Summary': []
        }
        for service in services:
            region = service.get("Region", "N/A")
            service_name = service.get("Service Name", "")
            monthly = float(service.get("Service Cost", {}).get("monthly", 0))
            monthly_cost = f"${monthly:,.2f}"
            yearly_cost = f"${monthly * 12:,.2f}"
            excel_data['Region'].append(region)
            excel_data['Service'].append(service_name)
            excel_data['Monthly ($)'].append(monthly_cost)
            excel_data['First 12 Month Total ($)'].append(yearly_cost)
            detail = ", ".join([f"{k}: {v}" for k, v in service.get("Properties", {}).items()])
            excel_data['Config Summary'].append(detail)
        
        df = pd.DataFrame(excel_data)
        total_monthly = f"${sum([float(x.replace('$','').replace(',','')) for x in df['Monthly ($)']]):.2f}"
        total_12_month = f"${sum([float(x.replace('$','').replace(',','')) for x in df['First 12 Month Total ($)']]):.2f}"
        total_row = ['', '', total_monthly, total_12_month, '']
        calculator_row = ['', '', '', '', '']
        df.loc[len(df)] = total_row
        df.loc[len(df)] = calculator_row
        
        # Tạo file Excel trong bộ nhớ
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='EST', index=False)
            workbook = writer.book
            worksheet = writer.sheets['EST']
            
            # Định dạng header với nền vàng
            yellow_format = workbook.add_format({
                'bg_color': '#FFFF00',
                'bold': True,
                'border': 1,
                'align': 'center',
                'valign': 'vcenter'
            })
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, yellow_format)
        output.seek(0)
        
        # 4. Tạo tên file và S3 key dựa trên email của người dùng
        file_uuid = str(uuid.uuid4())
        s3_key = f"{user_email}/{file_uuid}.xlsx"
        
        # Upload file Excel lên S3
        s3_client.upload_fileobj(output, S3_BUCKET, s3_key)
        
        # 5. Lưu metadata file vào DynamoDB
        metadata_item = {
            "user_email": user_email,            # Partition key
            "file_id": file_uuid,                # Có thể dùng file_uuid làm sort key
            "s3_key": s3_key,
            "s3_url": f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        metadata_table.put_item(Item=metadata_item)
        
        # 6. Để trực tiếp download file, lấy nội dung file từ S3
        s3_object = s3_client.get_object(Bucket=S3_BUCKET, Key=s3_key)
        file_content = s3_object['Body'].read()
        
        # Trả về file dưới dạng binary để người dùng download trực tiếp
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "Content-Disposition": f"attachment; filename={file_uuid}.xlsx"
            },
            "isBase64Encoded": True,
            "body": base64.b64encode(file_content).decode("utf-8")
        }
        
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
