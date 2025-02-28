from flask import Flask, request, send_file, render_template
import pandas as pd
import json
from io import BytesIO
from flask_cors import CORS

app = Flask(__name__)

CORS(app)

@app.route('/')
def upload_form():
    return render_template('home.html')

@app.route('/generate_excel', methods=['POST'])
def generate_excel():
    # Extract JSON file
    json_file = request.files.get('jsonFile')
    image_file = request.files.get('imageFile')

    # Read JSON data
    json_data = json_file.read()
    data = json.loads(json_data)

    # Process the JSON data
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
        
        # Prepare display values
        excel_data['Region'].append(region)
        excel_data['Service'].append(service_name)
        excel_data['Monthly ($)'].append(monthly_cost)
        excel_data['First 12 Month Total ($)'].append(yearly_cost)
        detail = ", ".join([f"{k}: {v}" for k, v in service['Properties'].items()])
        excel_data['Config Summary'].append(detail)
    
    # Create a DataFrame
    df = pd.DataFrame(excel_data)
    
    # Calculate totals
    total_monthly = f"${sum([float(x.replace('$', '').replace(',', '')) for x in df['Monthly ($)']]):.2f}"
    total_12_month = f"${sum([float(x.replace('$', '').replace(',', '')) for x in df['First 12 Month Total ($)']]):.2f}"
    
    # Append the total and calculator rows
    total_row = ['', '', total_monthly, total_12_month, '']
    calculator_row = ['', '', '', '', '']
    
    df.loc[len(df)] = total_row
    df.loc[len(df)] = calculator_row
    
    # Save to Excel
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        # Create the first sheet
        df.to_excel(writer, sheet_name='EST', index=False)
        
        # Access the workbook and worksheet for the first sheet
        workbook = writer.book
        worksheet = writer.sheets['EST']
        
        # Define formats for the first sheet
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
            'bold': True  # Making text bold
        })

        # Write the header row with yellow background
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
        
        # Set width for columns
        worksheet.set_column('A:A', 20)  # Region
        worksheet.set_column('B:B', 25)  # Service
        worksheet.set_column('C:C', 15)  # Monthly
        worksheet.set_column('D:D', 20)  # First 12 Month Total
        worksheet.set_column('E:E', 90)  # Config Summary

        # Format Total row (merge first two columns)
        worksheet.merge_range(total_row_index, 0, total_row_index, 1, 'Total', yellow_format)
        worksheet.write(total_row_index, 2, total_monthly, wrap_format)
        worksheet.write(total_row_index, 3, total_12_month, wrap_format)

        # Format Calculator row (merge first two columns)
        worksheet.merge_range(calculator_row_index, 0, calculator_row_index, 1, 'Calculator', yellow_format)
        worksheet.merge_range(calculator_row_index, 2, calculator_row_index, 3, '', wrap_format)

        # Insert the uploaded image below the table with a space
        if image_file:
            image_path = image_file.filename  # Get the file name
            image_file.save(image_path)  # Save the image temporarily
            # Insert image with one empty row below the last data row
            worksheet.insert_image(data_rows + 4, 0, image_path)  # Insert image at row data_rows + 4

        # Create a new sheet for Questions and Sample Answers
        # Create a new sheet for Questions and Sample Answers
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
    return send_file(output, download_name='aws_pricing.xlsx', as_attachment=True)

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
