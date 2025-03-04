import json
import uuid
from datetime import datetime
from io import BytesIO
import pandas as pd
import xlsxwriter
import boto3
import requests
from flask import request, send_file, session

# Giả sử bạn đã cấu hình các giá trị cần thiết từ môi trường hoặc config
S3_BUCKET = "my-excel-files"  # Tên S3 bucket của bạn
DYNAMODB_TABLE = "ExcelFilesMetadata"  # Tên DynamoDB table của bạn

# Khởi tạo client S3 và DynamoDB resource
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
metadata_table = dynamodb.Table(DYNAMODB_TABLE)

@app.route('/generate_excel', methods=['POST'])
def generate_excel():
    # Lấy user_email từ session hoặc từ thông tin xác thực đã được xử lý (giả sử có trong session)
    try:
        user_email = request.environ['apigateway.event']["requestContext"]["authorizer"]["email"]
    except Exception as e:
        return json.dumps({"error": "User not authenticated"}), 401

    # Extract JSON file and image file từ request
    json_file = request.files.get('jsonFile')
    image_file = request.files.get('imageFile')

    # Read JSON data
    json_data = json_file.read()
    data = json.loads(json_data)

    # Process JSON data: lấy thông tin các dịch vụ
    services = data.get('Groups', {}).get('Services', [])
    
    # Prepare data for Excel without the Description column
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
        
        excel_data['Region'].append(region)
        excel_data['Service'].append(service_name)
        excel_data['Monthly ($)'].append(monthly_cost)
        excel_data['First 12 Month Total ($)'].append(yearly_cost)
        detail = ", ".join([f"{k}: {v}" for k, v in service.get('Properties', {}).items()])
        excel_data['Config Summary'].append(detail)
    
    # Create DataFrame
    df = pd.DataFrame(excel_data)
    
    # Calculate totals
    total_monthly = f"${sum([float(x.replace('$', '').replace(',', '')) for x in df['Monthly ($)']]):.2f}"
    total_12_month = f"${sum([float(x.replace('$', '').replace(',', '')) for x in df['First 12 Month Total ($)']]):.2f}"
    
    total_row = ['', '', total_monthly, total_12_month, '']
    calculator_row = ['', '', '', '', '']
    df.loc[len(df)] = total_row
    df.loc[len(df)] = calculator_row
    
    # Create Excel file in memory
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
            'font_size': 11,
            'text_wrap': True
        })
        yellow_format = workbook.add_format({
            'border': 1,
            'align': 'center',
            'valign': 'vcenter',
            'font_name': 'Arial',
            'font_size': 11,
            'bg_color': '#FFFF00',
            'bold': True
        })
        
        # Write header row with yellow background
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, yellow_format)

        data_rows = len(df) - 2
        for row in range(data_rows):
            for col in range(len(df.columns)):
                cell_value = df.iloc[row][df.columns[col]]
                worksheet.write(row + 1, col, cell_value, wrap_format)
                
        worksheet.set_row(0, 20)
        for row in range(1, data_rows + 1):
            worksheet.set_row(row, 70)
        total_row_index = data_rows + 1
        calculator_row_index = data_rows + 2
        worksheet.set_row(total_row_index, 20)
        worksheet.set_row(calculator_row_index, 20)
        
        worksheet.set_column('A:A', 20)
        worksheet.set_column('B:B', 25)
        worksheet.set_column('C:C', 15)
        worksheet.set_column('D:D', 20)
        worksheet.set_column('E:E', 90)
        
        worksheet.merge_range(total_row_index, 0, total_row_index, 1, 'Total', yellow_format)
        worksheet.write(total_row_index, 2, total_monthly, wrap_format)
        worksheet.write(total_row_index, 3, total_12_month, wrap_format)
        
        worksheet.merge_range(calculator_row_index, 0, calculator_row_index, 1, 'Calculator', yellow_format)
        worksheet.merge_range(calculator_row_index, 2, calculator_row_index, 3, '', wrap_format)
        
        # Insert image if provided
        if image_file:
            image_path = image_file.filename
            image_file.save(image_path)
            worksheet.insert_image(data_rows + 4, 0, image_path)
        
        # Tạo sheet "Questions and Answers"
        question_sheet = workbook.add_worksheet('Questions and Answers')
        qa_header_format = workbook.add_format({
            'bg_color': '#FFFF00',
            'bold': True,
            'border': 1,
            'align': 'center',
            'valign': 'vcenter'
        })
        question_sheet.write('A1', 'Questions', qa_header_format)
        question_sheet.write('B1', 'Sample Answers', qa_header_format)
        question_sheet.set_column('A:A', 90)
        question_sheet.set_column('B:B', 90)
        question_sheet.set_row(0, 30)
        sample_questions = ["What is AWS?", "How does Lambda work?", "What is S3?"]
        sample_answers = ["AWS is Amazon Web Services.", "Lambda runs code without provisioning servers.", "S3 is scalable object storage."]
        for i, (question, answer) in enumerate(zip(sample_questions, sample_answers), start=1):
            question_sheet.write(i, 0, question)
            question_sheet.write(i, 1, answer)
            question_sheet.set_row(i, 30)
        
        for i in range(len(sample_questions) + 1):
            question_sheet.set_row(i, 30)
    
    output.seek(0)
    
    # Generate a unique filename, lưu trong thư mục theo user_email
    file_uuid = str(uuid.uuid4())
    s3_filename = f"{user_email}/{file_uuid}.xlsx"
    
    # Upload file Excel lên S3
    s3_client.upload_fileobj(output, S3_BUCKET, s3_filename)
    
    # Tạo metadata và lưu vào DynamoDB
    metadata_item = {
        'user_email': user_email,            # Partition key
        'file_id': file_uuid,          # Sort key (hoặc dùng timestamp)
        's3_key': s3_filename,
        's3_url': f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_filename}",
        'created_at': datetime.utcnow().isoformat() + "Z"
    }
    
    metadata_table.put_item(Item=metadata_item)
    
    # Tùy chọn: Nếu bạn muốn trả về URL tải file cho người dùng
    return json.dumps({
        "message": "Excel file generated and stored successfully",
        "file_url": metadata_item['s3_url']
    })
