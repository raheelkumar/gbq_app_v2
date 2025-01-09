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
import io
import base64
from matplotlib.figure import Figure
import textwrap

app = Flask(__name__)
app.secret_key = os.urandom(24)

# BigQuery client setup
credentials = service_account.Credentials.from_service_account_file('gbq_app_service_account.json')
project_id = 'wwbq-treasuredata'
client = bigquery.Client(credentials=credentials, project=project_id)
dataset_id = "GBQ"
table_id = "isv_data_store"
new_table_id = "ISV_Details_new"


@app.route('/')
def index():
    # Get counts for dashboard
    counts_query = f"""
    SELECT
        COUNT(CASE WHEN status = 'not started' THEN 1 END) as inactive_count,
        COUNT(CASE WHEN status = 'in progress' THEN 1 END) as in_progress_count
    FROM `{dataset_id}.{new_table_id}`
    """
    counts_job = client.query(counts_query)
    counts_result = next(counts_job.result())

    # Get Completed count from ISV_details
    query = """Select count(*) AS completed FROM `wwbq-treasuredata.GBQ.ISV_Details` WHERE status='Completed';"""
    query_job = client.query(query)
    results = next(query_job.result())

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
                           inactive_count=counts_result.inactive_count or 0,
                           in_progress_count=counts_result.in_progress_count or 0,
                           completed_count=results.completed or 0,
                           recent_activities=recent_activities,
                           domain_count=len(DOMAIN_CHOICES) or 0,
                           domain_chart=domain_chart,
                           quarter_chart=quarter_chart,
                           pie_chart=pie_chart,
                           line_chart_qtr=line_chart_qtr,
                           hor_chart_dom=hor_chart_dom)



@app.route('/tracker')
def tracker():
    # Get counts for dashboard
    counts_query = f"""
    SELECT
        COUNT(CASE WHEN status = 'not started' THEN 1 END) as inactive_count,
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
def add_isv():
    form = ISVForm()
    if request.method == 'POST':
        print("Form Data:", request.form)
        print("Form is valid:", form.validate())
        print("Form Errors:", form.errors)

        if form.validate():
            try:
                # Get the maximum Sr_No
                max_srno_query = f"""
                SELECT MAX(Sr_No) as max_srno
                FROM `{dataset_id}.{new_table_id}`
                """
                max_srno_result = list(client.query(max_srno_query).result())[0]
                next_srno = (max_srno_result.max_srno or 0) + 1

                # Join multiple domains with commas
                domains = ','.join(form.domain.data) if isinstance(form.domain.data, list) else form.domain.data

                # Calculate Year, Quarter, and YearQuarter from start_date
                start_date = form.start_date.data
                year = start_date.year
                quarter_num = (start_date.month - 1) // 3 + 1
                quarter = f"Q{quarter_num}"
                year_quarter = f"FY{year}{quarter}"  # Changed format to FY2025Q1

                # Prepare the data for BigQuery
                data_to_insert = {
                    'Sr_No': next_srno,
                    'Tool_Name': form.isv_name.data,
                    'Domain': domains,
                    'Certification_Type': form.certification_type.data,
                    'Version': form.version.data or '',
                    'Description': form.description.data,
                    'Team_Members': form.team_members.data,
                    'Year': year,
                    'Quarter': quarter,
                    'YearQuarter': year_quarter,
                    'ISV_Start_Date': start_date.strftime('%Y-%m-%d'),
                    'POC': form.poc.data or '',
                    'Status': form.status.data,
                    'Percentage': float(form.percentage.data) if form.percentage.data else 0.0,
                    'Comments': form.comments.data or '',
                    'Assessment_Sheet': form.assessment_sheet.data or '',
                    'Questions_Doc': form.questions_doc.data or '',
                    'Acceptance_Criteria_Sheet': form.acceptance_criteria_sheet.data or '',
                    'Summary_Doc1': form.summary_doc1.data or '',
                    'Summary_Doc2': form.summary_doc2.data or '',
                    'IOL_Doc': form.iol_doc.data or '',
                    'Installation_Doc': form.installation_doc.data or '',
                    'Best_Practices_Doc': form.best_practices_doc.data or '',
                    'Performance_Doc': form.performance_doc.data or '',
                    'Metric_Observation_Doc': form.metric_observation_doc.data or '',
                    'Issue_Bug_Doc': form.issue_bug_doc.data or '',
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

                print("Data to insert:", data_to_insert)

                # Insert into BigQuery
                table_ref = client.dataset(dataset_id).table(new_table_id)
                errors = client.insert_rows_json(table_ref, [data_to_insert])

                if errors == []:
                    # Initialize tasks for the new ISV
                    initialize_isv_tasks(next_srno)

                    response_data = {'success': True, 'redirect': url_for('current_isvs')}
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify(response_data)
                    else:
                        flash('ISV successfully added!', 'success')
                        return redirect(url_for('current_isvs'))
                else:
                    print("BigQuery Errors:", errors)
                    error_response = {'success': False, 'error': str(errors)}
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify(error_response), 400
                    else:
                        flash(f'Error occurred while adding ISV: {str(errors)}', 'error')
                        return render_template('add_isv.html', form=form)
            except Exception as e:
                print("Exception:", str(e))
                error_response = {'success': False, 'error': str(e)}
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify(error_response), 500
                else:
                    flash(f'Error: {str(e)}', 'error')
                    return render_template('add_isv.html', form=form)
        else:
            # Form validation failed
            error_response = {
                'success': False,
                'error': 'Form validation failed',
                'errors': form.errors,
                'form_data': request.form.to_dict()
            }
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify(error_response), 400
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
def current_isvs():
    # Calculate current and last quarter
    today = datetime.now()
    current_year = today.year
    current_quarter_num = (today.month - 1) // 3 + 1
    current_quarter = f"Q{current_quarter_num}"

    # Calculate last quarter
    if current_quarter_num == 1:
        last_quarter = "Q4"
        last_quarter_year = current_year - 1
    else:
        last_quarter = f"Q{current_quarter_num - 1}"
        last_quarter_year = current_year

    # Create YearQuarter strings in FY format
    current_year_quarter = f"FY{current_year}{current_quarter}"
    last_year_quarter = f"FY{last_quarter_year}{last_quarter}"

    query = f"""
    WITH TaskStats AS (
        SELECT 
            Sr_No,
            COUNT(*) as total_tasks,
            COUNTIF(status = 'Completed') as completed_tasks
        FROM `{dataset_id}.isv_tasks_new`
        GROUP BY Sr_No
    )
    SELECT 
        i.Sr_No,
        i.Tool_Name as isv_name,
        i.Domain as domain,
        i.POC as poc,
        i.Status as status,
        i.ISV_Start_Date as start_date,
        i.YearQuarter,
        IFNULL(ts.completed_tasks, 0) as completed_tasks,
        IFNULL(ROUND(IFNULL(ts.completed_tasks, 0) * 100.0 / 5, 1), 0) as completion_percentage
    FROM `{dataset_id}.{new_table_id}` i
    LEFT JOIN TaskStats ts ON i.Sr_No = ts.Sr_No
    WHERE 
        -- Include all not started and in progress ISVs
        (i.Status IN ('not started', 'in progress'))
        OR 
        -- Include completed ISVs only from current and last quarter
        (i.Status = 'Completed' 
         AND i.YearQuarter IN ('{current_year_quarter}', '{last_year_quarter}'))
    ORDER BY 
        CASE 
            WHEN i.Status = 'in progress' THEN 1
            WHEN i.Status = 'not started' THEN 2
            WHEN i.Status = 'Completed' THEN 3
        END,
        i.ISV_Start_Date DESC
    """

    isvs_query = client.query(query)
    isvs = [dict(row.items()) for row in isvs_query.result()]

    # Get tasks for each ISV
    for isv in isvs:
        tasks_query = f"""
        SELECT 
            Sr_No,
            task_name,
            status,
            updated_at
        FROM `{dataset_id}.isv_tasks_new`
        WHERE Sr_No = {isv['Sr_No']}
        ORDER BY task_name
        """
        tasks = list(client.query(tasks_query).result())

        # Convert tasks to dictionaries and update status display
        isv['tasks'] = []
        for task in tasks:
            task_dict = dict(task.items())
            # Update status to match what should be displayed in UI
            if task_dict['status'] == 'completed':
                task_dict['status'] = 'Completed'
            isv['tasks'].append(task_dict)

    return render_template('current_isvs.html', isvs=isvs)

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

# Update delete ISV route
@app.route('/isv/<int:sr_no>', methods=['DELETE'])
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

            # Calculate Year, Quarter, and YearQuarter from start_date
            start_date = form.start_date.data
            year = start_date.year
            quarter = f"Q{(start_date.month - 1) // 3 + 1}"
            year_quarter = f"{year}-{quarter}"

            query = f"""
            UPDATE `{dataset_id}.{new_table_id}`
            SET
                Tool_Name = '{form.isv_name.data}',
                Domain = '{domains}',
                Certification_Type = '{form.certification_type.data}',
                Version = '{form.version.data}',
                Description = '{form.description.data}',
                Team_Members = '{form.team_members.data}',
                Year = {year},
                Quarter = '{quarter}',
                YearQuarter = '{year_quarter}',
                ISV_Start_Date = '{form.start_date.data.strftime('%Y-%m-%d')}',
                ISV_End_Date = '{form.end_date.data.strftime('%Y-%m-%d')}',
                POC = '{form.poc.data}',
                Status = '{form.status.data}',
                Percentage = {float(form.percentage.data) if form.percentage.data else 0.0},
                Comments = '{form.comments.data}',
                Assessment_Sheet = '{form.assessment_sheet.data}',
                Questions_Doc = '{form.questions_doc.data}',
                Acceptance_Criteria_Sheet = '{form.acceptance_criteria_sheet.data}',
                Summary_Doc1 = '{form.summary_doc1.data}',
                Summary_Doc2 = '{form.summary_doc2.data}',
                IOL_Doc = '{form.iol_doc.data}',
                Installation_Doc = '{form.installation_doc.data}',
                Best_Practices_Doc = '{form.best_practices_doc.data}',
                Performance_Doc = '{form.performance_doc.data}',
                Metric_Observation_Doc = '{form.metric_observation_doc.data}',
                Issue_Bug_Doc = '{form.issue_bug_doc.data}'
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

@app.route("/isv_history_with_filter", methods=["GET"])
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
    # Base query to get the most recent ISVs (sorted by ISV_Start_Date descending)
    query = """
    SELECT Sr_No, Tool_Name, Domain, Certification_Type, Version, Description, Team_Members, Year, Quarter, YearQuarter, POC, ISV_Start_Date, ISV_End_Date, Status, Percentage, Comments, Assessment_Sheet, Questions_Doc
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    WHERE Tool_Name IS NOT NULL
    ORDER BY ISV_Start_Date DESC
    LIMIT 10
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
        SELECT DISTINCT Year, Quarter FROM `wwbq-treasuredata.GBQ.ISV_Details`
        """
        distinct_query_job = client.query(distinct_query)
        distinct_results = list(distinct_query_job.result())
        years = sorted({row["Year"] for row in distinct_results})
        quarters = sorted({row["Quarter"] for row in distinct_results})

        # Render the same template with the most recent ISVs
        return render_template(
            "isv_history_with_filter.html",
            data=isv_details,
            years=years,
            quarters=quarters,
            selected_quarter="",
            selected_year="",
        )
    except Exception as e:
        return f"An error occurred: {e}"


#Krishnakanth's Code
@app.route('/dashboards')
def dashboards():  # Renamed from home() to match the route
    query = """Select status, count(*) as count FROM `wwbq-treasuredata.GBQ.ISV_Details` GROUP BY status"""
    query_job = client.query(query)
    results = query_job.result()
    isv_counts = {row.status: row.count for row in results}
    domain_chart = generate_domain_chart()
    quarter_chart = generate_quarter_chart()
    pie_chart = generate_pie_chart()
    line_chart_qtr = generate_qtr_growth_chart()
    hor_chart_dom = generate_top_domain_chart()
    total_domains = get_dist_domains_count()
    return render_template('home2.html',
                         domain_chart=domain_chart,
                         quarter_chart=quarter_chart,
                         isv_counts=isv_counts,
                         pie_chart=pie_chart,
                         total_domains=total_domains,
                         line_chart_qtr=line_chart_qtr,
                         hor_chart_dom=hor_chart_dom)


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
def list_isvs():
    query = "SELECT Tool_Name FROM `wwbq-treasuredata.GBQ.ISV_Details`"
    isvs = fetch_isvs(query)
    return render_template('list_isvs2.html', isvs=isvs)


@app.route('/list_by_domain', methods=['GET', 'POST'])
def list_by_domain():
    if request.method == 'POST':
        domain = request.form['domain']
        query = f"""
        SELECT Tool_Name FROM `wwbq-treasuredata.GBQ.ISV_Details` WHERE domain = '{domain}'
        """
        isvs = fetch_isvs(query)
        return render_template('list_by_domain2.html', domains=get_domains(), isvs=isvs, selected_domain=domain)
    return render_template('list_by_domain2.html', domains=get_domains(), isvs=None)



# List ISVs by Year and Quarter route
@app.route("/list_by_year_quarter", methods=["GET", "POST"])
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


# Helper function to generate domain chart
def generate_domain_chart():
    query = """
    SELECT domain, COUNT(*) AS isv_count
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    GROUP BY domain
    """
    results = client.query(query).result()
    domains, counts = [], []
    for row in results:
        domains.append(row.domain)
        counts.append(row.isv_count)

    plt.figure(figsize=(12, 6))
    plt.bar(domains, counts, color="lightgreen")
    plt.xlabel("domain")
    plt.ylabel("isv_count")
    plt.title("ISV Count by Domain")
    plt.xticks(rotation=75, ha='right')
    plt.tight_layout()
#    plt.grid(axis='y')

    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode()
    img.close()
    # chart_path = "static/domain_chart.png"
    # plt.savefig(chart_path)
    plt.close()
    return chart


# Helper function to generate quarter chart
def generate_quarter_chart():
    query = """
    SELECT CAST(year as INT64) as year, quarter, COUNT(*) AS isv_count
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    GROUP BY year, quarter ORDER BY year, quarter
    """
    results = client.query(query).result()

    data = {}
    years =set()
    quarters = ['Q1', 'Q2', 'Q3', 'Q4']
    for row in results:
        year = row.year
        quarter = row.quarter
        count = row.isv_count
        if quarter not in data:
            data[quarter] = {}
        data[quarter][year] = count
        years.add(year)

    years =sorted(years)
    x = range(len(years))
    bar_width =0.2

    fig = Figure(figsize=(7, 5))
    ax = fig.add_subplot(111)

    for i, quarter in enumerate(quarters):
        values = [data.get(quarter, {}).get(year, 0) for year in years]
        ax.bar([p + bar_width * i for p in x], values, bar_width, label=quarter)

    ax.set_title('ISV Count by Quarter')
    ax.set_xlabel('Years')
    ax.set_ylabel('ISV Count')
    ax.set_xticks([p + bar_width * len(quarters) / 2 for p in x])
    ax.set_xticklabels(years)
    ax.legend(title='Quarters')

    img = io.BytesIO()
    # plt.savefig(img, format="png")
    fig.savefig(img, format="png")
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode()
    img.close()
    # chart_path = "static/quarter_chart.png"
    # plt.savefig(chart_path)
    plt.close()
    return chart

def generate_pie_chart():
    query = """
    SELECT Year as year, COUNT(*) AS isv_count
    FROM `wwbq-treasuredata.GBQ.ISV_Details`
    GROUP BY year ORDER BY year
    """
    results = client.query(query).result()
    years, counts = [], []
    for row in results:
        years.append(str(int(row.year)))
        counts.append(row.isv_count)

    # fig = Figure()
    # ax= fig.subplots()
    fig, ax = plt.subplots()
    ax.pie(
        counts,
        labels=years,
        autopct='%1.1f%%',
        startangle=90,
        colors=['#FF9999', '#66B2FF', '#99FF99', '#FFCC99', '#C299FF'],
    )
    ax.set_title("ISV by Years")

    img = io.BytesIO()
    plt.savefig(img, format="png")
    img.seek(0)
    chart = base64.b64encode(img.getvalue()).decode('utf8')
    img.close()
    # chart_path = "static/domain_chart.png"
    # plt.savefig(chart_path)
    plt.close()
    return chart

# Fetch ISVs from BigQuery
def fetch_isvs(query):
    query_job = client.query(query)
    results = query_job.result()
    return [dict(row) for row in results]

def generate_qtr_growth_chart():
    query = """
    SELECT CONCAT(CAST(year as STRING), '-', quarter) AS period, Count(*) as tool_count 
    FROM `wwbq-treasuredata.GBQ.ISV_Details` 
    GROUP BY year, quarter ORDER BY year, quarter;
    """
    data =fetch_isvs(query)
    periods = [row['period'] for row in data]
    counts = [row['tool_count'] for row in data]

    plt.figure(figsize=(7, 6))
    plt.plot(periods, counts, marker='o', label="Tools Added")
    plt.title("Quarterly Growth Rate")
    plt.xlabel("Year-Quarter")
    plt.ylabel("ISV Count")
    plt.xticks(rotation=51, ha='right')
    plt.grid(True)
    plt.tight_layout()
    plt.legend()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    chart = base64.b64encode(buf.getvalue()).decode('utf8')
    plt.close()
    return chart

def generate_top_domain_chart():
    query = """
    Select Domain as domain, Count(*) as tool_count FROM `wwbq-treasuredata.GBQ.ISV_Details` 
    GROUP BY domain ORDER BY tool_count DESC limit 10;
    """
    data =fetch_isvs(query)
    domains = [row['domain'] for row in data]
    counts = [row['tool_count'] for row in data]

    wrapped_domains=[textwrap.fill(domain, width=20) for domain in domains]

    plt.figure(figsize=(7, 6))
    plt.barh(wrapped_domains, counts, color='lightblue')
    plt.title("Top domains by tool")
    plt.xlabel("tool_count")
    plt.ylabel("Domains")
#    plt.xticks(rotation=45, ha='right')
    plt.gca().invert_yaxis()
    plt.grid(axis='x', linestyle='--', alpha=0.7)
    plt.tight_layout()
#    plt.legend()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    chart = base64.b64encode(buf.getvalue()).decode('utf8')
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

@app.route('/logins')
def logins():
    #login logic
    return render_template('login.html')

if __name__ == '__main__':
    app.run(debug=True)