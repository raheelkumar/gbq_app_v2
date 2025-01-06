# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from google.cloud import bigquery
import pandas as pd
from datetime import datetime
from google.oauth2 import service_account
from forms import ISVForm
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

# BigQuery client setup
credentials = service_account.Credentials.from_service_account_file('gbq_app_service_account.json')
project_id = 'wwbq-treasuredata'
client = bigquery.Client(credentials=credentials, project=project_id)
dataset_id = "GBQ"
table_id = "isv_data_store"


@app.route('/')
def index():
    # Get counts for dashboard
    counts_query = f"""
    SELECT
        COUNT(CASE WHEN status != 'completed' THEN 1 END) as active_count,
        COUNT(CASE WHEN status = 'in_progress' THEN 1 END) as in_progress_count,
        COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_count
    FROM `{dataset_id}.{table_id}`
    """
    counts_job = client.query(counts_query)
    counts_result = next(counts_job.result())

    # Get recent activities
    activities_query = f"""
    SELECT
        isv_name,
        status,
        created_at as updated_at
    FROM `{dataset_id}.{table_id}`
    ORDER BY created_at DESC
    LIMIT 5
    """
    activities_job = client.query(activities_query)
    recent_activities = activities_job.result()

    return render_template('index.html',
                           active_count=counts_result.active_count or 0,
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
        FROM `{dataset_id}.{table_id}`
        """
        max_srno_result = list(client.query(max_srno_query).result())[0]
        next_srno = (max_srno_result.max_srno or 0) + 1

        # Check if ISV exists
        exists_query = f"""
        SELECT COUNT(*) as count
        FROM `{dataset_id}.{table_id}`
        WHERE LOWER(isv_name) = LOWER('{isv_name}')
        """
        exists_result = list(client.query(exists_query).result())[0]

        return jsonify({
            'exists': exists_result.count > 0,
            'next_srno': next_srno
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/add_isv', methods=['GET', 'POST'])
def add_isv():
    form = ISVForm()
    if form.validate_on_submit():
        try:
            # Get the maximum Sr_No
            max_srno_query = f"""
            SELECT MAX(Sr_No) as max_srno
            FROM `{dataset_id}.{table_id}`
            """
            max_srno_result = list(client.query(max_srno_query).result())[0]
            next_srno = (max_srno_result.max_srno or 0) + 1

            # Join multiple domains with commas
            domains = ','.join(form.domain.data)

            # Prepare the data for BigQuery
            data_to_insert = {
                'Sr_No': next_srno,
                'isv_name': form.isv_name.data,
                'domain': domains,
                'certification_type': form.certification_type.data,
                'version': form.version.data,
                'description': form.description.data,
                'team_members': form.team_members.data,
                'start_date': form.start_date.data.strftime('%Y-%m-%d'),
                'poc': form.poc.data,
                'status': form.status.data,
                'assessment_sheet': form.assessment_sheet.data,
                'questions_doc': form.questions_doc.data,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # Insert into BigQuery
            table_ref = client.dataset(dataset_id).table(table_id)
            errors = client.insert_rows_json(table_ref, [data_to_insert])

            if errors == []:
                # Initialize tasks for the new ISV
                initialize_isv_tasks(next_srno)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': True, 'redirect': url_for('current_isvs')})
                flash('ISV successfully added!', 'success')
                return redirect(url_for('current_isvs'))
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'success': False, 'error': str(errors)}), 400
                flash(f'Error occurred while adding ISV: {str(errors)}', 'error')

        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'success': False, 'error': str(e)}), 500
            flash(f'Error: {str(e)}', 'error')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'success': False,
            'error': 'Invalid form data',
            'errors': form.errors
        }), 400

    return render_template('add_isv.html', form=form)

# Create ISV Tasks table if it doesn't exist
CREATE_TASKS_TABLE = f"""
CREATE TABLE IF NOT EXISTS `{dataset_id}.isv_tasks` (
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


# Update the task initialization function
def initialize_isv_tasks(sr_no):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for task_name in PREDEFINED_TASKS:
        query = f"""
        INSERT INTO `{dataset_id}.isv_tasks`
        (Sr_No, task_name, status, updated_at)
        VALUES
        ({sr_no}, '{task_name}', 'not_started', '{now}')
        """
        client.query(query).result()

# Update current_isvs route
@app.route('/current_isvs')
def current_isvs():
    query = f"""
    WITH TaskStats AS (
        SELECT 
            Sr_No,
            COUNT(*) as total_tasks,
            COUNTIF(status = 'completed') as completed_tasks
        FROM `{dataset_id}.isv_tasks`
        GROUP BY Sr_No
    )
    SELECT 
        i.*,
        IFNULL(ts.completed_tasks, 0) as completed_tasks,
        IFNULL(ROUND(IFNULL(ts.completed_tasks, 0) * 100.0 / 5, 1), 0) as completion_percentage
    FROM `{dataset_id}.{table_id}` i
    LEFT JOIN TaskStats ts ON i.Sr_No = ts.Sr_No
    WHERE i.status != 'Completed'
    ORDER BY i.start_date DESC
    """

    isvs_query = client.query(query)
    isvs = [dict(row.items()) for row in isvs_query.result()]

    # Get tasks for each ISV
    for isv in isvs:
        tasks_query = f"""
        SELECT *
        FROM `{dataset_id}.isv_tasks`
        WHERE Sr_No = {isv['Sr_No']}
        ORDER BY task_name
        """
        tasks = list(client.query(tasks_query).result())

        # If no tasks exist, initialize them
        if not tasks:
            initialize_isv_tasks(isv['Sr_No'])
            tasks = list(client.query(tasks_query).result())

        isv['tasks'] = [dict(task.items()) for task in tasks]

    return render_template('current_isvs.html', isvs=isvs)

# Update task status route
@app.route('/task/status', methods=['PUT'])
def update_task_status():
    try:
        data = request.json
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Update the task status
        query = f"""
        UPDATE `{dataset_id}.isv_tasks`
        SET status = '{data['status']}', updated_at = '{now}'
        WHERE Sr_No = {data['sr_no']}
        AND task_name = '{data['task_name']}'
        """
        client.query(query).result()

        # Check if all tasks are completed
        check_query = f"""
        SELECT COUNT(*) as incomplete_tasks
        FROM `{dataset_id}.isv_tasks`
        WHERE Sr_No = {data['sr_no']}
        AND status != 'completed'
        """
        result = list(client.query(check_query).result())[0]

        # Update ISV status if all tasks are completed
        if result.incomplete_tasks == 0:
            update_isv_query = f"""
            UPDATE `{dataset_id}.{table_id}`
            SET status = 'completed'
            WHERE Sr_No = {data['sr_no']}
            """
            client.query(update_isv_query).result()

        return jsonify({'message': 'Task status updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Update delete ISV route
@app.route('/isv/<int:sr_no>', methods=['DELETE'])
def delete_isv(sr_no):
    try:
        # Delete tasks first
        delete_tasks_query = f"""
        DELETE FROM `{dataset_id}.isv_tasks`
        WHERE Sr_No = {sr_no}
        """
        client.query(delete_tasks_query).result()

        # Delete ISV
        delete_isv_query = f"""
        DELETE FROM `{dataset_id}.{table_id}`
        WHERE Sr_No = {sr_no}
        """
        client.query(delete_isv_query).result()

        return jsonify({'message': 'ISV deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/isv/<int:sr_no>/edit', methods=['GET'])
def edit_isv(sr_no):
    query = f"""
    SELECT 
        Sr_No,
        isv_name,
        domain,
        certification_type,
        version,
        description,
        team_members,
        start_date,
        end_date,
        poc,
        status,
        assessment_sheet,
        questions_doc
    FROM `{dataset_id}.{table_id}`
    WHERE Sr_No = {sr_no}
    """
    result = list(client.query(query).result())[0]

    # Convert comma-separated domains back to list
    result_dict = dict(result.items())
    if result_dict.get('domain'):
        result_dict['domain'] = result_dict['domain'].split(',')

    # Convert start_date and end_date if they are strings
    if isinstance(result_dict.get('start_date'), str):
        result_dict['start_date'] = datetime.strptime(result_dict['start_date'], '%Y-%m-%d').date()
    if isinstance(result_dict.get('end_date'), str):
        result_dict['end_date'] = datetime.strptime(result_dict['end_date'], '%Y-%m-%d').date()

    form = ISVForm(data=result_dict)
    return render_template('edit_isv.html', form=form, sr_no=sr_no, isv_name=result_dict['isv_name'])


@app.route('/isv/<int:sr_no>/update', methods=['POST'])
def update_isv(sr_no):
    form = ISVForm()
    if form.validate_on_submit():
        try:
            # Join multiple domains with commas
            domains = ','.join(form.domain.data)

            query = f"""
            UPDATE `{dataset_id}.{table_id}`
            SET
                isv_name = '{form.isv_name.data}',
                domain = '{domains}',
                certification_type = '{form.certification_type.data}',
                version = '{form.version.data}',
                description = '{form.description.data}',
                team_members = '{form.team_members.data}',
                start_date = '{form.start_date.data.strftime('%Y-%m-%d')}',
                end_date = '{form.end_date.data.strftime('%Y-%m-%d')}',
                poc = '{form.poc.data}',
                status = '{form.status.data}',
                assessment_sheet = '{form.assessment_sheet.data}',
                questions_doc = '{form.questions_doc.data}'
            WHERE Sr_No = {sr_no}
            """
            client.query(query).result()

            flash('ISV updated successfully!', 'success')
            return redirect(url_for('current_isvs'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    return render_template('edit_isv.html', form=form, sr_no=sr_no)


@app.route('/isv_history')
def isv_history():
    # Get filter parameters
    tool_name = request.args.get('tool_name', '')
    domain = request.args.get('domain', '')
    status = request.args.get('status', '')

    # Base query
    query = """
    SELECT *
    FROM `GBQ.ISV_DETAILS_TEST`
    WHERE 1=1
    """

    # Add filters
    if tool_name:
        query += f" AND Tool_Name LIKE '%{tool_name}%'"
    if domain:
        query += f" AND Domain = '{domain}'"
    if status:
        query += f" AND Status = '{status}'"

    # Execute query
    df = client.query(query).to_dataframe()

    # Get unique values for filters
    domains = df['Domain'].unique().tolist()
    statuses = df['Status'].unique().tolist()

    return render_template('isv_history.html',
                           isvs=df.to_dict('records'),
                           domains=domains,
                           statuses=statuses)


if __name__ == '__main__':
    app.run(debug=True)