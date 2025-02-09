from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import Index

db = SQLAlchemy()

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(200), nullable=False)
    isbn = db.Column(db.String(13))  # No unique constraint
    copy_number = db.Column(db.Integer, default=1)
    publication_date = db.Column(db.String(10))
    pages = db.Column(db.Integer)
    chapters = db.Column(db.Integer)
    acquisition_date = db.Column(db.Date)
    categories = db.Column(db.String(500))
    tags = db.Column(db.String(500))
    notes = db.Column(db.Text)
    lendings = db.relationship('BookLending', backref='book', lazy=True)
    reading_list_items = db.relationship('ReadingListItem', backref='book', lazy=True)
    deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

class BookLending(db.Model):
    __tablename__ = 'book_lending'
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    borrower_name = db.Column(db.String(100), nullable=False)
    lent_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date)
    return_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

class ReadingListItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    order = db.Column(db.Integer, nullable=False)
    added_date = db.Column(db.Date, nullable=False, default=datetime.now().date())
    notes = db.Column(db.Text)
    completed = db.Column(db.Boolean, default=False)
    completed_date = db.Column(db.Date)

class RequestLog(db.Model):
    __tablename__ = 'request_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    method = db.Column(db.String(10))
    path = db.Column(db.String(500))
    endpoint = db.Column(db.String(500))
    status_code = db.Column(db.Integer)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(500))
    response_time = db.Column(db.Float)

class DatabaseBackup(db.Model):
    __tablename__ = 'database_backups'
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    size = db.Column(db.Integer)  # in bytes
    scheduled = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text) 