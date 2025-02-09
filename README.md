# Personal Library Manager

A Flask-based web application for managing your personal book collection, tracking lending history, and maintaining a reading list.

## Features

- Add books via ISBN lookup
- Track multiple copies of the same book
- Manage book lending and returns
- Maintain a reading list
- View lending history and metrics
- Admin panel with backup/restore functionality
- Search and filter books by various criteria

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

## Installation

1. Clone the repository:
```
bash
git clone https://github.com/Remillardj/PersonalLibrary
cd PersonalLibrary
```

2. Install dependencies, you can set up your own venv if you'd like:
```
pip install -r requirements.txt
```

3. Set up the database:
```
python manage.py db init
python manage.py db migrate
python manage.py db upgrade
```

4. Run the application:
```
flask run
```

5. Access the application at `http://localhost:5001`.

## Usage

- Add books using ISBN lookup or manual entry
- Track lending history and manage returns
- Use the admin panel for database maintenance, logs, and restoring deleted books or return history
- View metrics about your library and other useless statistics

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request