# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from google.cloud import bigquery
import pandas as pd
from datetime import datetime
from google.oauth2 import service_account
from domains import DOMAIN_CHOICES
from forms import ISVForm
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
import io
import base64
from matplotlib.figure import Figure
import textwrap
import numpy as np
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask import session, abort
import re

app = Flask(__name__)
app.secret_key = os.urandom(24)

# BigQuery client setup
credentials = service_account.Credentials.from_service_account_file('gbq_app_service_account.json')
project_id = 'wwbq-treasuredata'
client = bigquery.Client(credentials=credentials, project=project_id)
dataset_id = "GBQ"
table_id = "isv_data_store"
new_table_id = "ISV_Details"

# Decorator to check if user is logged in
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Decorator for admin-only routes
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            flash('Please log in to access this page', 'error')
            return redirect(url_for('login'))
        if session.get('user_role') != 'admin':
            return jsonify({
                'status': 'error',
                'message': 'You do not have permission to access this page. Admin role required.',
                'redirect': url_for('index')
            }), 403
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
@login_required
def index():
    # Get counts for dashboard
    counts_query = f"""
    SELECT
        COUNT(CASE WHEN status = 'in progress' THEN 1 END) as in_progress_count,
        COUNT(CASE WHEN status = 'Completed' THEN 1 END) as completed_count
    FROM `{dataset_id}.{new_table_id}`
    """
    counts_job = client.query(counts_query)
    counts_result = next(counts_job.result())

    # Get recent activities
    activities_query = f"""
    SELECT
        Tool_Name,
        status,
        created_at as updated_at
    FROM `{dataset_id}.{new_table_id}`
    ORDER BY created_at DESC
    LIMIT 5
    """
    activities_job = client.query(activities_query)
    recent_activities = activities_job.result()

    domain_chart = generate_domain_chart()
    quarter_chart = generate_quarter_chart()
    pie_chart = generate_pie_chart()
    line_chart_qtr = generate_qtr_growth_chart()
    hor_chart_dom = generate_top_domain_chart()
    total_domains = get_dist_domains_count()

    return render_template('index.html',
                        #    inactive_count=counts_result.inactive_count or 0,
                           in_progress_count=counts_result.in_progress_count or 0,
                           completed_count=counts_result.completed_count or 0,
                           recent_activities=recent_activities,
                           domain_count=len(DOMAIN_CHOICES) or 0,
                           domain_chart=domain_chart,
                           quarter_chart=quarter_chart,
                           pie_chart=pie_chart,
                           line_chart_qtr=line_chart_qtr,
                           hor_chart_dom=hor_chart_dom)



@app.route('/tracker')
@login_required
def tracker():
    # Get counts for dashboard
    counts_query = f"""
    SELECT
        COUNT(CASE WHEN status = 'not started' THEN 1 END) as inactive_count,
        COUNT(CASE WHEN status = 'on hold' THEN 1 END) as hold_count,
        COUNT(CASE WHEN status = 'in progress' THEN 1 END) as in_progress_count,
        COUNT(CASE WHEN status = 'Completed' THEN 1 END) as completed_count
    FROM `{dataset_id}.{new_table_id}`
    """
    counts_job = client.query(counts_query)
    counts_result = next(counts_job.result())

    # Get recent activities
    activities_query = f"""
    SELECT
        Tool_Name,
        status,
        created_at as updated_at
    FROM `{dataset_id}.{new_table_id}`
    ORDER BY created_at DESC
    LIMIT 5
    """
    activities_job = client.query(activities_query)
    recent_activities = activities_job.result()

    return render_template('tracker.html',
                           inactive_count=counts_result.inactive_count or 0,
                           hold_count=counts_result.hold_count or 0,
                           in_progress_count=counts_result.in_progress_count or 0,
                           completed_count=counts_result.completed_count or 0,
                           recent_activities=recent_activities)

@app.route('/check_isv_name', methods=['POST'])
def check_isv_name():
    try:
        isv_name = request.json.get('isv_name')

        # Get the maximum Sr_No
        max_srno_query = f"""
        SELECT MAX(Sr_No) as max_srno
        FROM `{dataset_id}.{new_table_id}`
        """
        max_srno_result = list(client.query(max_srno_query).result())[0]
        next_srno = (max_srno_result.max_srno or 0) + 1

        # Check if ISV exists
        exists_query = f"""
        SELECT COUNT(*) as count
        FROM `{dataset_id}.{new_table_id}`
        WHERE LOWER(Tool_Name) = LOWER('{isv_name}')
        """
        exists_result = list(client.query(exists_query).result())[0]

        return jsonify({
            'exists': exists_result.count > 0,
            'next_srno': next_srno
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/add_isv', methods=['GET', 'POST'])
@admin_required
def add_isv():
    form = ISVForm()
    if request.method == 'POST':
        if form.validate():
            try:
                # Get the maximum Sr_No
                max_srno_query = f"""
                SELECT MAX(Sr_No) as max_srno
                FROM `{dataset_id}.{new_table_id}`
                """
                max_srno_result = list(client.query(max_srno_query).result())[0]
                next_srno = (max_srno_result.max_srno or 0) + 1

                # Join multiple domains with plus
                domains = ' + '.join(form.domain.data) if isinstance(form.domain.data, list) else form.domain.data

                # Calculate Year, Quarter, and YearQuarter from start_date
                start_date = form.start_date.data
                year = start_date.year
                quarter_num = (start_date.month - 1) // 3 + 1
                quarter = f"Q{quarter_num}"
                year_quarter = f"FY{year}{quarter}"

                # Construct the INSERT query using standard SQL
                insert_query = f"""
                INSERT INTO `{dataset_id}.{new_table_id}` (
                    Sr_No, Tool_Name, Domain, Certification_Type, Version, Description,
                    Team_Members, Year, Quarter, YearQuarter, ISV_Start_Date,
                    POC, Status, Percentage, Comments, Assessment_Sheet,
                    Acceptance_Criteria_Sheet, IOL_Doc, Best_Practices_Doc, Summary_Doc1, Questions_Doc,
                    created_at
                    )
                VALUES (
                    {next_srno},
                    "{form.isv_name.data.replace('"', '""')}",
                    "{domains.replace('"', '""')}",
                    "{form.certification_type.data.replace('"', '""')}",
                    "{(form.version.data or '').replace('"', '""')}",
                    "{form.description.data.replace('"', '""')}",
                    "{form.team_members.data.replace('"', '""')}",
                    {year},
                    "{quarter}",
                    "{year_quarter}",
                    DATE("{start_date.strftime('%Y-%m-%d')}"),
                    "{(form.poc.data or '').replace('"', '""')}",
                    "{form.status.data.replace('"', '""')}",
                    {float(form.percentage.data) if form.percentage.data else 0.0},
                    "{(form.comments.data or '').replace('"', '""')}",
                    "{(form.assessment_sheet.data or '').replace('"', '""')}",
                    "{(form.acceptance_criteria_sheet.data or '').replace('"', '""')}",
                    "{(form.iol_doc.data or '').replace('"', '""')}",
                    "{(form.best_practices_doc.data or '').replace('"', '""')}",
                    "{(form.summary_doc1.data or '').replace('"', '""')}",
                    "{(form.questions_doc.data or '').replace('"', '""')}",
                    TIMESTAMP(FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S UTC', CURRENT_TIMESTAMP()))
                )
                """

                # Execute the insert query
                query_job = client.query(insert_query)
                query_job.result()  # Wait for the query to complete

                # Initialize tasks for the new ISV after successful insert
                initialize_isv_tasks(next_srno)

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': True,
                        'message': 'ISV successfully added!',
                        'redirect': url_for('current_isvs')
                    })
                else:
                    flash('ISV successfully added!', 'success')
                    return redirect(url_for('current_isvs'))

            except Exception as e:
                print("Exception:", str(e))
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': False,
                        'message': str(e)
                    }), 500
                else:
                    flash(f'Error: {str(e)}', 'error')
                    return render_template('add_isv.html', form=form)
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': False,
                    'message': 'Form validation failed',
                    'errors': form.errors
                }), 400
            else:
                return render_template('add_isv.html', form=form)

    return render_template('add_isv.html', form=form)

# Create ISV Tasks table if it doesn't exist
CREATE_TASKS_TABLE = f"""
CREATE TABLE IF NOT EXISTS `{dataset_id}.isv_tasks_new` (
    isv_name STRING,
    task_name STRING,
    status STRING,
    updated_at TIMESTAMP
)
"""

PREDEFINED_TASKS = [
    'Connectivity',
    'Features',
    'Structures & Types',
    'Best Practices',
    'Final Documentation'
]


#Curent ISV page to see the ongoing ISVs
@app.route('/current_isvs')
@login_required
def current_isvs():
    try:
        # Base query that includes actual percentage from ISV_Details_new table
        query = f"""
        WITH TaskStats AS (
            SELECT 
                Sr_No,
                COUNTIF(status = 'Completed') as completed_tasks,
                COUNT(*) as total_tasks
            FROM `{dataset_id}.isv_tasks_new`
            GROUP BY Sr_No
        ),
        RecentCompleted AS (
            SELECT 
                Sr_No,
                ROW_NUMBER() OVER (
                    PARTITION BY status 
                    ORDER BY ISV_Start_Date DESC
                ) as completion_rank
            FROM `{dataset_id}.{new_table_id}`
            WHERE status = 'Completed'
        ),
        MainData AS (
            SELECT 
                i.Sr_No,
                i.Tool_Name as isv_name,
                i.Domain as domain,
                i.POC as poc,
                i.Status as status,
                i.ISV_Start_Date as start_date,
                i.YearQuarter,
                IFNULL(ts.completed_tasks, 0) as completed_tasks,
                IFNULL(i.Percentage, 0) as completion_percentage
            FROM `{dataset_id}.{new_table_id}` i
            LEFT JOIN TaskStats ts ON i.Sr_No = ts.Sr_No
            LEFT JOIN RecentCompleted rc ON i.Sr_No = rc.Sr_No
            WHERE 
                i.Status IN ('not started', 'in progress')
                OR (i.Status = 'Completed' AND rc.completion_rank <= 3)
            ORDER BY 
                CASE 
                    WHEN i.Status = 'in progress' THEN 1
                    WHEN i.Status = 'not started' THEN 2
                    WHEN i.Status = 'Completed' THEN 3
                END,
                i.ISV_Start_Date DESC
        )
        SELECT * FROM MainData
        """

        # Execute the main query
        query_job = client.query(query)
        isv_results = list(query_job.result())

        # Process ISVs and get their tasks
        isvs = []
        for row in isv_results:
            # Get tasks for this ISV in a separate query
            tasks_query = f"""
            SELECT 
                Sr_No,
                task_name,
                status,
                updated_at
            FROM `{dataset_id}.isv_tasks_new`
            WHERE Sr_No = {row.Sr_No}
            ORDER BY task_name
            """
            tasks = list(client.query(tasks_query).result())

            # Convert tasks to list of dictionaries
            tasks_data = []
            for task in tasks:
                task_dict = {
                    'Sr_No': task.Sr_No,
                    'task_name': task.task_name,
                    'status': 'Completed' if task.status == 'completed' else task.status,
                    'updated_at': task.updated_at
                }
                tasks_data.append(task_dict)

            # Create ISV dictionary with tasks
            isv = {
                'Sr_No': row.Sr_No,
                'isv_name': row.isv_name,
                'domain': row.domain,
                'poc': row.poc,
                'status': row.status,
                'start_date': row.start_date,
                'YearQuarter': row.YearQuarter,
                'completed_tasks': row.completed_tasks,
                'completion_percentage': row.completion_percentage,
                'tasks': tasks_data
            }
            isvs.append(isv)

        return render_template('current_isvs.html', isvs=isvs)

    except Exception as e:
        print(f"Error in current_isvs route: {str(e)}")
        flash('An error occurred while loading the data. Please try again.', 'error')
        return render_template('current_isvs.html', isvs=[])

def initialize_isv_tasks(sr_no):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for task_name in PREDEFINED_TASKS:
        query = f"""
        INSERT INTO `{dataset_id}.isv_tasks_new`
        (Sr_No, task_name, status, updated_at)
        VALUES
        ({sr_no}, '{task_name}', 'not started', '{now}')
        """
        client.query(query).result()

# Update task status route
@app.route('/task/status', methods=['PUT'])
def update_task_status():
    try:
        data = request.json
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Update the task status in isv_tasks_new
        query = f"""
        UPDATE `{dataset_id}.isv_tasks_new`
        SET status = '{data['status'].lower()}', updated_at = '{now}'
        WHERE Sr_No = {data['sr_no']}
        AND task_name = '{data['task_name']}'
        """
        client.query(query).result()

        return jsonify({'message': 'Task status updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Delete ISVs from current_isv page
@app.route('/isv/<int:sr_no>', methods=['DELETE'])
@admin_required
def delete_isv(sr_no):
    try:
        # Delete tasks first
        delete_tasks_query = f"""
        DELETE FROM `{dataset_id}.isv_tasks_new`
        WHERE Sr_No = {sr_no}
        """
        client.query(delete_tasks_query).result()

        # Delete ISV
        delete_isv_query = f"""
        DELETE FROM `{dataset_id}.{new_table_id}`
        WHERE Sr_No = {sr_no}
        """
        client.query(delete_isv_query).result()

        return jsonify({'message': 'ISV deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/isv/<int:sr_no>/edit', methods=['GET'])
@admin_required
def edit_isv(sr_no):
    # Query to get all fields from the table
    query = f"""
    SELECT 
        Sr_No,
        Tool_Name as isv_name,
        Domain as domain,
        Certification_Type as certification_type,
        Version as version,
        Description as description,
        Team_Members as team_members,
        ISV_Start_Date as start_date,
        ISV_End_Date as end_date,
        POC as poc,
        Status as status,
        Percentage as percentage,
        Comments as comments,
        Assessment_Sheet as assessment_sheet,
        Questions_Doc as questions_doc,
        Acceptance_Criteria_Sheet as acceptance_criteria_sheet,
        Summary_Doc1 as summary_doc1,
        Summary_Doc2 as summary_doc2,
        IOL_Doc as iol_doc,
        Installation_Doc as installation_doc,
        Best_Practices_Doc as best_practices_doc,
        Performance_Doc as performance_doc,
        Metric_Observation_Doc as metric_observation_doc,
        Issue_Bug_Doc as issue_bug_doc
    FROM `{dataset_id}.{new_table_id}`
    WHERE Sr_No = {sr_no}
    """
    result = list(client.query(query).result())[0]
    result_dict = dict(result.items())

    # Convert comma-separated domains back to list
    if result_dict.get('domain'):
        result_dict['domain'] = result_dict['domain'].split(',')

    # Convert dates if they are strings
    if isinstance(result_dict.get('start_date'), str):
        result_dict['start_date'] = datetime.strptime(result_dict['start_date'], '%Y-%m-%d').date()
    if isinstance(result_dict.get('end_date'), str) and result_dict['end_date']:
        result_dict['end_date'] = datetime.strptime(result_dict['end_date'], '%Y-%m-%d').date()

    form = ISVForm(data=result_dict)
    return render_template('edit_isv.html', form=form, sr_no=sr_no, isv_name=result_dict['isv_name'])

@app.route('/isv/<int:sr_no>/update', methods=['POST'])
@admin_required
def update_isv(sr_no):
    form = ISVForm()
    if form.validate_on_submit():
        try:
            # Join multiple domains with commas
            domains = ','.join(form.domain.data)

            # Calculate Year, Quarter, and YearQuarter from start_date
            start_date = form.start_date.data
            year = start_date.year
            quarter_num = (start_date.month - 1) // 3 + 1
            quarter = f"Q{quarter_num}"
            year_quarter = f"FY{year}{quarter}"  # Format: FY2025Q1

            # Escape single quotes in text fields to prevent SQL injection
            def escape_sql(value):
                return str(value).replace("'", "''") if value else ''

            query = f"""
            UPDATE `{dataset_id}.{new_table_id}`
            SET
                Tool_Name = '{escape_sql(form.isv_name.data)}',
                Domain = '{escape_sql(domains)}',
                Certification_Type = '{escape_sql(form.certification_type.data)}',
                Version = '{escape_sql(form.version.data)}',
                Description = '{escape_sql(form.description.data)}',
                Team_Members = '{escape_sql(form.team_members.data)}',
                Year = {year},
                Quarter = '{quarter}',
                YearQuarter = '{year_quarter}',
                ISV_Start_Date = '{form.start_date.data.strftime('%Y-%m-%d')}',
                ISV_End_Date = '{form.end_date.data.strftime('%Y-%m-%d') if form.end_date.data else ''}',
                POC = '{escape_sql(form.poc.data)}',
                Status = '{escape_sql(form.status.data)}',
                Percentage = {float(form.percentage.data) if form.percentage.data else 0.0},
                Comments = '{escape_sql(form.comments.data)}',
                Assessment_Sheet = '{escape_sql(form.assessment_sheet.data)}',
                Questions_Doc = '{escape_sql(form.questions_doc.data)}',
                Acceptance_Criteria_Sheet = '{escape_sql(form.acceptance_criteria_sheet.data)}',
                Summary_Doc1 = '{escape_sql(form.summary_doc1.data)}',
                Summary_Doc2 = '{escape_sql(form.summary_doc2.data)}',
                IOL_Doc = '{escape_sql(form.iol_doc.data)}',
                Installation_Doc = '{escape_sql(form.installation_doc.data)}',
                Best_Practices_Doc = '{escape_sql(form.best_practices_doc.data)}',
                Performance_Doc = '{escape_sql(form.performance_doc.data)}',
                Metric_Observation_Doc = '{escape_sql(form.metric_observation_doc.data)}',
                Issue_Bug_Doc = '{escape_sql(form.issue_bug_doc.data)}'
            WHERE Sr_No = {sr_no}
            """
            client.query(query).result()

            flash('ISV updated successfully!', 'success')
            return redirect(url_for('current_isvs'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
            print(f"Update error: {str(e)}")  # For debugging

    return render_template('edit_isv.html', form=form, sr_no=sr_no)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            return jsonify({
                'success': False,
                'message': 'Please provide both email and password'
            }), 400

        # Query user from BigQuery
        query = f"""
        SELECT email, password_hash, role
        FROM `{dataset_id}.users`
        WHERE email = @email
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("email", "STRING", email)
            ]
        )

        results = list(client.query(query, job_config=job_config))

        if not results:
            return jsonify({
                'success': False,
                'message': 'Invalid email or password'
            }), 401

        user = results[0]

        if check_password_hash(user.password_hash, password):
            session['user_email'] = user.email
            session['user_role'] = user.role

            # Update last login timestamp
            update_query = f"""
            UPDATE `{dataset_id}.users`
            SET last_login = CURRENT_TIMESTAMP()
            WHERE email = @email
            """
            client.query(update_query, job_config=job_config).result()

            return jsonify({
                'success': True,
                'message': 'Login successful!',
                'redirect': url_for('index')
            })

        return jsonify({
            'success': False,
            'message': 'Invalid email or password'
        }), 401

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not email or not password or not confirm_password:
            return jsonify({
                'success': False,
                'message': 'Please fill in all fields'
            }), 400

        # Validate email format
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({
                'success': False,
                'message': 'Please enter a valid email address'
            }), 400

        # Check if user already exists
        check_query = f"""
        SELECT COUNT(*) as count
        FROM `{dataset_id}.users`
        WHERE email = @email
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("email", "STRING", email)
            ]
        )

        results = list(client.query(check_query, job_config=job_config))
        if results[0].count > 0:
            return jsonify({
                'success': False,
                'message': 'Email already registered'
            }), 400

        # Create new user with 'user' role
        password_hash = generate_password_hash(password)
        insert_query = f"""
        INSERT INTO `{dataset_id}.users` (email, password_hash, role, created_at, last_login)
        VALUES (@email, @password_hash, 'user', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("email", "STRING", email),
                bigquery.ScalarQueryParameter("password_hash", "STRING", password_hash)
            ]
        )

        try:
            client.query(insert_query, job_config=job_config).result()
            return jsonify({
                'success': True,
                'message': 'Registration successful! Please login.',
                'redirect': url_for('login')
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'An error occurred: {str(e)}'
            }), 500

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'success')
    return redirect(url_for('login'))

# Anushree's Code
@app.route("/isv_history_with_filter", methods=["GET"])
@login_required
def isv_history_with_filter():
    selected_quarter = request.args.get("quarter")
    selected_year = request.args.get("year")

    # Base query
    query = """
        SELECT Sr_No, Tool_Name, Domain, Certification_Type, Version, Description, Team_Members, Year, Quarter, YearQuarter, POC, ISV_Start_Date, ISV_End_Date, Status, Percentage, Comments, Assessment_Sheet, Questions_Doc
        FROM `wwbq-treasuredata.GBQ.ISV_Details`
        WHERE Tool_Name IS NOT NULL
    """

    # Fetch distinct years and quarters to populate the dropdown
    distinct_query = """
        SELECT DISTINCT Year, Quarter
        FROM `wwbq-treasuredata.GBQ.ISV_Details`
    """
    distinct_query_job = client.query(distinct_query)
    distinct_results = list(distinct_query_job.result())

    # Ensure `Year` is treated as string and include the current year if not present
    years = sorted({str(row["Year"]) for row in distinct_results})
    current_year = str(datetime.now().year)
    if current_year not in years:
        years.append(current_year)
    years = sorted(years)

    quarters = sorted({row["Quarter"] for row in distinct_results})

    # Set default selection to current year and quarter if no selection is made
    if not selected_quarter:
        selected_quarter = f"Q{((datetime.now().month - 1) // 3) + 1}"
    if not selected_year:
        selected_year = current_year

    # Add filter conditions based on user selection
    if selected_quarter:
        query += f" AND Quarter = '{selected_quarter}'"
    if selected_year:
        query += f" AND Year = {selected_year}"

    try:
        # Execute the query
        query_job = client.query(query)
        results = query_job.result()

        # Transform results into a list of dictionaries
        isv_details = [
            {
                "sr_no": row.Sr_No,
                "tool_name": row.Tool_Name,
                "domain": row.Domain,
                "certification_type": row.Certification_Type,
                "version": row.Version,
                "description": row.Description,
                "assessment_sheet": row.Assessment_Sheet,
                "questions_doc": row.Questions_Doc,
                "team_members": row.Team_Members,
                "year": row.Year,
                "quarter": row.Quarter,
                "year_quarter": row.YearQuarter,
                "poc": row.POC,
                "isv_start_date": row.ISV_Start_Date,
                "isv_end_date": row.ISV_End_Date,
                "status": row.Status,
                "percentage": row.Percentage,
                "comments": row.Comments,
            }
            for row in results
        ]

        # Render template with the filtered data
        return render_template(
            "isv_history_with_filter.html",
            data=isv_details,
            years=years,
            quarters=quarters,
            selected_quarter=selected_quarter,
            selected_year=selected_year,
        )
    except Exception as e:
        return f"An error occurred: {e}"

@app.route("/most_recent_isvs", methods=["GET"])
def most_recent_isvs():
    # Calculate the current quarter and year
    current_year = datetime.now().year
    current_quarter = f"Q{((datetime.now().month - 1) // 3) + 1}"

    # Base query to fetch data for the most recent quarter
    query = f"""
    SELECT Sr_No, Tool_Name, Domain, Certification_Type, Version, Description, Team_Members, Year, Quarter, YearQuarter, POC, ISV_Start_Date, ISV_End_Date, Status, Percentage, Comments, Assessment_Sheet, Questions_Doc
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    WHERE Tool_Name IS NOT NULL AND Year = {current_year} AND Quarter = '{current_quarter}'
    ORDER BY ISV_Start_Date DESC
    """

    try:
        # Execute the query to get the most recent ISVs
        query_job = client.query(query)
        results = query_job.result()

        # Transform results into a list of dictionaries
        isv_details = [
            {
                "sr_no": row.Sr_No,
                "tool_name": row.Tool_Name,
                "domain": row.Domain,
                "certification_type": row.Certification_Type,
                "version": row.Version,
                "description": row.Description,
                "assessment_sheet": row.Assessment_Sheet,
                "questions_doc": row.Questions_Doc,
                "team_members": row.Team_Members,
                "year": row.Year,
                "quarter": row.Quarter,
                "year_quarter": row.YearQuarter,
                "poc": row.POC,
                "isv_start_date": row.ISV_Start_Date,
                "isv_end_date": row.ISV_End_Date,
                "status": row.Status,
                "percentage": row.Percentage,
                "comments": row.Comments,
            }
            for row in results
        ]

        # Fetch distinct years and quarters to populate the dropdown
        distinct_query = """
        SELECT DISTINCT Year, Quarter
        FROM `wwbq-treasuredata.GBQ.ISV_Details`
        """
        distinct_query_job = client.query(distinct_query)
        distinct_results = list(distinct_query_job.result())

        # Include current year if not present
        years = sorted({str(row["Year"]) for row in distinct_results})
        current_year = str(datetime.now().year)
        if current_year not in years:
            years.append(current_year)
        years = sorted(years)
        quarters = sorted({row["Quarter"] for row in distinct_results})

        # Render the template with the filtered data
        return render_template(
            "isv_history_with_filter.html",
            data=isv_details,
            years=years,
            quarters=quarters,
            selected_quarter=current_quarter,
            selected_year=str(current_year),
        )
    except Exception as e:
        return f"An error occurred: {e}"


#Krishnakanth's Code

# Fetch ISVs from BigQuery
def fetch_isvs(query):
    query_job = client.query(query)
    results = query_job.result()
    return [dict(row) for row in results]

@app.route('/isv_status/<status>')
def isv_status(status):
    query = f"""Select Tool_Name, Domain, Team_Members, ISV_Start_Date, ISV_End_Date, YearQuarter FROM `wwbq-treasuredata.GBQ.ISV_Details` WHERE status = @status ORDER BY YearQuarter DESC, ISV_Start_Date DESC, Domain"""
    job_config = bigquery.QueryJobConfig(
        query_parameters =[bigquery.ScalarQueryParameter("status", "STRING", status)]
    )
    query_job = client.query(query, job_config=job_config)
    results = query_job.result()
    isv_details =[{
        "Tool_Name": row.Tool_Name,
        "Domain": row.Domain,
        "Team_Members": row.Team_Members,
        "ISV_Start_Date": row.ISV_Start_Date,
        "ISV_End_Date": row.ISV_End_Date,
        "YearQuarter": row.YearQuarter,
    }
    for row in results]
    return render_template('isv_status2.html', status=status, isv_details=isv_details)

@app.route('/list_isvs')
@login_required
def list_isvs():
    query = "SELECT Tool_Name FROM `wwbq-treasuredata.GBQ.ISV_Details`"
    isvs = fetch_isvs(query)
    return render_template('list_isvs2.html', isvs=isvs)


@app.route('/list_by_domain', methods=['GET'])
@login_required
def list_by_domain():
    query = """
    SELECT Domain, ARRAY_AGG(Tool_Name) as Tool_Name 
    FROM `wwbq-treasuredata.GBQ.ISV_Details` 
    GROUP BY Domain 
    ORDER BY Domain
    """
    isvs = fetch_isvs(query)
    return render_template('list_by_domain2.html', isvs=isvs)



# List ISVs by Year and Quarter route
@app.route("/list_by_year_quarter", methods=["GET", "POST"])
@login_required
def list_by_year_quarter():
    # Fetch years and quarters from BigQuery
    query_year_quarter = """
    SELECT DISTINCT year, quarter FROM `wwbq-treasuredata.GBQ.ISV_Details`
    """
    results = client.query(query_year_quarter).result()
    years, quarters = set(), set()
    for row in results:
        years.add(row.year)
        quarters.add(row.quarter)

    isv_data = None
    year, quarter = None, None

    # Fetch ISVs based on year and quarter selection
    if request.method == "POST":
        year = request.form.get("year")
        quarter = request.form.get("quarter")
        query_isvs = f"""
        SELECT Tool_Name, Domain 
        FROM `wwbq-treasuredata.GBQ.ISV_DETAILS_TEST` 
        WHERE year = {year} AND quarter = '{quarter}'
        """
        isv_data = client.query(query_isvs).result()
        return render_template('list_by_year_qtr2.html', years=sorted(years),
        quarters=sorted(quarters),
        isv_data=isv_data,
        year=year,
        quarter=quarter,)


    return render_template(
        "list_by_year_qtr2.html",
        years=sorted(years),
        quarters=sorted(quarters),
        isv_data=isv_data,
        year=year,
        quarter=quarter,
        # domain_chart=domain_chart,
        # quarter_chart=quarter_chart,
    )

# Initialize seaborn style
sns.set_theme()  # Set seaborn defaults
sns.set_style("whitegrid")  # Set specific style

def set_chart_style():
    """Set common style elements for all charts"""
    # Use seaborn styling
    sns.set_style("whitegrid")
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Arial']
    plt.rcParams['axes.edgecolor'] = '#333333'
    plt.rcParams['axes.linewidth'] = 1.0
    plt.rcParams['grid.alpha'] = 0.3
    plt.rcParams['grid.color'] = '#666666'


def set_chart_style():
    """Set common style elements for all charts"""
    # First use a matplotlib style as base
    plt.style.use('bmh')

    # Then apply seaborn styling
    sns.set_style("whitegrid")

    # Finally, add custom tweaks
    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Arial'],
        'axes.edgecolor': '#333333',
        'axes.linewidth': 1.0,
        'grid.alpha': 0.3,
        'grid.color': '#666666',
        'figure.figsize': [10, 6],
        'figure.dpi': 100
    })

# Example usage for a specific chart
def generate_domain_chart():
    set_chart_style()  # Apply the style
    query = """
    SELECT domain, COUNT(*) AS isv_count
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    GROUP BY domain
    ORDER BY isv_count DESC
    """
    results = client.query(query).result()
    domains, counts = [], []
    for row in results:
        domains.append(row.domain)
        counts.append(row.isv_count)

    # Create figure with specific size and DPI
    plt.figure(figsize=(12, 6), dpi=100)
    set_chart_style()

    # Create gradient colors
    colors = plt.cm.Blues(np.linspace(0.4, 0.8, len(domains)))

    # Create bars with gradient colors
    bars = plt.bar(domains, counts, color=colors)

    # Customize the chart
    plt.title('ISV Distribution Across Domains', fontsize=16, pad=20)
    plt.xlabel('Domain', fontsize=12, labelpad=10)
    plt.ylabel('Number of ISVs', fontsize=12, labelpad=10)

    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right', fontsize=10)
    plt.yticks(fontsize=10)

    # Add value labels on top of bars
    for bar in bars:
        height = bar.get_height()
        plt.text(bar.get_x() + bar.get_width() / 2., height,
                 f'{int(height)}',
                 ha='center', va='bottom')

    # Adjust layout to prevent label cutoff
    plt.tight_layout()

    # Save to buffer
    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches='tight', dpi=100)
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode()
    img.close()
    plt.close()
    return chart


def generate_quarter_chart():
    query = """
    SELECT CAST(year as INT64) as year, quarter, COUNT(*) AS isv_count
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    GROUP BY year, quarter 
    ORDER BY year, quarter
    """
    results = client.query(query).result()

    data = {}
    years = set()
    quarters = ['Q1', 'Q2', 'Q3', 'Q4']
    for row in results:
        year = row.year
        quarter = row.quarter
        count = row.isv_count
        if quarter not in data:
            data[quarter] = {}
        data[quarter][year] = count
        years.add(year)

    years = sorted(years)
    x = range(len(years))
    bar_width = 0.2

    # Create figure with increased height
    fig = plt.figure(figsize=(10, 8), dpi=100)  # Increased height from 6 to 8
    ax = fig.add_subplot(111)
    set_chart_style()

    # Color palette for quarters with enhanced visibility
    colors = ['#1f77b4', '#2ca02c', '#ff7f0e', '#d62728']

    # Plot bars for each quarter
    for i, (quarter, color) in enumerate(zip(quarters, colors)):
        values = [data.get(quarter, {}).get(year, 0) for year in years]
        bars = ax.bar([p + bar_width * i for p in x], values, bar_width,
                      label=quarter, color=color, alpha=0.85)  # Slightly increased alpha

        # Add value labels on top of bars
        for bar in bars:
            height = bar.get_height()
            if height > 0:  # Only add label if there's a value
                ax.text(bar.get_x() + bar.get_width() / 2., height,
                        f'{int(height)}', ha='center', va='bottom',
                        fontsize=9)  # Slightly larger font for labels

    # Customize the chart
    ax.set_title('Quarterly ISV Growth Trends', fontsize=16, pad=20)
    ax.set_xlabel('Years', fontsize=12, labelpad=10)
    ax.set_ylabel('Number of ISVs', fontsize=12, labelpad=10)

    # Set x-axis ticks
    ax.set_xticks([p + bar_width * len(quarters) / 2 for p in x])
    ax.set_xticklabels(years, fontsize=10)

    # Add legend at the bottom with horizontal layout
    ax.legend(title='Quarters', title_fontsize=10, fontsize=9,
              loc='upper center', bbox_to_anchor=(0.5, -0.15),
              ncol=4)  # Changed legend position and made it horizontal

    # Adjust layout to accommodate bottom legend
    plt.tight_layout()
    plt.subplots_adjust(bottom=0.2)  # Make room for the legend

    # Save to buffer
    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches='tight', dpi=100)
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode()
    img.close()
    plt.close()
    return chart


def generate_pie_chart():
    set_chart_style()  # Apply the style
    query = """
    SELECT Year as year, COUNT(*) AS isv_count
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    GROUP BY year 
    ORDER BY year
    """
    results = client.query(query).result()
    years, counts = [], []
    for row in results:
        years.append(str(int(row.year)))
        counts.append(row.isv_count)

    # Create figure
    plt.figure(figsize=(8, 8), dpi=100)
    set_chart_style()

    # Color palette
    colors = plt.cm.Pastel1(np.linspace(0, 1, len(years)))

    # Create pie chart with custom styling
    patches, texts, autotexts = plt.pie(counts, labels=years, colors=colors,
                                        autopct='%1.1f%%', startangle=90,
                                        pctdistance=0.85,
                                        wedgeprops={'edgecolor': 'white',
                                                    'linewidth': 2,
                                                    'antialiased': True})

    # Add a circle at the center to create a donut chart effect
    centre_circle = plt.Circle((0, 0), 0.70, fc='white')
    fig = plt.gcf()
    fig.gca().add_artist(centre_circle)

    # Customize text properties
    plt.setp(autotexts, size=9, weight="bold")
    plt.setp(texts, size=10)

    # Add title in the center
    plt.text(0, 0, 'ISV Distribution\nby Year',
             horizontalalignment='center',
             verticalalignment='center',
             fontsize=14,
             fontweight='bold')

    # Equal aspect ratio ensures that pie is drawn as a circle
    plt.axis('equal')

    # Save to buffer
    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches='tight', dpi=100)
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode('utf8')
    img.close()
    plt.close()
    return chart


def generate_qtr_growth_chart():
    set_chart_style()  # Apply the style
    query = """
    SELECT CONCAT(CAST(year as STRING), '-', quarter) AS period, 
           Count(*) as tool_count,
           SUM(Count(*)) OVER (ORDER BY year, quarter) as cumulative_count
    FROM `wwbq-treasuredata.GBQ.ISV_Details` 
    GROUP BY year, quarter 
    ORDER BY year, quarter
    """
    data = fetch_isvs(query)
    periods = [row['period'] for row in data]
    counts = [row['tool_count'] for row in data]
    cumulative = [row['cumulative_count'] for row in data]

    # Create figure
    plt.figure(figsize=(10, 6), dpi=100)
    set_chart_style()

    # Plot both lines
    plt.plot(periods, counts, marker='o', label="Quarterly Additions",
             color='#2196F3', linewidth=2, markersize=6)
    plt.plot(periods, cumulative, marker='s', label="Cumulative Growth",
             color='#4CAF50', linewidth=2, markersize=6)

    # Add points labels
    for i, (count, cum) in enumerate(zip(counts, cumulative)):
        plt.annotate(f'{count}', (periods[i], count),
                     textcoords="offset points", xytext=(0, 10),
                     ha='center', fontsize=8)
        plt.annotate(f'{cum}', (periods[i], cum),
                     textcoords="offset points", xytext=(0, -15),
                     ha='center', fontsize=8)

    # Customize the chart
    plt.title('ISV Growth Trajectory', fontsize=16, pad=20)
    plt.xlabel('Year-Quarter', fontsize=12, labelpad=10)
    plt.ylabel('Number of ISVs', fontsize=12, labelpad=10)

    # Rotate x-axis labels
    plt.xticks(rotation=45, ha='right', fontsize=10)
    plt.yticks(fontsize=10)

    # Add legend
    plt.legend(fontsize=10, loc='upper left')

    # Adjust layout
    plt.tight_layout()

    # Save to buffer
    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches='tight', dpi=100)
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode('utf8')
    img.close()
    plt.close()
    return chart


def generate_top_domain_chart():
    query = """
    Select Domain as domain, Count(*) as tool_count 
    FROM `wwbq-treasuredata.GBQ.ISV_Details` 
    GROUP BY domain 
    ORDER BY tool_count DESC 
    LIMIT 10
    """
    data = fetch_isvs(query)

    # Sort data in descending order
    data = sorted(data, key=lambda x: x['tool_count'], reverse=True)

    # Extract sorted domains and counts
    domains = [row['domain'] for row in data]
    counts = [row['tool_count'] for row in data]

    # Create figure
    plt.figure(figsize=(10, 6), dpi=100)
    set_chart_style()

    # Create gradient colors - using greens
    colors = plt.cm.Greens(np.linspace(0.5, 0.9, len(domains)))

    # Create position array - reversed to show highest value at top
    positions = range(len(domains) - 1, -1, -1)

    # Create horizontal bars with reversed positions
    bars = plt.barh(positions, counts, color=colors)

    # Customize the chart
    plt.title('Top 10 Domains by ISV Count', fontsize=16, pad=20)
    plt.xlabel('Number of ISVs', fontsize=12, labelpad=10)

    # Set y-ticks with domain names - reversed to match bar positions
    plt.yticks(positions, domains, fontsize=10)

    # Add value labels at the end of each bar
    for bar in bars:
        width = bar.get_width()
        plt.text(width, bar.get_y() + bar.get_height() / 2,
                 f' {int(width)}',
                 va='center', fontsize=10, fontweight='bold')

    # Customize ticks
    plt.xticks(fontsize=10)

    # Remove edge lines for cleaner look
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)

    # Add light grid lines only for x-axis
    plt.grid(axis='x', linestyle='--', alpha=0.3)

    # Adjust layout
    plt.tight_layout()

    # Save to buffer
    img = io.BytesIO()
    plt.savefig(img, format="png", bbox_inches='tight', dpi=100)
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode('utf8')
    img.close()
    plt.close()
    return chart

# Function to execute SQL query and return results as a list of dictionaries
def execute_query(query):
    client = bigquery.Client()
    query_job = client.query(query)
    results = query_job.result()
    return [dict(row) for row in results]
    # return [{"ISV_Name": row.ISV_Name, "Domain": row.Domain} for row in results]

@app.route('/best_isv_by_domain')
@login_required
def index_new():
    query = """ SELECT
  a.tool AS Tool_Name,
  a.category AS Domain
FROM
  wwbq-treasuredata.GBQ.BEST_ISV_DETAILS a,
  (
  SELECT
    category,
    MIN(Percentage_Of_Failure) AS min_fail
  FROM
    wwbq-treasuredata.GBQ.BEST_ISV_DETAILS
  GROUP BY
    category) b
WHERE
  a.category=b.category
  AND a.Percentage_Of_Failure=b.min_fail
ORDER BY
  a.category; """

    query_job = client.query(query)
    results = query_job.result()
    return render_template('best_isv2_1.html', results=results)


@app.route('/best_isv_by_yr_qtr')
@login_required
def index1():
    query = """ SELECT
  a.tool AS ISV_Name,
  a.year AS Year,
  a.qtr AS Quarter,
  a.category AS Category
FROM
  wwbq-treasuredata.GBQ.BEST_ISV_DETAILS a,
  (
  SELECT
    year,
    qtr,
    MIN(Percentage_Of_Failure) AS min_fail
  FROM
    wwbq-treasuredata.GBQ.BEST_ISV_DETAILS
  GROUP BY
    year,
    qtr
  ORDER BY
    year,
    qtr) b
WHERE
  a.year=b.year
  AND a.qtr=b.qtr
  AND a.Percentage_Of_Failure=b.min_fail
ORDER BY
  a.year,
  a.qtr; """

    query_job = client.query(query)
    results = query_job.result()
    return render_template('best_isv2_2.html', results=results)

# Helper functions for dropdowns
def get_domains():
    query = "SELECT DISTINCT Domain FROM `wwbq-treasuredata.GBQ.ISV_Details`"
    results = fetch_isvs(query)
    return [row['Domain'] for row in results]

def get_dist_domains_count():
    query = "SELECT count(DISTINCT Domain) as total_domains FROM `wwbq-treasuredata.GBQ.ISV_Details` Where Domain Not Like '%+%';"
    query_job = client.query(query)
    results = query_job.result()
    for row in results:
        return row["total_domains"]

def get_years():
    query = "SELECT DISTINCT Year FROM `wwbq-treasuredata.GBQ.ISV_Details`"
    results = fetch_isvs(query)
    return [row['Year'] for row in results]

def get_quarters():
    query = "SELECT DISTINCT Quarter FROM `wwbq-treasuredata.GBQ.ISV_Details`"
    results = fetch_isvs(query)
    return [row['Quarter'] for row in results]

#vinnet and Anurag's code

def get_domains():
    query=f"""SELECT DISTINCT Domain FROM `wwbq-treasuredata.GBQ.ISV_Details`"""
    query_job = client.query(query)
    results = query_job.result()
    domains = [row.Domain for row in results]
    return domains

# Cache for ISV data
ISV_CACHE = []

def load_isv_data():
    """Load data from BigQuery into a cache."""
    global ISV_CACHE
    query = """
        SELECT Sr_No, Tool_Name, Domain, YearQuarter, Status
        FROM `wwbq-treasuredata.GBQ.ISV_Details`
        ORDER BY ISV_Start_Date DESC
    """
    query_job = client.query(query)
    results = query_job.result()
    ISV_CACHE = []
    for row in results:
        isv_dict = dict(row.items())
        ISV_CACHE.append(isv_dict)

@app.route('/list')
@login_required
def list_isv():
    global ISV_CACHE
    load_isv_data()
    search_term = request.args.get('search', '').lower()
    yearquarter_filter = request.args.get('yearquarter', '')
    status_filter = request.args.get('status', '')
    page = int(request.args.get('page', 1))
    items_per_page = 10

    # Filter data based on search term, YearQuarter and Status
    filtered_data = [
        item for item in ISV_CACHE
        if (search_term in item["Tool_Name"].lower() or search_term in item["Domain"].lower()) and
           (not yearquarter_filter or item["YearQuarter"] == yearquarter_filter) and
           (not status_filter or item["Status"] == status_filter)
    ]

    total_items = len(filtered_data)
    total_pages = (total_items + items_per_page - 1) // items_per_page
    start_index = (page - 1) * items_per_page
    end_index = start_index + items_per_page
    paginated_data = filtered_data[start_index:end_index]

    # Get distinct YearQuarter and Status values
    yearquarters = list(set(item["YearQuarter"] for item in ISV_CACHE))
    statuses = list(set(item["Status"] for item in ISV_CACHE))

    return render_template(
        'isv_list.html',
        isvs=paginated_data,
        total_pages=total_pages,
        current_page=page,
        yearquarters=yearquarters,
        statuses=statuses
    )

@app.route('/details/<int:sr_no>', methods=['GET'])
@login_required
def details(sr_no):
    table_ref = f"{client.project}.{dataset_id}.{new_table_id}"
    query = f"SELECT * FROM `{table_ref}` WHERE Sr_No = @sr_no"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("sr_no", "INT64", sr_no)
        ]
    )
    results = list(client.query(query, job_config=job_config))
    details = results[0] if results else None
    return render_template('isv_details.html', details=details)


@app.route('/edit/<int:sr_no>', methods=['GET', 'POST'])
@admin_required
def edit(sr_no):
    domain_options = get_domains()
    table_ref = f"{client.project}.{dataset_id}.{new_table_id}"

    if request.method == 'GET':
        query = f"""
        SELECT *
        FROM `{table_ref}`
        WHERE Sr_No = @sr_no
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("sr_no", "INT64", sr_no)
            ]
        )
        results = list(client.query(query, job_config=job_config))
        details = dict(results[0].items()) if results else None

        if not details:
            flash("ISV not found.", "error")
            return redirect(url_for('list'))

        return render_template('edit.html', details=details, domain_options=domain_options)

    elif request.method == 'POST':
        try:
            # Get the form data
            data = request.form.to_dict()

            # Handle new domain if specified
            if data.get('New_Domain'):
                new_domain = data.get('New_Domain')
                data['Domain'] = new_domain
            if 'New_Domain' in data:
                del data['New_Domain']

            # Calculate YearQuarter based on ISV_Start_Date
            if data.get('ISV_Start_Date'):
                date_obj = datetime.strptime(data['ISV_Start_Date'], '%Y-%m-%d')
                year = date_obj.year
                month = date_obj.month
                quarter = f"Q{((month - 1) // 3) + 1}"
                data['Year'] = year
                data['Quarter'] = quarter
                data['YearQuarter'] = f"FY{year}{quarter}"

            # Construct the update query dynamically
            query_parameters = []
            set_clauses = []

            for key, value in data.items():
                if not value:  # Skip empty values
                    continue

                if key in ["Year"]:
                    set_clauses.append(f"{key} = @{key}")
                    query_parameters.append(bigquery.ScalarQueryParameter(key, "INT64", int(value)))
                elif key in ["Percentage"]:
                    set_clauses.append(f"{key} = @{key}")
                    query_parameters.append(bigquery.ScalarQueryParameter(key, "NUMERIC", float(value)))
                elif key in ["ISV_Start_Date", "ISV_End_Date"]:
                    if value.strip():  # Only process non-empty date strings
                        try:
                            # Validate date format
                            datetime.strptime(value, '%Y-%m-%d')
                            set_clauses.append(f"{key} = @{key}")
                            query_parameters.append(bigquery.ScalarQueryParameter(key, "DATE", value))
                        except ValueError:
                            continue
                else:
                    set_clauses.append(f"{key} = @{key}")
                    query_parameters.append(bigquery.ScalarQueryParameter(key, "STRING", value))

            # Add Sr_No parameter
            query_parameters.append(bigquery.ScalarQueryParameter("Sr_No", "INT64", sr_no))

            if set_clauses:  # Only proceed if there are fields to update
                update_query = f"""
                    UPDATE `{table_ref}`
                    SET {', '.join(set_clauses)}
                    WHERE Sr_No = @Sr_No
                """

                # Execute the update query
                job_config = bigquery.QueryJobConfig(query_parameters=query_parameters)
                client.query(update_query, job_config=job_config).result()

                flash("Details updated successfully!", "success")
                return redirect(url_for('details', sr_no=sr_no))  # Note: changed Sr_No to sr_no
            else:
                flash("No valid fields to update", "warning")
                return render_template('edit.html', details=data, domain_options=domain_options)

        except Exception as e:
            flash(f"Error updating ISV: {str(e)}", "error")
            return render_template('edit.html', details=data, domain_options=domain_options)


@app.route('/delete_isv/<int:sr_no>', methods=['DELETE'])
@admin_required
def delete_tool(sr_no):
    """Delete an ISV and its related tasks from BigQuery."""
    table_ref = f"{client.project}.{dataset_id}.{new_table_id}"
    tasks_table_ref = f"{client.project}.{dataset_id}.isv_tasks_new"

    try:
        # First delete related tasks
        delete_tasks_query = f"""
        DELETE FROM `{tasks_table_ref}`
        WHERE Sr_No = @sr_no
        """

        # Then delete the ISV
        delete_isv_query = f"""
        DELETE FROM `{table_ref}`
        WHERE Sr_No = @sr_no
        """

        # Configure job parameters
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("sr_no", "INT64", sr_no)
            ]
        )

        # Execute delete tasks query
        tasks_query_job = client.query(delete_tasks_query, job_config=job_config)
        tasks_query_job.result()  # Wait for completion

        # Execute delete ISV query
        isv_query_job = client.query(delete_isv_query, job_config=job_config)
        isv_query_job.result()  # Wait for completion

        return jsonify({"message": "ISV and related tasks deleted successfully!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)