# ISV Tracking System

A Flask-based web application for managing and tracking Independent Software Vendor (ISV) partnerships, certifications, and assessments. This system helps organizations streamline their ISV certification process and maintain detailed records of partner engagements.

## Features

### Dashboard
- Quick overview of ISV statistics (Active, In Progress, Completed)
- Recent activity feed
- Quick action shortcuts

### ISV Management
- Add new ISV partnerships
- Track certification types (Lite/Detailed)
- Multiple domain support
- Team member assignment
- Progress tracking with predefined tasks
- Document linking (Google Sheets/Docs integration)
- Start/End date tracking
- Point of Contact (POC) management

### Task Tracking
- Predefined task templates
- Status updates (Not Started/In Progress/Completed)
- Automatic progress calculation
- Task completion timestamps

### Historical Data
- Complete ISV partnership history
- Quarterly/Yearly filtering
- Domain-based filtering
- Status-based filtering
- Most recent ISVs view

## Tech Stack

- **Backend**: Python/Flask
- **Database**: Google BigQuery
- **Frontend**: HTML, JavaScript, Tailwind CSS
- **Authentication**: Google OAuth 2.0
- **Document Integration**: Google Workspace (Sheets/Docs)

## Prerequisites

- Python 3.x
- Google Cloud Platform account
- BigQuery enabled project
- Google Workspace account (for document integration)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/raheelkumar/gbq_app_v2.git
cd isv-tracking-system
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up Google Cloud credentials:
- Create a service account in Google Cloud Console
- Download the JSON credentials file
- Rename it to `gbq_app_service_account.json` and place it in the project root

5. Configure environment variables:
```bash
export FLASK_APP=app.py
export FLASK_ENV=development
```

## Database Setup

The application uses Google BigQuery with the following tables:
- `isv_data_store`: Main ISV information
- `isv_tasks`: Task tracking and progress
- `ISV_DETAILS_TEST`: Historical ISV data
- `ISV_Details`: Detailed ISV information with quarterly tracking

Table schemas are defined in the application code.

## Running the Application

1. Start the Flask development server:
```bash
flask run
```

2. Access the application at `http://localhost:5000`

## Project Structure

```
isv-tracking-system/
├── app.py                 # Main application file
├── forms.py              # Form definitions
├── domains.py            # Domain choices configuration
├── static/               # Static assets
│   ├── css/
│   └── js/
├── templates/            # HTML templates
│   ├── base.html
│   ├── index.html
│   ├── add_isv.html
│   ├── current_isvs.html
│   ├── edit_isv.html
│   ├── isv_history.html
│   └── isv_history_with_filter.html
└── requirements.txt      # Python dependencies

```

## Form Validation

The system includes comprehensive form validation for:
- ISV name uniqueness
- Google Sheets/Docs URL format
- Required fields
- Date range validation
- Multiple domain selection

## Security Features

- CSRF protection
- Google OAuth integration
- Secure document linking
- Input sanitization
- Form validation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License

Copyright (c) 2025 Raheel Kumar, Anushree Bhure

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Support

For support, please contact raheelrsingh@gmail.com