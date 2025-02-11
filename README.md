# Personal Library Manager

A Flask-based web application for managing your personal book collection, tracking lending history, and maintaining a reading list.

## Features

### Book Management
- Add books via ISBN lookup or search by title/author using Google or OpenLibrary APIs
- Edit book details and fill in missing information from Google/OpenLibrary using ISBN
- Track multiple copies of the same book
- Mark books as read or unread

### Lending Features
- Manage book lending and returns 
- View lending history and metrics
- Maintain a reading list

### Search & Organization
- Search and filter books by various criteria, including no categories, read status, title, author, ISBN or acquisition date range

### Administration
- Admin panel with backup/restore functionality
- Soft delete support for books and lending history with ability to restore or permanently delete

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