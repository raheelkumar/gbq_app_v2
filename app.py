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
credentials = service_account.Credentials.from_service_account_file('treasure_data_sa.json')
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
    isv_name = request.json.get('isv_name')
    query = f"""
    SELECT Sr_No
    FROM `{dataset_id}.{table_id}`
    WHERE LOWER(isv_name) = LOWER('{isv_name}')
    LIMIT 1
    """
    result = list(client.query(query).result())

    if result:
        return jsonify({
            'exists': True,
            'Sr_No': result[0].Sr_No
        })
    return jsonify({'exists': False})


@app.route('/get_max_sr_no', methods=['GET'])
def get_max_sr_no():
    query = f"""
    SELECT MAX(Sr_No) as max_sr_no
    FROM `{dataset_id}.{table_id}`
    """
    result = list(client.query(query).result())[0]
    return jsonify({'max_sr_no': result.max_sr_no or 0})


@app.route('/add_isv', methods=['GET', 'POST'])
def add_isv():
    form = ISVForm()
    if form.validate_on_submit():
        try:
            # Join multiple domains with commas
            domains = ','.join(form.domain.data)

            # Get Sr_No based on ISV existence
            isv_query = f"""
            SELECT Sr_No
            FROM `{dataset_id}.{table_id}`
            WHERE LOWER(isv_name) = LOWER('{form.isv_name.data}')
            LIMIT 1
            """
            isv_result = list(client.query(isv_query).result())

            if isv_result:
                sr_no = isv_result[0].Sr_No
            else:
                max_query = f"""
                SELECT MAX(Sr_No) as max_sr_no
                FROM `{dataset_id}.{table_id}`
                """
                max_result = list(client.query(max_query).result())[0]
                sr_no = (max_result.max_sr_no or 0) + 1

            # Prepare the data for BigQuery
            data_to_insert = {
                'Sr_No': sr_no,
                'isv_name': form.isv_name.data,
                'domain': domains,
                'certification_type': form.certification_type.data,
                'version': form.version.data,
                'description': form.description.data,
                'team_members': form.team_members.data,
                'start_date': form.start_date.data.strftime('%Y-%m-%d'),
                'end_date': form.end_date.data.strftime('%Y-%m-%d'),
                'poc': form.poc.data,
                'status': form.status.data,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # Insert into BigQuery
            table_ref = client.dataset(dataset_id).table(table_id)
            errors = client.insert_rows_json(table_ref, [data_to_insert])

            if errors == []:
                flash('ISV successfully added!', 'success')
                return redirect(url_for('current_isvs'))
            else:
                flash('Error occurred while adding ISV.', 'error')

        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

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


@app.route('/current_isvs')
def current_isvs():
    # Get ISVs with their tasks and completion percentage
    query = f"""
    WITH TaskStats AS (
        SELECT 
            isv_name,
            COUNT(*) as total_tasks,
            COUNTIF(status = 'completed') as completed_tasks
        FROM `{dataset_id}.isv_tasks`
        GROUP BY isv_name
    )
    SELECT 
        i.*,
        IFNULL(ts.completed_tasks, 0) as completed_tasks,
        IFNULL(ROUND(IFNULL(ts.completed_tasks, 0) * 100.0 / 5, 1), 0) as completion_percentage
    FROM `{dataset_id}.{table_id}` i
    LEFT JOIN TaskStats ts ON i.isv_name = ts.isv_name
    WHERE i.status != 'Completed'
    ORDER BY i.start_date DESC
    """

    isvs_query = client.query(query)
    # Convert Row objects to dictionaries
    isvs = [dict(row.items()) for row in isvs_query.result()]

    # Get tasks for each ISV
    for isv in isvs:
        tasks_query = f"""
        SELECT *
        FROM `{dataset_id}.isv_tasks`
        WHERE isv_name = '{isv['isv_name']}'
        ORDER BY task_name
        """
        tasks = list(client.query(tasks_query).result())

        # If no tasks exist, initialize them
        if not tasks:
            initialize_isv_tasks(isv['isv_name'])
            tasks = list(client.query(tasks_query).result())

        # Convert task Row objects to dictionaries
        isv['tasks'] = [dict(task.items()) for task in tasks]

    return render_template('current_isvs.html', isvs=isvs)


def initialize_isv_tasks(isv_name):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for task_name in PREDEFINED_TASKS:
        query = f"""
        INSERT INTO `{dataset_id}.isv_tasks`
        (isv_name, task_name, status, updated_at)
        VALUES
        ('{isv_name}', '{task_name}', 'not_started', '{now}')
        """
        client.query(query).result()


@app.route('/isv/<isv_name>', methods=['DELETE'])
def delete_isv(isv_name):
    try:
        # Delete tasks first
        delete_tasks_query = f"""
        DELETE FROM `{dataset_id}.isv_tasks`
        WHERE isv_name = '{isv_name}'
        """
        client.query(delete_tasks_query).result()

        # Delete ISV
        delete_isv_query = f"""
        DELETE FROM `{dataset_id}.{table_id}`
        WHERE isv_name = '{isv_name}'
        """
        client.query(delete_isv_query).result()

        return jsonify({'message': 'ISV deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/task/status', methods=['PUT'])
def update_task_status():
    try:
        data = request.json
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        query = f"""
        UPDATE `{dataset_id}.isv_tasks`
        SET status = '{data['status']}', updated_at = '{now}'
        WHERE isv_name = '{data['isv_name']}'
        AND task_name = '{data['task_name']}'
        """
        client.query(query).result()

        return jsonify({'message': 'Task status updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/isv/<isv_name>/edit', methods=['GET'])
def edit_isv(isv_name):
    query = f"""
    SELECT *
    FROM `{dataset_id}.{table_id}`
    WHERE isv_name = '{isv_name}'
    """
    result = list(client.query(query).result())[0]

    # Convert comma-separated domains back to list
    result_dict = dict(result.items())
    if result_dict.get('domain'):
        result_dict['domain'] = result_dict['domain'].split(',')

    form = ISVForm(data=result_dict)
    return render_template('edit_isv.html', form=form, isv_name=isv_name)


@app.route('/isv/<isv_name>/update', methods=['POST'])
def update_isv(isv_name):
    form = ISVForm()
    if form.validate_on_submit():
        try:
            # Join multiple domains with commas
            domains = ','.join(form.domain.data)

            query = f"""
            UPDATE `{dataset_id}.{table_id}`
            SET
                domain = '{domains}',
                certification_type = '{form.certification_type.data}',
                version = '{form.version.data}',
                description = '{form.description.data}',
                team_members = '{form.team_members.data}',
                start_date = '{form.start_date.data.strftime('%Y-%m-%d')}',
                end_date = '{form.end_date.data.strftime('%Y-%m-%d')}',
                poc = '{form.poc.data}',
                status = '{form.status.data}'
            WHERE isv_name = '{isv_name}'
            """
            client.query(query).result()

            flash('ISV updated successfully!', 'success')
            return redirect(url_for('current_isvs'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    return render_template('edit_isv.html', form=form, isv_name=isv_name)


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