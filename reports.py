from flask import Blueprint, render_template, send_file, jsonify
from io import BytesIO
from datetime import datetime
from app import db, Client, User

reports_bp = Blueprint('reports', __name__, template_folder='templates')

@reports_bp.route('/report/<int:client_id>', methods=['GET'])
def report_preview(client_id):
    """Generate a preview of the client report."""
    client = Client.query.get_or_404(client_id)
    user = User.query.get(client.created_by)
    report_data = {
        "Client Name": client.client_name,
        "Started On": client.contract_date.strftime('%Y-%m-%d'),
        "Status/Completed On": client.deadline.strftime('%Y-%m-%d') if client.status == "Completed Contract" else client.status,
        "Total Earning": f"{client.price} {client.currency}",
        "Total Hours Worked": client.hours_worked if client.billing_type == "hourly" else "N/A",
        "Upwork Account": client.upwork_account,
        "Created By": user.username if user else "Unknown",
        "Progress": client.progress,
        "Description": client.description,
    }
    return render_template('report_preview.html', report_data=report_data)

@reports_bp.route('/report/download/<int:client_id>', methods=['GET'])
def report_download(client_id):
    """Generate and download a report as a file."""
    client = Client.query.get_or_404(client_id)
    user = User.query.get(client.created_by)
    # Generate the report as plain text
    report_content = f"""
    Client Report
    -------------
    Client Name: {client.client_name}
    Started On: {client.contract_date.strftime('%Y-%m-%d')}
    Status/Completed On: {client.deadline.strftime('%Y-%m-%d') if client.status == "Completed Contract" else client.status}
    Total Earning: {client.price} {client.currency}
    Total Hours Worked: {client.hours_worked if client.billing_type == "hourly" else "N/A"}
    Upwork Account: {client.upwork_account}
    Created By: {user.username if user else "Unknown"}
    Progress: {client.progress}
    Description: {client.description}
    """
    # Convert to a downloadable file
    report_file = BytesIO()
    report_file.write(report_content.encode('utf-8'))
    report_file.seek(0)
    return send_file(
        report_file,
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"client_report_{client.client_no}.txt"
    )
