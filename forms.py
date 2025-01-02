# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, TextAreaField, DateField
from wtforms.validators import DataRequired, Length, ValidationError
from datetime import datetime


class ISVForm(FlaskForm):
    isv_name = StringField('ISV Name', validators=[
        DataRequired(),
        Length(min=2, max=100)
    ])

    domain = StringField('Domain', validators=[
        DataRequired(),
        Length(min=2, max=50)
    ])

    certification_type = SelectField('Certification Type',
                                     choices=[
                                         ('lite', 'Lite'),
                                         ('detailed', 'Detailed'),
                                     ],
                                     validators=[DataRequired()]
                                     )

    version_description = TextAreaField('Version Description', validators=[
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