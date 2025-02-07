from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
from io import BytesIO
from reportlab.pdfgen import canvas
import requests
import os

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Configurations for SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///clients.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Set timezone to Pakistan Standard Time (PST)
pst = pytz.timezone('Asia/Karachi')
# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_no = db.Column(db.Integer, unique=True, nullable=False)
    client_name = db.Column(db.String(100), nullable=False)
    contract_date = db.Column(db.DateTime, nullable=False)
    deadline = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    progress = db.Column(db.String(100), nullable=False)
    upwork_account = db.Column(db.String(50), nullable=False)
    billing_type = db.Column(db.String(20), nullable=False)  # 'project' or 'hourly'
    price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), nullable=False)
    hours_worked = db.Column(db.Float, default=0)  # For hourly-based clients only
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pst))

class Revision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    change_date = db.Column(db.DateTime, default=lambda: datetime.now(pst))
    changes = db.Column(db.Text, nullable=False)

# @app.route('/')
# def home():
#     if 'user_id' in session:
#         clients = Client.query.order_by(Client.client_no).all()
#         finances = Finance.query.all()  # Fetch finance data from the database
#         partner_balances = PartnerBalance.query.all()
#         return render_template('dashboard.html', clients=clients, partner_balances=partner_balances, finances=finances, User=User)
#     return redirect(url_for('login'))

# @app.route('/')
# def home():
#     if 'user_id' in session:
#         clients = Client.query.order_by(Client.client_no).all()
#         finances = Finance.query.all()
#         partners = PartnerBalance.query.all()  # Fetch all partners and their balances
#         return render_template(
#             'dashboard.html',
#             clients=clients,
#             finances=finances,
#             partners=partners,
#             User=User
#         )
#     return redirect(url_for('login'))

@app.route('/')
def home():
    if 'user_id' in session:
        clients = Client.query.order_by(Client.client_no).all()
        finances = Finance.query.order_by(Finance.date_added.desc()).all()
        partner_balances = get_partner_balances()  # Compute balances dynamically

        return render_template(
            'dashboard.html',
            clients=clients,
            finances=finances,
            partner_balances=partner_balances,  # Use computed balances instead of stored ones
            User=User
        )
    return redirect(url_for('login'))



@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('home'))
        return 'Invalid Credentials'
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

@app.route('/add_client', methods=['GET', 'POST'])
def add_client():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        client_name = request.form['client_name']
        status = request.form['status']
        description = request.form['description']
        upwork_account = request.form['upwork_account']
        if upwork_account == 'Other':
            upwork_account = request.form['upwork_account_other']

        # Validate fields based on status
        if status in ["Active", "Required Critical Attention", "Completed Contract"]:
            # Contract date and deadline are required for these statuses
            try:
                contract_date = datetime.strptime(request.form['contract_date'], '%Y-%m-%d').replace(tzinfo=pytz.utc)
                deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%d').replace(tzinfo=pytz.utc)

                # Ensure deadline is not in the past
                current_time = datetime.now(pst).astimezone(pytz.utc)
                if deadline < current_time:
                    return "Deadline cannot be in the past. Please choose a valid date."
            except ValueError:
                return "Please provide valid dates for Contract Date and Deadline."

            progress = request.form['progress']
            billing_type = request.form['billing_type']
            price = float(request.form['price'])
            currency = request.form['currency']
        elif status in ["Under Discussion", "Contract Awaiting"]:
            # Only allow client name, description, and upwork account to be set
            contract_date = None
            deadline = None
            progress = ""
            billing_type = ""
            price = 0.0
            currency = ""
        else:
            return "Invalid client status. Please select a valid status."

        # Automatically assign the next client number
        max_client_no = db.session.query(db.func.max(Client.client_no)).scalar() or 0
        new_client_no = max_client_no + 1

        new_client = Client(
            client_no=new_client_no,
            client_name=client_name,
            contract_date=contract_date,
            deadline=deadline,
            status=status,
            description=description,
            progress=progress,
            upwork_account=upwork_account,
            billing_type=billing_type,
            price=price,
            currency=currency,
            created_by=session['user_id']
        )
        db.session.add(new_client)
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('add_client.html')


@app.route('/edit_client/<int:client_id>', methods=['GET', 'POST'])
def edit_client(client_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    client = Client.query.get_or_404(client_id)
    if request.method == 'POST':
        changes = []
        status = request.form['status']

        # Validate fields based on status
        if status in ["Active", "Required Critical Attention", "Completed Contract"]:
            # Update contract date
            if client.contract_date.replace(tzinfo=pytz.utc) != datetime.strptime(request.form['contract_date'], '%Y-%m-%d').replace(tzinfo=pytz.utc):
                changes.append(f"Contract Date changed from {client.contract_date.strftime('%Y-%m-%d')} to {request.form['contract_date']}")
                client.contract_date = datetime.strptime(request.form['contract_date'], '%Y-%m-%d').replace(tzinfo=pytz.utc)

            # Update deadline
            if client.deadline.replace(tzinfo=pytz.utc) != datetime.strptime(request.form['deadline'], '%Y-%m-%d').replace(tzinfo=pytz.utc):
                new_deadline = datetime.strptime(request.form['deadline'], '%Y-%m-%d').replace(tzinfo=pytz.utc)
                current_time = datetime.now(pst).astimezone(pytz.utc)
                if new_deadline < current_time:
                    return "Deadline cannot be in the past. Please choose a valid date."
                changes.append(f"Deadline changed from {client.deadline.strftime('%Y-%m-%d')} to {request.form['deadline']}")
                client.deadline = new_deadline

            # Update progress
            if client.progress != request.form['progress']:
                changes.append(f"Progress changed from {client.progress} to {request.form['progress']}")
                client.progress = request.form['progress']

            # Update billing type
            billing_type = request.form.get('billing_type', client.billing_type)
            if client.billing_type != billing_type:
                changes.append(f"Billing Type changed from {client.billing_type} to {billing_type}")
                client.billing_type = billing_type

            # Update price
            price = float(request.form.get('price', client.price))
            if client.price != price:
                changes.append(f"Price changed from {client.price} to {price}")
                client.price = price

            # Update currency
            currency = request.form.get('currency', client.currency)
            if client.currency != currency:
                changes.append(f"Currency changed from {client.currency} to {currency}")
                client.currency = currency

            # Update hours worked for hourly clients
            if client.billing_type == 'hourly':
                additional_hours = float(request.form.get('hours_worked', 0))
                if additional_hours > 0:
                    new_total_hours = client.hours_worked + additional_hours
                    changes.append(f"Hours Worked updated from {client.hours_worked} to {new_total_hours}")
                    client.hours_worked = new_total_hours

        elif status in ["Under Discussion", "Contract Awaiting"]:
            # Only allow client name, description, and upwork account to be updated
            if client.client_name != request.form['client_name']:
                changes.append(f"Client Name changed from {client.client_name} to {request.form['client_name']}")
                client.client_name = request.form['client_name']

            if client.description != request.form['description']:
                changes.append("Description changed")
                client.description = request.form['description']

            upwork_account = request.form.get('upwork_account', client.upwork_account)
            if upwork_account == 'Other':
                upwork_account = request.form.get('upwork_account_other', client.upwork_account)
            if client.upwork_account != upwork_account:
                changes.append(f"Upwork Account changed from {client.upwork_account} to {upwork_account}")
                client.upwork_account = upwork_account
        else:
            return "Invalid status value. Please select a valid status."

        # Update status
        if client.status != status:
            changes.append(f"Status changed from {client.status} to {status}")
            client.status = status

        # Save changes and create a revision
        if changes:
            revision = Revision(client_id=client.id, changed_by=session['user_id'], changes='; '.join(changes))
            db.session.add(revision)

        db.session.commit()
        return redirect(url_for('home'))
    return render_template('edit_client.html', client=client)



@app.route('/revisions/<int:client_id>')
def revisions(client_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    # Fetch revisions for the given client_id
    revisions = Revision.query.filter_by(client_id=client_id).all()
    
    return render_template('revisions.html', revisions=revisions, User=User)

@app.route('/reports/report/<int:client_id>', methods=['GET'])
def report_preview(client_id):
    client = Client.query.get_or_404(client_id)
    user = User.query.get(client.created_by)
    
    if client.billing_type == "hourly":
        # For hourly projects, calculate total earning based on hours worked
        total_earning = client.hours_worked * client.price
    elif client.status in ["Active", "Required Critical Attention"]:
        # For project-based contracts in progress, show "Expected Earning"
        total_earning = f"Expected Earning: {client.price} {client.currency}"
    elif client.status in ["Completed Contract", "Closed"]:
        # For completed project-based contracts, total earning is the price
        total_earning = f"{client.price} {client.currency}"
    else:
        total_earning = "N/A"
    
    report_data = {
        "Client ID": client.id,
        "Client Name": client.client_name,
        "Started On": client.contract_date.strftime('%Y-%m-%d'),
        "Status/Completed On": client.deadline.strftime('%Y-%m-%d') if client.status == "Completed Contract" else client.status,
        "Total Earning": total_earning,
        "Total Hours Worked": client.hours_worked if client.billing_type == "hourly" else "N/A",
        "Upwork Account": client.upwork_account,
        "Created By": user.username if user else "Unknown",
        "Progress": client.progress,
        "Description": client.description,
    }
    return render_template('report_preview.html', report_data=report_data)


@app.route('/reports/report/download/<int:client_id>', methods=['GET'])
def report_download(client_id):
    client = Client.query.get_or_404(client_id)
    user = User.query.get(client.created_by)
    
    if client.billing_type == "hourly":
        total_earning = client.hours_worked * client.price
    elif client.status in ["Active", "Required Critical Attention"]:
        total_earning = f"Expected Earning: {client.price} {client.currency}"
    elif client.status in ["Completed Contract", "Closed"]:
        total_earning = f"{client.price} {client.currency}"
    else:
        total_earning = "N/A"

    # Create a PDF in memory
    report_file = BytesIO()
    pdf = canvas.Canvas(report_file)
    pdf.drawString(100, 800, "Client Report")
    pdf.drawString(100, 780, f"Client Name: {client.client_name}")
    pdf.drawString(100, 760, f"Started On: {client.contract_date.strftime('%Y-%m-%d')}")
    pdf.drawString(100, 740, f"Status/Completed On: {client.deadline.strftime('%Y-%m-%d') if client.status == 'Completed Contract' else client.status}")
    pdf.drawString(100, 720, f"Total Earning: {total_earning}")
    pdf.drawString(100, 700, f"Total Hours Worked: {client.hours_worked if client.billing_type == 'hourly' else 'N/A'}")
    pdf.drawString(100, 680, f"Upwork Account: {client.upwork_account}")
    pdf.drawString(100, 660, f"Created By: {user.username if user else 'Unknown'}")
    pdf.drawString(100, 640, f"Progress: {client.progress}")
    pdf.drawString(100, 620, f"Description: {client.description}")
    pdf.save()

    # Prepare the file for download
    report_file.seek(0)
    return send_file(
        report_file,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"client_report_{client.client_no}.pdf"
    )


##########################################################################################
############################# Finance Management System ##################################
##########################################################################################


class Finance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    added_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), nullable=False)
    purpose = db.Column(db.String(255), nullable=False)
    date_added = db.Column(db.DateTime, default=lambda: datetime.now(pst))
    recipient = db.Column(db.String(100), nullable=True)
    paid_by = db.Column(db.String(100), nullable=False)
    settled = db.Column(db.Boolean, default=False)
    transaction_type = db.Column(db.String(10), nullable=False)  # "debit" or "credit"
    debit_type = db.Column(db.String(20), nullable=True)  # "expense" or "partner_payment"
    partner_paid_to = db.Column(db.String(100), nullable=True)  # For partner payments

class FinanceRevision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    finance_id = db.Column(db.Integer, db.ForeignKey('finance.id'), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    change_date = db.Column(db.DateTime, default=lambda: datetime.now(pst))
    changes = db.Column(db.Text, nullable=False)

class PartnerBalance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    partner_name = db.Column(db.String(100), unique=True, nullable=False)

# ------------------------- Helper Functions -------------------------

def get_partner_balances():
    """Compute partner balances dynamically from finance records."""
    partners = {p.partner_name: 0.0 for p in PartnerBalance.query.all()}  

    for finance in Finance.query.all():
        if finance.transaction_type == "credit":
            for partner in partners:
                partners[partner] += finance.amount / len(partners)

        elif finance.transaction_type == "debit":
            if finance.debit_type == "partner_payment" and finance.partner_paid_to:
                partners[finance.partner_paid_to] -= finance.amount

            elif finance.debit_type == "expense":
                num_partners = len(partners)
                share = finance.amount / num_partners
                for partner in partners:
                    if partner == finance.paid_by:
                        partners[partner] -= (finance.amount - share)
                    else:
                        partners[partner] -= share

    return partners

# ------------------------- Routes -------------------------

@app.route('/finance/add', methods=['GET', 'POST'])
def add_finance():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        transaction_type = request.form['transaction_type']
        amount = float(request.form['amount'])
        currency = request.form['currency']
        purpose = request.form['purpose']
        recipient = request.form.get('recipient')
        debit_type = request.form.get('debit_type', None)
        partner_paid_to = request.form.get('partner_paid_to', None)
        paid_by = request.form['paid_by']

        if transaction_type == 'credit':
            new_finance = Finance(
                added_by=session['user_id'],
                amount=amount,
                currency=currency,
                purpose=purpose,
                recipient=recipient,
                paid_by=paid_by,
                transaction_type=transaction_type
            )
            db.session.add(new_finance)

        elif transaction_type == 'debit':
            if debit_type == 'partner_payment':
                partner = PartnerBalance.query.filter(
                    PartnerBalance.partner_name.ilike(partner_paid_to)
                ).first()

                if not partner:
                    flash(f"Error: Partner '{partner_paid_to}' does not exist.", "danger")
                    return redirect(url_for('add_finance'))

                new_finance = Finance(
                    added_by=session['user_id'],
                    amount=amount,
                    currency=currency,
                    purpose=purpose,
                    recipient=recipient,
                    paid_by=paid_by,
                    transaction_type=transaction_type,
                    debit_type=debit_type,
                    partner_paid_to=partner_paid_to
                )
                db.session.add(new_finance)

            elif debit_type == 'expense':
                new_finance = Finance(
                    added_by=session['user_id'],
                    amount=amount,
                    currency=currency,
                    purpose=purpose,
                    recipient=recipient,
                    paid_by=paid_by,
                    transaction_type=transaction_type,
                    debit_type=debit_type
                )
                db.session.add(new_finance)
            else:
                flash("Error: Debit type is required for debit transactions.", "danger")
                return redirect(url_for('add_finance'))

        db.session.commit()
        flash("Finance record added successfully.", "success")
        return redirect(url_for('home'))

    partners = PartnerBalance.query.all()
    return render_template('add_finance.html', partners=partners)

@app.route('/finance/delete/<int:finance_id>', methods=['POST'])
def delete_finance(finance_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    finance_entry = Finance.query.get_or_404(finance_id)

    db.session.delete(finance_entry)
    db.session.commit()

    flash("Finance record deleted successfully and balances updated.", "success")
    return redirect(url_for('home'))

# Initialize the database and seed default partner balances
def initialize_partner_balances():
    """Populate PartnerBalance table with default partners if empty."""
    if PartnerBalance.query.count() == 0:
        default_partners = [
            PartnerBalance(partner_name="Zain"),
            PartnerBalance(partner_name="Hammad"),
            PartnerBalance(partner_name="Rizwan"),
        ]
        db.session.add_all(default_partners)
        db.session.commit()
        print("PartnerBalance table initialized with default partners.")

# Call this function when the application starts
with app.app_context():
    db.create_all()  # Create tables if they don't exist
    initialize_partner_balances()


# @app.route('/finance/dashboard')
# def finance_dashboard():
#     if 'user_id' not in session:
#         return redirect(url_for('login'))

#     finance_records = Finance.query.order_by(Finance.date_added.desc()).all()
#     partner_balances = get_partner_balances()

#     return render_template(
#         'finance_dashboard.html',
#         finance_records=finance_records,
#         partner_balances=partner_balances
#     )




##############################################################################################
###############################################################################################
###########################################################################################

# class Finance(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     added_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
#     amount = db.Column(db.Float, nullable=False)
#     currency = db.Column(db.String(10), nullable=False)
#     purpose = db.Column(db.String(255), nullable=False)
#     date_added = db.Column(db.DateTime, default=lambda: datetime.now(pst))
#     recipient = db.Column(db.String(100), nullable=True)  # For partner payments
#     paid_by = db.Column(db.String(100), nullable=False)
#     settled = db.Column(db.Boolean, default=False)
#     transaction_type = db.Column(db.String(10), nullable=False)  # "debit" or "credit"
#     debit_type = db.Column(db.String(20), nullable=True)  # "expense" or "partner_payment"
#     partner_paid_to = db.Column(db.String(100), nullable=True)  # For partner payments
#     balance = db.Column(db.Float, nullable=False, default=0.0)

# class PartnerBalance(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     partner_name = db.Column(db.String(100), unique=True, nullable=False)
#     balance = db.Column(db.Float, nullable=False, default=0.0)

# class FinanceRevision(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     finance_id = db.Column(db.Integer, db.ForeignKey('finance.id'), nullable=False)
#     changed_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
#     change_date = db.Column(db.DateTime, default=lambda: datetime.now(pst))
#     changes = db.Column(db.Text, nullable=False)

# @app.route('/finance/add', methods=['GET', 'POST'])
# def add_finance():
#     if 'user_id' not in session:
#         return redirect(url_for('login'))

#     if request.method == 'POST':
#         # Fetch the last balance
#         last_finance = Finance.query.order_by(Finance.id.desc()).first()
#         last_balance = last_finance.balance if last_finance else 0.0

#         # Fetch form data
#         transaction_type = request.form['transaction_type']
#         amount = float(request.form['amount'])
#         currency = request.form['currency']
#         purpose = request.form['purpose']
#         recipient = request.form.get('recipient')  # This can be None for partner payments
#         debit_type = request.form.get('debit_type', None)  # 'expense' or 'partner_payment'
#         partner_paid_to = request.form.get('partner_paid_to', None)
#         paid_by = request.form['paid_by']

#         # Handle credit (income) logic
#         if transaction_type == 'credit':
#             # Distribute equally among partners
#             for partner in PartnerBalance.query.all():
#                 partner.balance += amount / 3
#                 db.session.add(partner)
#             new_balance = last_balance + amount

#         # Handle debit logic
#         elif transaction_type == 'debit':
#             if debit_type == 'partner_payment':
#                 # Handle partner payment logic
#                 partner_paid_to = partner_paid_to.strip() if partner_paid_to else None
#                 partner = PartnerBalance.query.filter(
#                     PartnerBalance.partner_name.ilike(partner_paid_to)
#                 ).first()

#                 if not partner:
#                     flash(f"Error: Partner '{partner_paid_to}' does not exist.", "danger")
#                     return redirect(url_for('add_finance'))

#                 if partner.balance < amount:
#                     flash(f"Error: Insufficient balance for {partner_paid_to}. Maximum available: {partner.balance:.2f}", "danger")
#                     return redirect(url_for('add_finance'))

#                 partner.balance -= amount
#                 db.session.add(partner)
#                 new_balance = last_balance - amount

#             elif debit_type == 'expense':
#                 # Get all partners
#                 all_partners = PartnerBalance.query.all()
#                 total_partners = len(all_partners)
                
#                 # Calculate the equal share of the expense for each partner
#                 share = amount / total_partners
                
#                 for partner in all_partners:
#                     if partner.partner_name == paid_by:
#                         # The paying partner bears only their share of the expense (reimbursed for the rest)
#                         partner.balance -= (amount - share)
#                     else:
#                         # Other partners bear their equal share
#                         partner.balance -= share
                    
#                     db.session.add(partner)

#                 # Update the total balance
#                 new_balance = last_balance - amount
#             else:
#                 flash("Error: Debit type is required for debit transactions.", "danger")
#                 return redirect(url_for('add_finance'))
#         else:
#             flash("Error: Invalid transaction type.", "danger")
#             return redirect(url_for('add_finance'))

#         # Create the finance record
#         finance = Finance(
#             added_by=session['user_id'],
#             amount=amount,
#             currency=currency,
#             purpose=purpose,
#             recipient=recipient,
#             paid_by=paid_by,
#             transaction_type=transaction_type,
#             debit_type=debit_type,
#             partner_paid_to=partner_paid_to,
#             balance=new_balance,
#         )
#         db.session.add(finance)
#         db.session.commit()

#         # Send Slack notification
#         if SLACK_WEBHOOK_URL:
#             try:
#                 slack_message = {
#                     "blocks": [
#                         {
#                             "type": "header",
#                             "text": {
#                                 "type": "plain_text",
#                                 "text": ":moneybag: New Finance Entry Added! :moneybag:",
#                                 "emoji": True
#                             }
#                         },
#                         {
#                             "type": "section",
#                             "fields": [
#                                 {
#                                     "type": "mrkdwn",
#                                     "text": f"*Added By:* {User.query.get(session['user_id']).username}"
#                                 },
#                                 {
#                                     "type": "mrkdwn",
#                                     "text": f"*Amount:* {amount} {currency}"
#                                 },
#                                 {
#                                     "type": "mrkdwn",
#                                     "text": f"*Transaction Type:* {transaction_type.capitalize()}"
#                                 },
#                                 {
#                                     "type": "mrkdwn",
#                                     "text": f"*Purpose:* {purpose}"
#                                 },
#                                 {
#                                     "type": "mrkdwn",
#                                     "text": f"*Paid By:* {paid_by}"
#                                 }
#                             ]
#                         },
#                         {
#                             "type": "divider"
#                         },
#                         {
#                             "type": "context",
#                             "elements": [
#                                 {
#                                     "type": "mrkdwn",
#                                     "text": "For more details, visit the *Finance Dashboard* in your app."
#                                 }
#                             ]
#                         }
#                     ]
#                 }

#                 response = requests.post(SLACK_WEBHOOK_URL, json=slack_message)
#                 if response.status_code != 200:
#                     app.logger.error(f"Slack notification failed: {response.text}")
#             except Exception as e:
#                 app.logger.error(f"Error sending Slack notification: {str(e)}")

#         flash("Finance record added successfully.", "success")
#         return redirect(url_for('home'))

#     partners = PartnerBalance.query.all()
#     return render_template('add_finance.html', partners=partners)

# @app.route('/finance/delete/<int:finance_id>', methods=['POST'])
# def delete_finance(finance_id):
#     if 'user_id' not in session:
#         return redirect(url_for('login'))

#     finance_entry = Finance.query.get_or_404(finance_id)
#     # Fetch all partners
#     partners = PartnerBalance.query.all()

#     # Revert balances based on the transaction type and debit type
#     if finance_entry.transaction_type == 'credit':
#         # Revert distributed credit amount
#         for partner in partners:
#             partner.balance -= finance_entry.amount / len(partners)
#             db.session.add(partner)
#     elif finance_entry.transaction_type == 'debit':
#         if finance_entry.debit_type == 'expense':
#             if finance_entry.settled:
#                 # Revert settled debit amount equally
#                 for partner in partners:
#                     partner.balance += finance_entry.amount / len(partners)
#                     db.session.add(partner)
#             else:
#                 # Revert unsettled debit amount (2/3 from others, none from paid_by)
#                 for partner in partners:
#                     if partner.partner_name != finance_entry.paid_by:
#                         partner.balance += (2 / 3) * finance_entry.amount / (len(partners) - 1)
#                         db.session.add(partner)
#         elif finance_entry.debit_type == 'partner_payment':
#             # Revert partner payment
#             partner = PartnerBalance.query.filter_by(partner_name=finance_entry.partner_paid_to).first()
#             if partner:
#                 partner.balance += finance_entry.amount
#                 db.session.add(partner)

#     # Delete the finance entry
#     db.session.delete(finance_entry)
#     db.session.commit()

#     flash("Finance record deleted successfully and balances reverted.", "success")
#     return redirect(url_for('home'))


# Create predefined users
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Add predefined users
        if not User.query.filter_by(username='zain').first():
            user1 = User(username='zain', password=generate_password_hash('zain-ul.abideen@i2zone.com'))
            user2 = User(username='hammad', password=generate_password_hash('hammad.yousaf@i2zone.com'))
            user3 = User(username='rizwan', password=generate_password_hash('rizwan.butt@i2zone.com'))
            db.session.add_all([user1, user2, user3])
            db.session.commit()
    app.run(host='0.0.0.0', port=5000, debug=True)



# from app import db, PartnerBalance

# # Fetch all partners
# partners = PartnerBalance.query.all()

# # Print their details
# for partner in partners:
#     print(f"Partner: {partner.partner_name}, Balance: {partner.balance}")


# partners = [
#     PartnerBalance(partner_name="Zain", balance=0.0),
#     PartnerBalance(partner_name="Hammad", balance=0.0),
#     PartnerBalance(partner_name="Rizwan", balance=0.0),
# ]

# db.session.add_all(partners)
# db.session.commit()

# print("PartnerBalance table seeded successfully!")
