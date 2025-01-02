# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, DateField, SelectMultipleField, validators
from wtforms.validators import DataRequired, Length, ValidationError
from datetime import datetime
from wtforms import URLField
from wtforms.validators import URL, ValidationError
import re

DOMAIN_CHOICES = [
    ('business intelligence', 'Business Intelligence'),
    ('extract transform load', 'Extract Transform Load'),
    ('data integration', 'Data Integration'),
    ('data marketing', 'Data Marketing'),
    ('data governance', 'Data Governance'),
    ('machine learning', 'Machine Learning'),
    ('data analytics', 'Data Analytics'),
    ('data virtualization', 'Data Virtualization'),
    ('advanced analytics', 'Advanced Analytics'),
    ('master data management', 'Master Data Management'),
    ('reverse etl', 'Reverse ETL'),
    ('data security', 'Data Security'),
    ('data monitoring', 'Data Monitoring'),
    ('data observability', 'Data Observability'),
    ('spatial analytics', 'Spatial Analytics'),
    ('data quality', 'Data Quality'),
    ('customer data platform', 'Customer Data Platform'),
    ('marketing analytics', 'Marketing Analytics'),
    ('data activation', 'Data Activation'),
    ('behavioural data platform', 'Behavioural Data Platform'),
    ('graph database', 'Graph Database'),
    ('data modeler', 'Data Modeler'),
    ('data api', 'Data API'),
    ('mobile first bi', 'Mobile First BI'),
    ('data app development', 'Data App Development'),
    ('deep data observability', 'Deep Data Observability'),
    ('finops', 'FinOps'),
    ('dataops', 'DataOps'),
    ('real time etl', 'Real Time ETL'),
    ('product analytics platform', 'Product Analytics Platform'),
    ('synthetic data generation', 'Synthetic Data Generation'),
    ('data visualization', 'Data Visualization'),
    ('artificial intelligence', 'Artificial Intelligence'),
    ('generative ai', 'Generative AI'),
    ('automation', 'Automation'),
]

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
                                     validators=[DataRequired()]
                                     )

    version = TextAreaField('Version', validators=[
        DataRequired(),
        Length(min=10, max=500)
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
    end_date = DateField('End Date')

    poc = StringField('POC', validators=[
        DataRequired(),
        Length(min=2, max=100)
    ])

    status = SelectField('Status',
                         choices=[
                             ('not_started', 'Not Started'),
                             ('in_progress', 'In Progress'),
                             ('completed', 'Completed')
                         ],
                         validators=[DataRequired()]
                         )

    def validate_end_date(self, field):
        if field.data < self.start_date.data:
            raise ValidationError('End date must be after start date')