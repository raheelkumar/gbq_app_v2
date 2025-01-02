# app.py
from flask import Flask, render_template, request, redirect, url_for, flash
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


@app.route('/current_isvs')
def current_isvs():
    query = f"""
    SELECT *
    FROM `{dataset_id}.{table_id}`
    WHERE status != 'Completed'
    ORDER BY start_date DESC
    """
    query_job = client.query(query)
    results = query_job.result()

    return render_template('current_isvs.html', isvs=results)


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