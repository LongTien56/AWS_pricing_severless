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
        # 1. Lấy thông tin người dùng từ context của custom authorizer
        authorizer = event.get("requestContext", {}).get("authorizer", {})
        user_email = authorizer.get("lambda", {}).get("email")
        if not user_email:
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "User not authenticated"})
            }
        print(user_email)
        
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
        aws_calculator_url = None

        for part in multipart_data.parts:
            content_disposition = part.headers.get(b'Content-Disposition', b'').decode()

            if 'name="customerName"' in content_disposition:
                customer_name = part.text.strip()

            if 'name="jsonData"' in content_disposition:
                json_data = json.loads(part.text)

            if 'name="imageFile"' in content_disposition:
                image_bytes = part.content  # ✅ Extract raw image bytes

            if 'name="awsCalculatorUrl"' in content_disposition:
                aws_calculator_url = part.text.strip()
            
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
        # Calculate totals
        total_monthly = f"${sum([float(x.replace('$', '').replace(',', '')) for x in df['Monthly ($)']]):.2f}"
        total_12_month = f"${sum([float(x.replace('$', '').replace(',', '')) for x in df['First 12 Month Total ($)']]):.2f}"
        
        # Append the total and calculator rows
        total_row = ['', '', total_monthly, total_12_month, '']
        calculator_row = ['', '', '', '', '']
        
        df.loc[len(df)] = total_row
        df.loc[len(df)] = calculator_row

        output = BytesIO()

        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='EST', index=False)

            workbook = writer.book
            worksheet = writer.sheets['EST']

            wrap_format = workbook.add_format({
                'border': 1,
                'align': 'center',
                'valign': 'vcenter',
                'font_name': 'Arial',
                'font_size': 13,
                'text_wrap': True
            })
            # ✅ Format header (yellow background)
            yellow_format = workbook.add_format({
                'border': 1,
                'align': 'center',
                'valign': 'vcenter',
                'font_name': 'Arial',
                'font_size': 13,
                'bg_color': '#FFFF00',
                'bold': True
            })

            # ✅ Apply header formatting
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, yellow_format)

            # Write data rows and apply wrap format
            data_rows = len(df) - 2  # Number of data rows (excluding total and calculator)
            for row in range(data_rows):  # Write all data rows
                for col in range(len(df.columns)):
                    cell_value = df.iloc[row][df.columns[col]]
                    worksheet.write(row + 1, col, cell_value, wrap_format)

            # Set height for rows
            worksheet.set_row(0, 20)  # Header row
            for row in range(1, data_rows + 1):  # Data rows
                worksheet.set_row(row, 70)
            
            # Set total and calculator row heights
            total_row_index = data_rows + 1
            calculator_row_index = data_rows + 2
            worksheet.set_row(total_row_index, 20)
            worksheet.set_row(calculator_row_index, 20)

            # ✅ Adjust column width
            worksheet.set_column('A:A', 20)
            worksheet.set_column('B:B', 25)
            worksheet.set_column('C:C', 15)
            worksheet.set_column('D:D', 20)
            worksheet.set_column('E:E', 90)

            # Format Total row (merge first two columns)
            worksheet.merge_range(total_row_index, 0, total_row_index, 1, 'Total', yellow_format)
            worksheet.write(total_row_index, 2, total_monthly, wrap_format)
            worksheet.write(total_row_index, 3, total_12_month, wrap_format)

            # Format Calculator row (merge first two columns)
            worksheet.merge_range(calculator_row_index, 0, calculator_row_index, 1, 'Calculator', yellow_format)
            worksheet.merge_range(calculator_row_index, 2, calculator_row_index, 3, aws_calculator_url, wrap_format)


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

            # Create a new sheet for Questions and Sample Answers
            question_sheet = workbook.add_worksheet('Questions and Answers')

            # Define formats for the new sheet (header format only)
            qa_header_format = workbook.add_format({
                'bg_color': '#FFFF00',
                'bold': True,
                'border': 1,
                'align': 'center',
                'valign': 'vcenter'
            })

            # Write header with yellow background
            question_sheet.write('A1', 'Questions', qa_header_format)
            question_sheet.write('B1', 'Sample Answers', qa_header_format)

            # Set column widths and row heights
            question_sheet.set_column('A:A', 90)  # Questions column
            question_sheet.set_column('B:B', 90)  # Sample Answers column
            question_sheet.set_row(0, 30)  # Header row height

            # Sample data without yellow background
            sample_questions = ["What is AWS?", "How does Lambda work?", "What is S3?"]
            sample_answers = ["AWS is Amazon Web Services.", "Lambda allows you to run code without provisioning servers.", "S3 is a scalable storage service."]

            # Write sample data without yellow background
            for i, (question, answer) in enumerate(zip(sample_questions, sample_answers), start=1):
                question_sheet.write(i, 0, question)  # Write question
                question_sheet.write(i, 1, answer)  # Write sample answer
                question_sheet.set_row(i, 30)  # Set height for each row

            # Define a format for the border
            border_format = workbook.add_format({
                'border': 1,
                'align': 'center',
                'valign': 'vcenter'
            })

            # Apply borders around the header and the data range
            question_sheet.conditional_format(0, 0, 0, 1, {'type': 'no_blanks', 'format': qa_header_format})  # Only for the header row
            question_sheet.conditional_format(0, 0, len(sample_questions), 1, {'type': 'no_blanks', 'format': border_format})  # Add borders to the entire range including headers

            # Optional: You can set the height for all rows, if needed
            for i in range(len(sample_questions) + 1):  # +1 to include the header row
                question_sheet.set_row(i, 30)  # Set height for each row

        output.seek(0)

        # 6. Upload to S3
        file_uuid = str(uuid.uuid4())
        safe_customer_name = "".join(c for c in customer_name if c.isalnum() or c in (' ', '_')).strip().replace(" ", "_")
        s3_key = f"{user_email}/{safe_customer_name}_{datetime.utcnow().isoformat()}.xlsx"

        s3_client.upload_fileobj(output, S3_BUCKET, s3_key)
        logger.info(f"✅ File uploaded to S3: {s3_key}")

        # 7. Generate pre-signed URL for download
        presigned_url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": S3_BUCKET, "Key": s3_key}, ExpiresIn=3600
        )


        # 8. Lưu metadata vào DynamoDB
        metadata_item = {
            "user_email": user_email,
            "file_id": file_uuid,
            "customer_name": safe_customer_name,
            "s3_key": s3_key,
            "s3_url": f"{presigned_url}",
            "created_at": datetime.utcnow().isoformat() + "Z"
        }
        logger.info("Metadata item: %s", json.dumps(metadata_item))
        try:
            metadata_table.put_item(Item=metadata_item)
            logger.info("Uploaded metadata to DynamoDB")
        except Exception as ex:
            logger.error("Failed to put item in DynamoDB: %s", ex)
            raise


        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Success", "file_url": presigned_url})
        }

    except Exception as e:
        logger.error("❌ Unhandled exception", exc_info=True)
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
