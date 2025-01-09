# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, DateField, SelectMultipleField, URLField, validators
from wtforms.validators import DataRequired, Length, URL, ValidationError
from datetime import datetime
from urllib.parse import urlparse
from domains import DOMAIN_CHOICES

def validate_google_sheet(form, field):
    if not field.data:
        return
    parsed_url = urlparse(field.data)
    if not (parsed_url.netloc == 'docs.google.com' and '/spreadsheets/d/' in field.data):
        raise ValidationError('Please provide a valid Google Sheets URL')

def validate_google_doc(form, field):
    if not field.data:
        return
    parsed_url = urlparse(field.data)
    if not (parsed_url.netloc == 'docs.google.com' and '/document/d/' in field.data):
        raise ValidationError('Please provide a valid Google Docs URL')

class ISVForm(FlaskForm):
    isv_name = StringField('ISV Name', validators=[
        DataRequired(),
        Length(min=2, max=100)
    ])

    domain = SelectMultipleField('Domains (Hold Ctrl/Cmd to select multiple)',
                               choices=DOMAIN_CHOICES,
                               validators=[DataRequired()])

    certification_type = SelectField('Certification Type',
                                   choices=[
                                       ('lite', 'Lite'),
                                       ('detailed', 'Detailed'),
                                   ],
                                   validators=[DataRequired()])

    version = TextAreaField('Version', validators=[
        Length(max=500)
    ])

    description = TextAreaField('Description', validators=[
        DataRequired(),
        Length(min=10, max=500)
    ])

    team_members = TextAreaField('Team Members', validators=[
        DataRequired(),
        Length(min=2, max=200)
    ])

    start_date = DateField('Start Date', validators=[DataRequired()])
    end_date = DateField('End Date', validators=None)

    poc = StringField('POC', validators=[
        Length(max=100)
    ])

    status = SelectField('Status',
                        choices=[
                            ('not started', 'Not Started'),
                            ('in progress', 'In Progress'),
                            ('Completed', 'Completed')
                        ],
                        validators=[DataRequired()])

    percentage = StringField('Completion Percentage', validators=[
        Length(max=10)
    ])

    comments = TextAreaField('Comments', validators=[
        Length(max=1000)
    ])

    assessment_sheet = URLField('Assessment Sheet', validators=[validate_google_sheet])
    questions_doc = URLField('Questions Document', validators=[validate_google_doc])
    acceptance_criteria_sheet = URLField('Acceptance Criteria Sheet', validators=[validate_google_sheet])
    summary_doc1 = URLField('Summary Document', validators=[validate_google_doc])
    summary_doc2 = URLField('Summary Document 2', validators=[validate_google_doc])
    iol_doc = URLField('IOL Document', validators=[validate_google_doc])
    installation_doc = URLField('Installation Document', validators=[validate_google_doc])
    best_practices_doc = URLField('Best Practices Document', validators=[validate_google_doc])
    performance_doc = URLField('Performance Document', validators=[validate_google_doc])
    metric_observation_doc = URLField('Metric Observation Document', validators=[validate_google_doc])
    issue_bug_doc = URLField('Issue/Bug Document', validators=[validate_google_doc])