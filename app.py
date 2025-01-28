from flask import Flask, render_template, request, redirect, url_for, session, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import pytz
from io import BytesIO

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

# Routes
@app.route('/')
def home():
    if 'user_id' in session:
        clients = Client.query.order_by(Client.client_no).all()
        return render_template('dashboard.html', clients=clients, User=User)
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
    report_data = {
        "Client ID": client.id,  # Include Client ID
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


@app.route('/reports/report/download/<int:client_id>', methods=['GET'])
def report_download(client_id):
    client = Client.query.get_or_404(client_id)
    user = User.query.get(client.created_by)
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
    report_file = BytesIO()
    report_file.write(report_content.encode('utf-8'))
    report_file.seek(0)
    return send_file(
        report_file,
        mimetype='text/plain',
        as_attachment=True,
        download_name=f"client_report_{client.client_no}.txt"
    )

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

