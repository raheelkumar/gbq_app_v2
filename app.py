# app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from google.cloud import bigquery
from datetime import datetime
from google.oauth2 import service_account
from forms import ISVForm
import os
import uuid
from datetime import datetime
from flask import jsonify, request


app = Flask(__name__)
app.secret_key = os.urandom(24)

# BigQuery client setup
credentials = service_account.Credentials.from_service_account_file('treasure_data_sa.json')
project_id = 'wwbq-treasuredata'
client = bigquery.Client(credentials=credentials, project=project_id)
dataset_id = "GBQ"
table_id = "ISV_DETAILS_TEST_NEW"


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


@app.route('/add_isv', methods=['GET', 'POST'])
def add_isv():
    form = ISVForm()
    if form.validate_on_submit():
        try:
            # Prepare the data for BigQuery
            rows_to_insert = [{
                'isv_name': form.isv_name.data,
                'domain': form.domain.data,
                'certification_type': form.certification_type.data,
                'version_description': form.version_description.data,
                'team_members': form.team_members.data,
                'start_date': form.start_date.data.strftime('%Y-%m-%d'),
                'end_date': form.end_date.data.strftime('%Y-%m-%d'),
                'poc': form.poc.data,
                'status': form.status.data,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }]

            # Insert into BigQuery
            table_ref = client.dataset(dataset_id).table(table_id)
            errors = client.insert_rows_json(table_ref, rows_to_insert)

            if errors == []:
                flash('ISV successfully added!', 'success')
                return redirect(url_for('current_isvs'))
            else:
                flash('Error occurred while adding ISV.', 'error')

        except Exception as e:
            flash(f'Error: {str(e)}', 'error')

    return render_template('add_isv.html', form=form)


# Get ISVs with their tasks and completion percentage
@app.route('/current_isvs')
def current_isvs():
    query = f"""
    WITH TaskStats AS (
        SELECT 
            isv_name,
            COUNT(*) as total_tasks,
            COUNTIF(status = 'completed') as completed_tasks
        FROM `{dataset_id}.ISV_TASKS_TEST`
        GROUP BY isv_name
    )
    SELECT 
        i.*,
        IFNULL(ts.total_tasks, 0) as total_tasks,
        IFNULL(ts.completed_tasks, 0) as completed_tasks,
        IFNULL(ROUND(ts.completed_tasks * 100.0 / ts.total_tasks, 1), 0) as completion_percentage
    FROM `{dataset_id}.ISV_DETAILS_TEST_NEW` i
    LEFT JOIN TaskStats ts ON i.isv_name = ts.isv_name
    WHERE i.status != 'completed'
    ORDER BY i.start_date DESC
    """

    isvs_query = client.query(query)
    isvs = list(isvs_query.result())

    # Get tasks for each ISV
    for isv in isvs:
        tasks_query = f"""
        SELECT *
        FROM `{dataset_id}.ISV_TASKS_TEST`
        WHERE isv_name = '{isv.isv_name}'
        ORDER BY created_at DESC
        """
        isv.task_name = list(client.query(tasks_query).result())

    return render_template('current_isvs.html', isvs=isvs)


# Delete ISV
@app.route('/isv/<path:isv_name>', methods=['DELETE'])
def delete_isv(isv_name):
    try:
        # Delete associated tasks first
        delete_tasks_query = f"""
        DELETE FROM `{dataset_id}.ISV_TASKS_TEST`
        WHERE isv_name = '{isv_name}'
        """
        client.query(delete_tasks_query).result()

        # Delete ISV
        delete_isv_query = f"""
        DELETE FROM `{dataset_id}.ISV_DETAILS_TEST`
        WHERE isv_name = '{isv_name}'
        """
        client.query(delete_isv_query).result()

        return jsonify({'message': 'ISV deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Add new task
@app.route('/task', methods=['POST'])
def add_task():
    try:
        data = request.json
        task_id = str(uuid.uuid4())  # Still using UUID for task_id as it needs to be unique
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        query = f"""
        INSERT INTO `{dataset_id}.ISV_TASKS_TEST`
        (task_id, isv_name, task_name, task_description, status, created_at, updated_at)
        VALUES
        ('{task_id}', '{data['isv_name']}', '{data['task_name']}', 
         '{data.get('task_description', '')}', 'not_started', '{now}', '{now}')
        """

        client.query(query).result()
        return jsonify({'message': 'Task added successfully'}), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Update task status
@app.route('/task/<task_id>/status', methods=['PUT'])
def update_task_status(task_id):
    try:
        data = request.json
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        query = f"""
        UPDATE `{dataset_id}.ISV_TASKS_TEST`
        SET status = '{data['status']}', updated_at = '{now}'
        WHERE task_id = '{task_id}'
        """

        client.query(query).result()
        return jsonify({'message': 'Task status updated successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Delete task
@app.route('/task/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    try:
        query = f"""
        DELETE FROM `{dataset_id}.ISV_TASKS_TEST`
        WHERE task_id = '{task_id}'
        """

        client.query(query).result()
        return jsonify({'message': 'Task deleted successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/isv_history')
def isv_history():
    query = f"""
    SELECT *
    FROM `{dataset_id}.{table_id}`
    WHERE status = 'Completed'
    ORDER BY end_date DESC
    """
    query_job = client.query(query)
    results = query_job.result()

    return render_template('isv_history.html', isvs=results)


if __name__ == '__main__':
    app.run(debug=True)