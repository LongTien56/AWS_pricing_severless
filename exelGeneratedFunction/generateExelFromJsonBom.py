import json
import uuid
import base64
import boto3
import logging
from datetime import datetime
from io import BytesIO
import pandas as pd
import xlsxwriter
from requests_toolbelt.multipart import decoder  # ✅ Required for multipart parsing

# Enable logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS Services
S3_BUCKET = "generated-bom-files"
DYNAMODB_TABLE = "generated_bom_file_metadata"

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
metadata_table = dynamodb.Table(DYNAMODB_TABLE)

def lambda_handler(event, context):
    """AWS Lambda handler to process JSON and image upload, generate an Excel file, and store in S3."""
    try:
        logger.info("🔹 Lambda function triggered")
        logger.info("Received event: %s", json.dumps(event))

        # 1. Get Content-Type from headers
        content_type = event["headers"].get("content-type", "")
        if "multipart/form-data" not in content_type:
            logger.error("❌ Invalid content type: Expected multipart/form-data")
            return {"statusCode": 400, "body": json.dumps({"error": "Invalid content type"})}

        # 2. Decode multipart/form-data request
        body_bytes = base64.b64decode(event["body"]) if event.get("isBase64Encoded") else event["body"]
        multipart_data = decoder.MultipartDecoder(body_bytes, content_type)

        customer_name = None
        json_data = None
        image_bytes = None

        for part in multipart_data.parts:
            content_disposition = part.headers.get(b'Content-Disposition', b'').decode()

            if 'name="customerName"' in content_disposition:
                customer_name = part.text.strip()

            if 'name="jsonData"' in content_disposition:
                json_data = json.loads(part.text)

            if 'name="imageFile"' in content_disposition:
                image_bytes = part.content  # ✅ Extract raw image bytes

        # 3. Validate input data
        if not customer_name:
            logger.error("❌ Customer name missing")
            return {"statusCode": 400, "body": json.dumps({"error": "Customer name is required"})}

        if not json_data:
            logger.error("❌ JSON data missing")
            return {"statusCode": 400, "body": json.dumps({"error": "No JSON data provided"})}

        logger.info(f"✅ Processing request for customer: {customer_name}")

        # 4. Process Excel File
        services = json_data.get('Groups', {}).get('Services', [])
        
        # Prepare data for Excel
        excel_data = {
            'Region': [],
            'Service': [],
            'Monthly ($)': [],
            'First 12 Month Total ($)': [],
            'Config Summary': []
        }

        for service in services:
            region = service.get('Region', 'N/A')
            service_name = service['Service Name']
            monthly_cost = f"${float(service['Service Cost']['monthly']):,.2f}"
            yearly_cost = f"${float(service['Service Cost']['monthly']) * 12:,.2f}"

            detail = ", ".join([f"{k}: {v}" for k, v in service['Properties'].items()])
            excel_data['Region'].append(region)
            excel_data['Service'].append(service_name)
            excel_data['Monthly ($)'].append(monthly_cost)
            excel_data['First 12 Month Total ($)'].append(yearly_cost)
            excel_data['Config Summary'].append(detail)

        df = pd.DataFrame(excel_data)
        output = BytesIO()

        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='EST', index=False)

            workbook = writer.book
            worksheet = writer.sheets['EST']

            # ✅ Format header (yellow background)
            yellow_format = workbook.add_format({
                'border': 1,
                'align': 'center',
                'valign': 'vcenter',
                'font_name': 'Arial',
                'font_size': 11,
                'bg_color': '#FFFF00',
                'bold': True
            })

            # ✅ Apply header formatting
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, yellow_format)

            # ✅ Adjust column width
            worksheet.set_column('A:A', 20)
            worksheet.set_column('B:B', 25)
            worksheet.set_column('C:C', 15)
            worksheet.set_column('D:D', 20)
            worksheet.set_column('E:E', 90)

            # 5. ✅ Insert Image (Only This Part Was Updated)
            if image_bytes:
                try:
                    logger.info("🔹 Processing image from multipart/form-data")

                    # Convert binary data into BytesIO stream
                    image_stream = BytesIO(image_bytes)

                    # Insert the image into Excel (bắt đầu từ hàng dưới bảng dữ liệu)
                    last_data_row = len(df) + 2  # Chèn ảnh ở vị trí cách bảng dữ liệu 2 hàng
                    worksheet.insert_image(last_data_row, 0, "image.png", {'image_data': image_stream})

                    logger.info("✅ Image successfully inserted into Excel")

                except Exception as img_error:
                    logger.error("❌ Image processing error", exc_info=True)
                    print(f"❌ Error processing image: {img_error}")

        output.seek(0)

        # 6. Upload to S3
        file_uuid = str(uuid.uuid4())
        safe_customer_name = "".join(c for c in customer_name if c.isalnum() or c in (' ', '_')).strip().replace(" ", "_")
        s3_key = f"{safe_customer_name}_{datetime.utcnow().isoformat()}.xlsx"

        s3_client.upload_fileobj(output, S3_BUCKET, s3_key)
        logger.info(f"✅ File uploaded to S3: {s3_key}")

        # 7. Generate pre-signed URL for download
        presigned_url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": S3_BUCKET, "Key": s3_key}, ExpiresIn=3600
        )

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Success", "file_url": presigned_url})
        }

    except Exception as e:
        logger.error("❌ Unhandled exception", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
