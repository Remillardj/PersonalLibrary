from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, g, send_file, make_response
from main import LibraryManager, BookDTO, format_isbn
from models import db, Book, BookLending, ReadingListItem, RequestLog, DatabaseBackup
from datetime import datetime, timedelta, date
from sqlalchemy import text
from sqlalchemy.sql import extract, distinct, desc, func
from flask_migrate import Migrate
import click
import logging
import requests
import os
import shutil
import humanize
import time
from flask_apscheduler import APScheduler
import csv
from io import StringIO
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Required for flash messages
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_POOL_SIZE'] = 10
app.config['SQLALCHEMY_MAX_OVERFLOW'] = 20
app.config['SQLALCHEMY_POOL_TIMEOUT'] = 30

# Initialize extensions
db.init_app(app)
migrate = Migrate(app, db)
library = LibraryManager()

# Add this after creating the Flask app
app.jinja_env.filters['format_isbn'] = format_isbn

# Define the database path
INSTANCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
DB_PATH = os.path.join(INSTANCE_PATH, 'library.db')
BACKUP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')

# Create necessary directories
if not os.path.exists(INSTANCE_PATH):
    os.makedirs(INSTANCE_PATH)
if not os.path.exists(BACKUP_FOLDER):
    os.makedirs(BACKUP_FOLDER)

scheduler = BackgroundScheduler()
scheduler.start()

# Create the application context
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
migrate = Migrate(app, db)

# Ensure the instance folder exists
if not os.path.exists('instance'):
    os.makedirs('instance')

# Create tables within application context
with app.app_context():
    db.create_all()

def get_db_size():
    """Get the size of the database file"""
    try:
        return os.path.getsize(DB_PATH)
    except:
        return 0

def perform_backup(notes="Scheduled backup"):
    """Function to perform the actual backup"""
    with app.app_context():
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(BACKUP_FOLDER, f'library_{timestamp}.db')
        
        # Create backup
        shutil.copy2(DB_PATH, backup_path)
        
        # Record backup in database
        size = os.path.getsize(backup_path)
        backup = DatabaseBackup(
            filename=f'library_{timestamp}.db',
            size=size,
            scheduled=True,
            notes=notes
        )
        db.session.add(backup)
        db.session.commit()

@app.cli.command("init-db")
def init_db():
    """Initialize the database."""
    try:
        with app.app_context():
            # Create all tables
            db.create_all()
            print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Error initializing database: {str(e)}")

@app.route('/')
def index():
    search_query = request.args.get('search', '').strip()
    category = request.args.get('category', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    query = Book.query.filter_by(deleted=False)
    
    if search_query:
        query = query.filter(
            db.or_(
                Book.title.ilike(f'%{search_query}%'),
                Book.author.ilike(f'%{search_query}%'),
                Book.isbn.ilike(f'%{search_query}%')
            )
        )
    
    if category:
        query = query.filter(Book.categories.contains([category]))
    
    pagination = query.order_by(Book.title).paginate(page=page, per_page=per_page, error_out=False)
    books = []
    for book in pagination.items:
        books.append({
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'isbn': book.isbn,
            'publication_date': book.publication_date,
            'pages': book.pages,
            'chapters': book.chapters,
            'acquisition_date': book.acquisition_date,
            'categories': book.categories,
            'tags': book.tags,
            'copy_number': book.copy_number,
            'deleted': book.deleted
        })
    categories = library.get_all_categories()
    
    return render_template('index.html', 
                         books=books, 
                         categories=categories,
                         search_query=search_query,
                         selected_category=category,
                         pagination=pagination,
                         total_pages=pagination.pages,
                         current_page=page,
                         total_books=pagination.total)

def get_next_copy_number(isbn):
    if not isbn:
        return 1
    # Get all non-deleted books with this ISBN
    existing_books = Book.query.filter(
        Book.isbn == isbn,
        Book.deleted == False
    ).order_by(Book.copy_number.desc()).all()
    
    if not existing_books:
        return 1
    return existing_books[0].copy_number + 1

@app.route('/add_book', methods=['GET', 'POST'])
def add_book():
    if request.method == 'POST':
        isbn = request.form.get('isbn')
        chapters = request.form.get('chapters', type=int)
        tags = request.form.get('tags', '')
        
        try:
            book_data = library.get_book_data_by_isbn(isbn)
            if not book_data:
                flash('Could not find book data for this ISBN', 'error')
                return redirect(url_for('add_book'))
            
            copy_number = get_next_copy_number(isbn)
            
            # Fix categories handling - ensure it's a string, not a list
            categories = book_data.get('categories', '')
            if isinstance(categories, list):
                categories = ', '.join(categories)
            
            book = Book(
                title=book_data['title'],
                author=book_data['author'],
                isbn=isbn,
                copy_number=copy_number,
                publication_date=book_data.get('publication_date'),
                pages=book_data.get('pages'),
                chapters=chapters,
                acquisition_date=datetime.now().date(),
                categories=categories,
                tags=tags,
            )
            
            db.session.add(book)
            db.session.commit()
            
            flash('Book added successfully!', 'success')
            return redirect(url_for('index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding book: {str(e)}', 'error')
            return redirect(url_for('add_book'))
    
    return render_template('add_book.html')

@app.route('/lookup_isbn/<isbn>')
def lookup_isbn(isbn):
    try:
        book_data = library.get_book_data_by_isbn(isbn)
        if book_data:
            return jsonify(book_data)
        return jsonify({'error': 'Book not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/book/<int:book_id>/delete')
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    book.deleted = True
    book.deleted_at = datetime.utcnow()
    
    # Mark all associated lending records as deleted
    lendings = BookLending.query.filter_by(book_id=book_id, deleted=False).all()
    for lending in lendings:
        lending.deleted = True
        lending.deleted_at = datetime.utcnow()
    
    db.session.commit()
    flash('Book moved to trash', 'success')
    return redirect(url_for('index'))

@app.route('/edit_book/<int:book_id>', methods=['GET', 'POST'])
def edit_book(book_id):
    book = library.get_book(book_id)
    if request.method == 'POST':
        categories = [cat.strip() for cat in request.form.get('categories', '').split(',') if cat.strip()]
        tags = [tag.strip() for tag in request.form.get('tags', '').split(',') if tag.strip()]
        
        # Update SQLAlchemy Book
        sqlalchemy_book = Book.query.get(book_id)
        if sqlalchemy_book:
            sqlalchemy_book.title = request.form['title']
            sqlalchemy_book.author = request.form['author']
            sqlalchemy_book.isbn = request.form['isbn']
            sqlalchemy_book.publication_date = request.form['publication_date']
            sqlalchemy_book.pages = int(request.form['pages'])
            sqlalchemy_book.chapters = int(request.form['chapters']) if request.form.get('chapters') else None
            sqlalchemy_book.acquisition_date = datetime.strptime(request.form['acquisition_date'], '%Y-%m-%d').date() if request.form['acquisition_date'] else None
            sqlalchemy_book.categories = ','.join(categories)
            sqlalchemy_book.tags = ','.join(tags)
            db.session.commit()
        
        # Update LibraryManager Book
        book.title = request.form['title']
        book.author = request.form['author']
        book.isbn = request.form['isbn']
        book.publication_date = request.form['publication_date']
        book.pages = int(request.form['pages'])
        book.chapters = int(request.form['chapters']) if request.form.get('chapters') else None
        book.acquisition_date = datetime.strptime(request.form['acquisition_date'], '%Y-%m-%d').date() if request.form['acquisition_date'] else None
        book.categories = categories
        book.tags = ','.join(tags)
        library.update_book(book)
        
        flash('Book updated successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('edit_book.html', book=book)

@app.route('/search_title', methods=['POST'])
def search_title():
    data = request.get_json()
    title = data.get('title')
    author = data.get('author')
    
    # Call the updated search method
    books = library.search_google_books_by_title_and_author(title, author)
    return jsonify(books)

@app.route('/book/<int:book_id>/lending', methods=['GET', 'POST'])
def lending_history(book_id):
    book = library.get_book(book_id)
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get search parameters
    borrower = request.args.get('borrower', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    status = request.args.get('status', '')
    
    # Build query with both book_id and deleted=False filters
    query = BookLending.query.filter_by(book_id=book_id, deleted=False)
    
    if borrower:
        query = query.filter(BookLending.borrower_name.ilike(f'%{borrower}%'))
    if date_from:
        query = query.filter(BookLending.lent_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(BookLending.lent_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
    
    # Add pagination
    pagination = query.order_by(BookLending.lent_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    if book.deleted:
        flash('This book has been deleted. Lending operations are disabled.', 'warning')
        
    if request.method == 'POST':
        if book.deleted:
            flash('Cannot add lending record to a deleted book.', 'error')
            return redirect(url_for('lending_history', book_id=book_id))
            
        active_lending = get_active_lending(book_id)
        borrower_name = request.form['borrower_name']
        
        # Check if book is already lent
        if active_lending and active_lending.borrower_name != borrower_name:
            flash('This book is already lent out to ' + active_lending.borrower_name, 'error')
            return redirect(url_for('lending_history', book_id=book_id))
        
        lending = BookLending(
            book_id=book_id,
            borrower_name=borrower_name,
            lent_date=datetime.strptime(request.form['lent_date'], '%Y-%m-%d').date(),
            due_date=datetime.strptime(request.form['due_date'], '%Y-%m-%d').date() if request.form.get('due_date') else None,
            return_date=datetime.strptime(request.form['return_date'], '%Y-%m-%d').date() if request.form.get('return_date') else None,
            notes=request.form.get('notes', '')
        )
        
        # If it's a re-lending, add a note about the previous borrower
        if active_lending and active_lending.borrower_name == borrower_name:
            lending.notes = f"Re-lent by {borrower_name}. " + lending.notes
        
        db.session.add(lending)
        db.session.commit()
        flash('Lending record added successfully!', 'success')
        return redirect(url_for('lending_history', book_id=book_id))
    
    return render_template('lending_history.html', 
                         book=book,
                         lending_history=pagination.items,
                         pagination=pagination,
                         get_active_lending=get_active_lending,
                         today=datetime.now().date(),
                         borrower=borrower,
                         date_from=date_from,
                         date_to=date_to,
                         status=status)

@app.route('/lending/<int:lending_id>/return', methods=['POST'])
def mark_returned(lending_id):
    try:
        lending = BookLending.query.get_or_404(lending_id)
        logging.info(f"Marking lending {lending_id} as returned for book {lending.book_id}")
        
        lending.return_date = datetime.now().date()
        db.session.commit()
        
        # Check if we came from a book's lending history
        referer = request.referrer
        if referer and '/book/' in referer and '/lending' in referer:
            logging.info(f"Redirecting back to book lending history for book {lending.book_id}")
            return redirect(url_for('lending_history', book_id=lending.book_id))
            
        logging.info("Redirecting to currently lent page")
        flash('Book marked as returned!', 'success')
        return redirect(url_for('currently_lent'))
        
    except Exception as e:
        logging.error(f"Error marking lending {lending_id} as returned: {str(e)}")
        db.session.rollback()
        flash('Error marking book as returned!', 'error')
        return redirect(url_for('currently_lent'))

@app.route('/lending/<int:lending_id>/delete')
def delete_lending(lending_id):
    lending = BookLending.query.get_or_404(lending_id)
    lending.deleted = True
    lending.deleted_at = datetime.utcnow()
    db.session.commit()
    flash('Lending record moved to trash', 'success')
    return redirect(url_for('lending_history', book_id=lending.book_id))

@app.route('/currently-lent')
def currently_lent():
    active_lendings = BookLending.query.join(Book).filter(
        BookLending.return_date == None,
        BookLending.deleted == False
    ).all()
    
    lent_books = []
    for lending in active_lendings:
        book = Book.query.get(lending.book_id)
        if book:
            # Include copy number in title if it exists and is > 1
            title = book.title
            if book.copy_number and book.copy_number > 1:
                title = f"{title} (Copy #{book.copy_number})"
                
            lent_books.append({
                'book': {
                    'id': book.id,
                    'title': title,
                    'author': book.author,
                    'deleted': book.deleted,
                    'copy_number': book.copy_number
                },
                'lending': lending
            })
    
    return render_template('currently_lent.html', lent_books=lent_books)

@app.route('/lending_history')
def all_lending_history():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    
    # Get search parameters
    title = request.args.get('title', '')
    borrower = request.args.get('borrower', '')
    status = request.args.get('status', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    today = datetime.now().date()
    
    # Build query
    query = BookLending.query
    
    # Apply filters
    if borrower:
        query = query.filter(BookLending.borrower_name.ilike(f'%{borrower}%'))
    if date_from:
        query = query.filter(BookLending.lent_date >= datetime.strptime(date_from, '%Y-%m-%d').date())
    if date_to:
        query = query.filter(BookLending.lent_date <= datetime.strptime(date_to, '%Y-%m-%d').date())
    
    # Status filters
    if status == 'returned':
        query = query.filter(BookLending.return_date != None)
    elif status == 'out':
        query = query.filter(BookLending.return_date == None)
    elif status == 'overdue':
        query = query.filter(
            BookLending.return_date == None,
            BookLending.due_date != None,
            BookLending.due_date < today
        )
    
    # Add pagination
    pagination = query.order_by(BookLending.lent_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    
    # Get the associated books
    lending_history = []
    for lending in pagination.items:
        book = Book.query.get(lending.book_id)
        if book:
            # Only filter by title if book exists and title is specified
            if title and title.lower() not in book.title.lower():
                continue
                
            # Include copy number in title if it exists and is > 1
            display_title = book.title
            if book.copy_number and book.copy_number > 1:
                display_title = f"{display_title} (Copy #{book.copy_number})"
                
            lending_history.append({
                'book': {
                    'id': book.id,
                    'title': display_title,
                    'author': book.author,
                    'deleted': book.deleted
                },
                'lending': lending
            })
    
    return render_template('all_lending_history.html',
                         lending_history=lending_history,
                         pagination=pagination,
                         title=title,
                         borrower=borrower,
                         status=status,
                         date_from=date_from,
                         date_to=date_to,
                         today=today)

def get_active_lending(book_id):
    """Helper function to get active lending for a book"""
    return BookLending.query.filter_by(
        book_id=book_id,
        return_date=None,
        deleted=False
    ).first()

# Make the function available to templates
app.jinja_env.globals.update(get_active_lending=get_active_lending)

@app.route('/reading_list')
def reading_list():
    # Get all books that aren't in the reading list
    subquery = db.session.query(ReadingListItem.book_id)
    available_books = Book.query.filter(~Book.id.in_(subquery)).all()
    
    # Get current date info
    current_date = datetime.now()
    month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                  'July', 'August', 'September', 'October', 'November', 'December']
    
    # Get the selected year from query params
    selected_year = request.args.get('year', str(current_date.year))
    
    # Get total count of all books in reading list
    total_books = ReadingListItem.query.count()
    
    # Query for reading list items
    query = ReadingListItem.query.join(Book)
    
    if selected_year and selected_year.isdigit():
        # For specific year, order by the item's order field
        query = query.filter(extract('year', ReadingListItem.added_date) == int(selected_year))
        results = query.order_by(ReadingListItem.order).all()
    else:
        # For all years, order by date (newest first) then by order within same date
        results = query.order_by(ReadingListItem.added_date.desc(), ReadingListItem.order).all()
    
    # Create reading list with sequential numbers
    reading_list = []
    for index, item in enumerate(results, start=1):
        reading_list.append({
            'item': item,
            'book': item.book,
            'display_order': index
        })
    
    filtered_count = len(reading_list)
    
    # Get available years for dropdown
    year_query = db.session.query(
        distinct(extract('year', ReadingListItem.added_date).label('year'))
    ).order_by(text('year DESC'))
    
    available_years = [int(year[0]) for year in year_query.all()]
    
    return render_template('reading_list.html',
                         reading_list=reading_list,
                         available_books=available_books,
                         available_years=available_years,
                         selected_year=int(selected_year) if selected_year and selected_year.isdigit() else None,
                         current_year=current_date.year,
                         month_names=month_names,
                         total_books=total_books,
                         filtered_count=filtered_count)

@app.route('/reading_list/add/<int:book_id>', methods=['POST'])
def add_to_reading_list(book_id):
    # Get the last order number
    last_item = ReadingListItem.query.order_by(ReadingListItem.order.desc()).first()
    next_order = (last_item.order + 1) if last_item else 1
    
    # Parse the added_date if provided, otherwise use today
    added_date_str = request.form.get('added_date')
    if added_date_str:
        added_date = datetime.strptime(added_date_str, '%Y-%m-%d').date()
    else:
        added_date = datetime.now().date()
    
    item = ReadingListItem(
        book_id=book_id,
        order=next_order,
        added_date=added_date,
        notes=request.form.get('notes', '')
    )
    
    db.session.add(item)
    db.session.commit()
    flash('Book added to reading list!', 'success')
    return redirect(url_for('reading_list'))

@app.route('/reading_list/reorder', methods=['POST'])
def reorder_reading_list():
    items = request.json.get('items', [])
    for item_data in items:
        item = ReadingListItem.query.get(item_data['id'])
        if item:
            item.order = item_data['order']
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/reading_list/complete/<int:item_id>', methods=['POST'])
def complete_reading_list_item(item_id):
    item = ReadingListItem.query.get_or_404(item_id)
    item.completed = True
    item.completed_date = datetime.now().date()
    db.session.commit()
    flash('Book marked as read!', 'success')
    return redirect(url_for('reading_list'))

@app.route('/reading_list/remove/<int:item_id>', methods=['POST'])
def remove_from_reading_list(item_id):
    item = ReadingListItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash('Book removed from reading list!', 'success')
    return redirect(url_for('reading_list'))

@app.route('/reading_list/add_with_date', methods=['POST'])
def add_to_reading_list_with_date():
    book_id = request.form.get('book_id')
    year = int(request.form.get('year'))
    month = request.form.get('month', '1')  # Default to January if not specified
    month = int(month) if month else 1
    day = request.form.get('day', '1')  # Default to 1st if not specified
    day = int(day) if day and day.isdigit() else 1
    notes = request.form.get('notes', '')

    # Set the date to the specified day (or 1st if not specified)
    added_date = datetime(year, month, day).date()

    # Get the last order number
    last_item = ReadingListItem.query.order_by(ReadingListItem.order.desc()).first()
    next_order = (last_item.order + 1) if last_item else 1
    
    item = ReadingListItem(
        book_id=book_id,
        order=next_order,
        added_date=added_date,
        notes=notes
    )
    
    db.session.add(item)
    db.session.commit()
    flash('Book added to reading list!', 'success')
    return redirect(url_for('reading_list'))

@app.route('/reading_list/edit_date', methods=['POST'])
def edit_reading_list_date():
    item_id = request.form.get('item_id')
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    day = int(request.form.get('day'))
    
    item = ReadingListItem.query.get_or_404(item_id)
    item.added_date = datetime(year, month, day).date()
    db.session.commit()
    
    flash('Date updated successfully!', 'success')
    return redirect(url_for('reading_list'))

@app.route('/reading_list/edit_read_date', methods=['POST'])
def edit_reading_list_read_date():
    item_id = request.form.get('item_id')
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    day = int(request.form.get('day'))
    
    item = ReadingListItem.query.get_or_404(item_id)
    item.completed_date = datetime(year, month, day).date()
    db.session.commit()
    
    flash('Read date updated successfully!', 'success')
    return redirect(url_for('reading_list'))

@app.route('/reading_list/unmark/<int:item_id>', methods=['POST'])
def unmark_reading_list_item(item_id):
    try:
        logging.info(f"Starting unmark process for book {item_id}")
        item = ReadingListItem.query.get_or_404(item_id)
        logging.info(f"Found item: {item.id}, Current status - completed: {item.completed}, date: {item.completed_date}")
        
        # Explicitly set both fields
        item.completed = False
        item.completed_date = None
        db.session.add(item)
        
        try:
            db.session.commit()
            logging.info("Changes committed successfully")
        except Exception as commit_error:
            logging.error(f"Error during commit: {str(commit_error)}")
            db.session.rollback()
            raise
            
        # Verify the changes
        db.session.refresh(item)
        logging.info(f"After update - completed: {item.completed}, date: {item.completed_date}")
        
        flash('Book unmarked as read!', 'success')
        return redirect(url_for('reading_list'))
        
    except Exception as e:
        logging.error(f"Error unmarking book {item_id}: {str(e)}")
        db.session.rollback()
        flash('Error: Failed to unmark book as read', 'error')
        return redirect(url_for('reading_list'))

@app.route('/metrics')
def metrics():
    from datetime import date, datetime  # Add this at the top of the function
    
    # Basic statistics
    total_books = Book.query.filter_by(deleted=False).count()
    total_pages = db.session.query(func.sum(Book.pages)).filter(Book.deleted == False).scalar() or 0
    total_chapters = db.session.query(func.sum(Book.chapters)).filter(Book.deleted == False).scalar() or 0
    
    # Category statistics
    category_counts = {}
    books = Book.query.filter_by(deleted=False).all()
    for book in books:
        if book.categories:
            # Split categories and properly clean them
            categories = book.categories.split(',')
            categories = [cat.strip() for cat in categories if cat.strip()]  # Remove empty strings and whitespace
            for category in categories:
                if category:  # Extra check to ensure no empty categories
                    category_counts[category] = category_counts.get(category, 0) + 1
    
    # Get current date for calculations
    today = date.today()
    
    # Lending statistics
    active_lendings = BookLending.query.join(Book).filter(
        BookLending.return_date == None,
        Book.deleted == False
    ).all()
    
    currently_lent = len(active_lendings)
    total_returned = BookLending.query.join(Book).filter(
        BookLending.return_date != None,
        Book.deleted == False
    ).count()
    
    # Calculate overdue
    overdue = BookLending.query.join(Book).filter(
        BookLending.return_date == None,
        Book.deleted == False,
        BookLending.lent_date < (today - timedelta(days=14))
    ).count()
    
    # Advanced statistics
    avg_pages = total_pages / total_books if total_books > 0 else 0
    longest_book = Book.query.filter_by(deleted=False).order_by(Book.pages.desc()).first()
    books_this_year = Book.query.filter(
        Book.deleted == False,
        Book.acquisition_date >= datetime(date.today().year, 1, 1)
    ).count()
    
    # Reading list statistics
    reading_list_total = ReadingListItem.query.join(Book).filter(Book.deleted == False).count()
    reading_list_completed = ReadingListItem.query.join(Book).filter(
        Book.deleted == False,
        ReadingListItem.completed == True
    ).count()
    
    # Update most borrowed book query
    most_borrowed_book = db.session.query(
        Book,
        func.count(BookLending.id).label('borrow_count')
    ).join(BookLending).filter(Book.deleted == False).group_by(Book.id).order_by(text('borrow_count DESC')).first()
    
    # Monthly lending trends (last 12 months)
    twelve_months_ago = today - timedelta(days=365)
    monthly_lendings = db.session.query(
        func.strftime('%Y-%m', BookLending.lent_date).label('month'),
        func.count(BookLending.id).label('count')
    ).filter(
        BookLending.lent_date >= twelve_months_ago
    ).group_by(
        func.strftime('%Y-%m', BookLending.lent_date)
    ).order_by(text('month DESC')).all()
    
    # Format the results to include full month name
    formatted_monthly_lendings = []
    for month_str, count in monthly_lendings:
        year, month = month_str.split('-')
        date = datetime(int(year), int(month), 1)
        formatted_monthly_lendings.append((date, count))
    
    # Request statistics
    total_requests = RequestLog.query.count()
    get_requests = RequestLog.query.filter_by(method='GET').count()
    post_requests = RequestLog.query.filter_by(method='POST').count()
    success_requests = RequestLog.query.filter(RequestLog.status_code.between(200, 299)).count()
    error_requests = RequestLog.query.filter(RequestLog.status_code >= 400).count()

    # Reading metrics
    reading_rate = reading_list_completed / (datetime.now() - datetime(datetime.now().year, 1, 1)).days * 365
    avg_completion_time = db.session.query(
        func.avg(
            func.julianday(ReadingListItem.completed_date) - 
            func.julianday(ReadingListItem.added_date)
        )
    ).filter(ReadingListItem.completed == True).scalar() or 0

    # Lending patterns
    avg_lending_duration = db.session.query(
        func.avg(
            func.julianday(BookLending.return_date) - 
            func.julianday(BookLending.lent_date)
        )
    ).filter(BookLending.return_date != None).scalar() or 0
    
    # Get unique borrowers count
    unique_borrowers = db.session.query(func.count(distinct(BookLending.borrower_name))).scalar()
    
    # Reading metrics
    avg_completion_time = db.session.query(
        func.avg(
            func.julianday(ReadingListItem.completed_date) - 
            func.julianday(ReadingListItem.added_date)
        )
    ).filter(ReadingListItem.completed == True).scalar() or 0

    # Lending patterns
    avg_lending_duration = db.session.query(
        func.avg(
            func.julianday(BookLending.return_date) - 
            func.julianday(BookLending.lent_date)
        )
    ).filter(BookLending.return_date != None).scalar() or 0
    
    # Update most frequent borrower query
    most_frequent_borrower = db.session.query(
        BookLending.borrower_name,
        func.count(BookLending.id).label('borrow_count')
    ).group_by(BookLending.borrower_name).order_by(text('borrow_count DESC')).first()

    return render_template('metrics.html',
                         total_books=total_books,
                         total_pages=total_pages,
                         total_chapters=total_chapters,
                         category_counts=category_counts,
                         total_lendings=currently_lent,
                         currently_lent=currently_lent,
                         total_returned=total_returned,
                         overdue=overdue,
                         unique_borrowers=unique_borrowers,
                         reading_list_total=reading_list_total,
                         reading_list_completed=reading_list_completed,
                         monthly_lendings=formatted_monthly_lendings,
                         total_requests=total_requests,
                         get_requests=get_requests,
                         post_requests=post_requests,
                         success_requests=success_requests,
                         error_requests=error_requests,
                         avg_pages=avg_pages,
                         longest_book=longest_book,
                         books_this_year=books_this_year,
                         reading_rate=reading_rate,
                         avg_completion_time=avg_completion_time,
                         avg_lending_duration=avg_lending_duration,
                         most_borrowed_book=most_borrowed_book,
                         most_frequent_borrower=most_frequent_borrower)

@app.route('/admin')
def admin_panel():
    import humanize
    
    # Get deleted books
    deleted_books = Book.query.filter_by(deleted=True).order_by(Book.deleted_at.desc()).all()
    
    # Get deleted lendings
    deleted_lendings = BookLending.query.join(Book).filter(
        BookLending.deleted == True
    ).order_by(BookLending.deleted_at.desc()).all()
    
    # Get request logs with pagination
    page = request.args.get('page', 1, type=int)
    logs = RequestLog.query.order_by(RequestLog.timestamp.desc()).paginate(
        page=page, per_page=10, error_out=False)
    
    # Get database size using existing function
    db_size = get_db_size()
    
    # Get total backups and calculate total backup size
    backups = DatabaseBackup.query.all()
    total_backups = len(backups)
    backups_size = sum(os.path.getsize(os.path.join(BACKUP_FOLDER, backup.filename)) 
                      for backup in backups if os.path.exists(os.path.join(BACKUP_FOLDER, backup.filename)))
    
    return render_template('admin/panel.html', 
                         deleted_books=deleted_books,
                         deleted_lendings=deleted_lendings,
                         humanize=humanize,
                         db_size=db_size,
                         total_backups=total_backups,
                         backups_size=backups_size,
                         logs=logs,
                         backups=backups)

@app.route('/admin/backup/download/<int:backup_id>')
def download_backup(backup_id):
    backup = DatabaseBackup.query.get_or_404(backup_id)
    return send_file(
        os.path.join(BACKUP_FOLDER, backup.filename),
        as_attachment=True,
        download_name=backup.filename
    )

@app.route('/admin/backup/<int:backup_id>/delete', methods=['POST'])
def delete_backup(backup_id):
    backup = DatabaseBackup.query.get_or_404(backup_id)
    try:
        # Delete file
        os.remove(os.path.join(BACKUP_FOLDER, backup.filename))
        # Delete database record
        db.session.delete(backup)
        db.session.commit()
        flash('Backup deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting backup: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/backup/cleanup', methods=['POST'])
def cleanup_old_backups():
    try:
        # Delete backups older than 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        old_backups = DatabaseBackup.query.filter(
            DatabaseBackup.created_at < thirty_days_ago
        ).all()
        
        for backup in old_backups:
            try:
                os.remove(os.path.join(BACKUP_FOLDER, backup.filename))
                db.session.delete(backup)
            except:
                continue
                
        db.session.commit()
        flash(f'Cleaned up {len(old_backups)} old backups', 'success')
    except Exception as e:
        flash(f'Error cleaning up backups: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/logs/export')
def export_logs():
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Timestamp', 'Method', 'Endpoint', 'Status', 'Response Time', 'IP', 'User Agent'])
    
    logs = RequestLog.query.order_by(RequestLog.timestamp.desc()).all()
    for log in logs:
        cw.writerow([
            log.timestamp,
            log.method,
            log.endpoint,
            log.status_code,
            f"{log.response_time:.2f}s",
            log.ip_address,
            log.user_agent
        ])
    
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=logs.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# Backup scheduling routes
@app.route('/admin/schedule', methods=['POST'])
def schedule_backup():
    try:
        schedule_type = request.form.get('schedule_type')
        
        # Remove existing scheduled backups
        for job in scheduler.get_jobs():
            job.remove()
            
        if schedule_type == 'daily':
            hour = int(request.form.get('hour', 0))
            minute = int(request.form.get('minute', 0))
            scheduler.add_job(
                perform_backup,
                CronTrigger(hour=hour, minute=minute),
                id='daily_backup',
                args=['Daily scheduled backup']
            )
        elif schedule_type == 'weekly':
            day = int(request.form.get('day', 0))  # 0-6 (Monday-Sunday)
            hour = int(request.form.get('hour', 0))
            minute = int(request.form.get('minute', 0))
            scheduler.add_job(
                perform_backup,
                CronTrigger(day_of_week=day, hour=hour, minute=minute),
                id='weekly_backup',
                args=['Weekly scheduled backup']
            )
        
        flash('Backup schedule updated successfully', 'success')
    except Exception as e:
        flash(f'Error scheduling backup: {str(e)}', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/schedule/remove', methods=['POST'])
def remove_schedule():
    try:
        # Remove all scheduled jobs
        scheduler.remove_all_jobs()
        
        # Log the action
        logging.info("All backup schedules removed")
        
        flash('Backup schedule has been removed successfully', 'success')
    except Exception as e:
        logging.error(f"Error removing backup schedule: {str(e)}")
        flash(f'Error removing backup schedule: {str(e)}', 'error')
    
    return redirect(url_for('admin_panel'))

@app.route('/debug_book/<int:book_id>')
def debug_book(book_id):
    book = Book.query.get_or_404(book_id)
    return {
        'title': book.title,
        'categories_raw': book.categories,
        'categories_type': type(book.categories).__name__
    }

@app.route('/admin/backup', methods=['POST'])
def create_backup():
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(BACKUP_FOLDER, f'library_{timestamp}.db')
        
        # Create backup
        shutil.copy2(DB_PATH, backup_path)
        
        # Record backup in database
        size = os.path.getsize(backup_path)
        backup = DatabaseBackup(
            filename=f'library_{timestamp}.db',
            size=size,
            notes=request.form.get('notes', '')
        )
        db.session.add(backup)
        db.session.commit()
        
        flash('Backup created successfully!', 'success')
    except Exception as e:
        flash(f'Error creating backup: {str(e)}', 'error')
        logging.error(f"Backup error: {str(e)}")
    
    return redirect(url_for('admin_panel'))

@app.route('/admin/trash/book/<int:book_id>/restore', methods=['POST'])
def restore_book(book_id):
    book = Book.query.get_or_404(book_id)
    book.deleted = False
    book.deleted_at = None
    
    # Restore all associated lending records that were deleted at the same time
    lendings = BookLending.query.filter_by(
        book_id=book_id, 
        deleted=True,
        deleted_at=book.deleted_at
    ).all()
    
    for lending in lendings:
        lending.deleted = False
        lending.deleted_at = None
    
    db.session.commit()
    flash('Book and associated lending records restored successfully', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/trash/lending/<int:lending_id>/restore', methods=['POST'])
def restore_lending(lending_id):
    lending = BookLending.query.get_or_404(lending_id)
    lending.deleted = False
    lending.deleted_at = None
    db.session.commit()
    flash('Lending record restored successfully', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/test')
def test():
    return "App is working"

@app.before_request
def before_request():
    g.start_time = time.time()

@app.after_request
def after_request(response):
    try:
        if hasattr(g, 'start_time'):
            response_time = time.time() - g.start_time
            user_agent = request.headers.get('User-Agent', '')
            log = RequestLog(
                timestamp=datetime.utcnow(),
                method=request.method,
                path=request.path,
                endpoint=request.endpoint or '',
                status_code=response.status_code,
                ip_address=request.remote_addr or '',
                user_agent=user_agent,
                response_time=response_time
            )
            db.session.add(log)
            db.session.commit()
    except Exception as e:
        app.logger.error(f"Failed to log request: {str(e)}")
        db.session.rollback()
    
    return response

def format_isbn(isbn):
    """Format ISBN by adding hyphens"""
    if not isbn:
        return ''
    isbn = isbn.replace('-', '')  # Remove existing hyphens
    if len(isbn) == 13:  # ISBN-13
        return f"{isbn[0:3]}-{isbn[3]}-{isbn[4:7]}-{isbn[7:12]}-{isbn[12]}"
    elif len(isbn) == 10:  # ISBN-10
        return f"{isbn[0]}-{isbn[1:4]}-{isbn[4:9]}-{isbn[9]}"
    return isbn  # Return unformatted if not 10 or 13 digits

# Register the filter
app.jinja_env.filters['format_isbn'] = format_isbn

@app.route('/admin/fix-copy-numbers', methods=['POST'])
def fix_copy_numbers():
    # Group non-deleted books by ISBN
    books = Book.query.filter(
        Book.deleted == False,
        Book.isbn != None,
        Book.isbn != ''
    ).order_by(Book.id).all()
    
    isbn_groups = {}
    for book in books:
        if book.isbn not in isbn_groups:
            isbn_groups[book.isbn] = []
        isbn_groups[book.isbn].append(book)
    
    # Update copy numbers
    for isbn, book_group in isbn_groups.items():
        for i, book in enumerate(book_group, 1):
            if book.copy_number != i:
                book.copy_number = i
                db.session.add(book)
    
    db.session.commit()
    flash('Copy numbers have been updated!', 'success')
    return redirect(url_for('admin_panel'))

if __name__ == '__main__':
    app.run(debug=True) 