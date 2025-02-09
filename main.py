from datetime import datetime
import isbnlib
from dataclasses import dataclass
from typing import List
import requests
from sqlalchemy import or_, func
from models import db, Book as SQLBook

@dataclass
class BookDTO:
    title: str
    author: str
    isbn: str
    publication_date: str
    pages: int
    chapters: int
    acquisition_date: str
    categories: List[str]
    tags: List[str] = None
    id: int = None

class LibraryManager:
    def __init__(self):
        pass

    def add_book(self, book_data):
        book = SQLBook(
            title=book_data.title,
            author=book_data.author,
            isbn=book_data.isbn,
            publication_date=book_data.publication_date,
            pages=book_data.pages,
            chapters=book_data.chapters,
            acquisition_date=datetime.strptime(book_data.acquisition_date, '%Y-%m-%d').date() if book_data.acquisition_date else None,
            categories=','.join(book_data.categories) if book_data.categories else None,
            tags=','.join(book_data.tags) if book_data.tags else None
        )
        db.session.add(book)
        db.session.commit()
        return book.id

    def get_book(self, book_id):
        return SQLBook.query.get(book_id)

    def update_book(self, book_data):
        book = SQLBook.query.get(book_data.id)
        if book:
            book.title = book_data.title
            book.author = book_data.author
            book.isbn = book_data.isbn
            book.publication_date = book_data.publication_date
            book.pages = book_data.pages
            book.chapters = book_data.chapters
            book.acquisition_date = datetime.strptime(book_data.acquisition_date, '%Y-%m-%d').date() if book_data.acquisition_date else None
            book.categories = ','.join(book_data.categories) if book_data.categories else None
            book.tags = ','.join(book_data.tags) if book_data.tags else None
            db.session.commit()
            return True
        return False

    def delete_book(self, book_id):
        book = SQLBook.query.get(book_id)
        if book:
            db.session.delete(book)
            db.session.commit()
            return True
        return False

    def list_all_books(self):
        return SQLBook.query.all()

    def search_books(self, search_term=None, search_by=None, date_from=None, date_to=None):
        query = SQLBook.query

        if search_term:
            if search_by == 'title':
                query = query.filter(SQLBook.title.ilike(f'%{search_term}%'))
            elif search_by == 'author':
                query = query.filter(SQLBook.author.ilike(f'%{search_term}%'))
            elif search_by == 'isbn':
                query = query.filter(SQLBook.isbn.ilike(f'%{search_term}%'))
            elif search_by == 'categories':
                query = query.filter(SQLBook.categories.ilike(f'%{search_term}%'))
            elif search_by == 'tags':
                query = query.filter(SQLBook.tags.ilike(f'%{search_term}%'))
            else:
                query = query.filter(or_(
                    SQLBook.title.ilike(f'%{search_term}%'),
                    SQLBook.author.ilike(f'%{search_term}%'),
                    SQLBook.isbn.ilike(f'%{search_term}%'),
                    SQLBook.categories.ilike(f'%{search_term}%'),
                    SQLBook.tags.ilike(f'%{search_term}%')
                ))

        if date_from:
            query = query.filter(SQLBook.acquisition_date >= date_from)
        if date_to:
            query = query.filter(SQLBook.acquisition_date <= date_to)

        return query.all()

    def get_all_categories(self):
        books = SQLBook.query.filter(SQLBook.categories.isnot(None)).all()
        all_categories = set()
        for book in books:
            if book.categories:
                # Don't split the category string - it's already a single value
                all_categories.add(book.categories)
        return sorted(list(all_categories))

    def get_all_tags(self):
        books = SQLBook.query.filter(SQLBook.tags.isnot(None)).all()
        all_tags = set()
        for book in books:
            if book.tags:
                # Only split if there are multiple tags
                tags = [tag.strip() for tag in book.tags.split(',') if tag.strip()]
                all_tags.update(tags)
        return sorted(list(all_tags))

    def get_google_books_data(self, isbn: str):
        try:
            url = f'https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}'
            response = requests.get(url)
            data = response.json()

            if data.get('items'):
                volume_info = data['items'][0]['volumeInfo']
                return {
                    'pageCount': volume_info.get('pageCount'),
                    'publishedDate': volume_info.get('publishedDate'),
                    'categories': volume_info.get('categories', [])
                }
        except Exception as e:
            print(f"Error fetching Google Books data: {e}")
        return None

    def search_google_books_by_title(self, title: str):
        try:
            url = f'https://www.googleapis.com/books/v1/volumes?q=intitle:{title}&maxResults=5'
            response = requests.get(url)
            data = response.json()
            
            results = []
            if data.get('items'):
                for item in data['items']:
                    volume_info = item['volumeInfo']
                    # Only include results that have enough information
                    if volume_info.get('title') and volume_info.get('authors'):
                        results.append({
                            'title': volume_info.get('title'),
                            'authors': volume_info.get('authors', []),
                            'isbn': next((i.get('identifier') for i in volume_info.get('industryIdentifiers', []) 
                                       if i.get('type') in ['ISBN_13', 'ISBN_10']), ''),
                            'publishedDate': volume_info.get('publishedDate'),
                            'pageCount': volume_info.get('pageCount'),
                            'categories': volume_info.get('categories', []),
                            'description': volume_info.get('description', '')[:200] + '...' if volume_info.get('description') else ''
                        })
                return results
        except Exception as e:
            print(f"Error searching Google Books: {e}")
        return []

    def search_google_books_by_title_and_author(self, title, author=None):
        try:
            query = f'intitle:{title}'
            if author:
                query += f'+inauthor:{author}'
            
            url = f'https://www.googleapis.com/books/v1/volumes?q={query}'
            response = requests.get(url)
            data = response.json()
            
            results = []
            if data.get('items'):
                for item in data['items'][:5]:  # Limit to first 5 results
                    volume_info = item['volumeInfo']
                    if volume_info.get('title'):
                        results.append({
                            'title': volume_info.get('title'),
                            'authors': volume_info.get('authors', []),
                            'isbn': next((i['identifier'] for i in volume_info.get('industryIdentifiers', []) 
                                        if i.get('type') in ['ISBN_13', 'ISBN_10']), ''),
                            'publishedDate': volume_info.get('publishedDate'),
                            'pageCount': volume_info.get('pageCount'),
                            'categories': volume_info.get('categories', []),
                            'description': volume_info.get('description', '')[:200] + '...' if volume_info.get('description') else ''
                        })
            return results
        except Exception as e:
            print(f"Error searching Google Books: {e}")
            return []

    def get_book_by_isbn(self, isbn: str):
        if not isbn:
            return None
        return SQLBook.query.filter_by(isbn=isbn).first()

    def get_book_data_by_isbn(self, isbn: str):
        try:
            print(f"Fetching data for ISBN: {isbn}")
            url = f'https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}'
            response = requests.get(url)
            data = response.json()
            
            if data.get('items'):
                volume_info = data['items'][0]['volumeInfo']
                categories = volume_info.get('categories', [])
                
                # Ensure categories is properly formatted
                if isinstance(categories, str):
                    categories = [categories]
                elif not isinstance(categories, list):
                    categories = []
                    
                return {
                    'title': volume_info.get('title'),
                    'author': ', '.join(volume_info.get('authors', [])),
                    'isbn': isbn,
                    'publication_date': volume_info.get('publishedDate'),
                    'pages': volume_info.get('pageCount'),
                    'categories': ', '.join(categories) if categories else None
                }
            return None
        except Exception as e:
            print(f"Error fetching ISBN data: {e}")
            return None

    def add_book_by_isbn(self, isbn: str, chapters: int = None):
        """Add a book to the database using ISBN lookup."""
        book_data = self.get_book_data_by_isbn(isbn)
        if book_data:
            try:
                book = SQLBook(
                    title=book_data['title'],
                    author=book_data['author'],
                    isbn=isbn,
                    publication_date=book_data['publication_date'],
                    pages=book_data['pages'],
                    chapters=chapters,
                    acquisition_date=datetime.now().date(),
                    categories=book_data['categories']
                )
                db.session.add(book)
                db.session.commit()
                return book.id
            except Exception as e:
                db.session.rollback()
                print(f"Error adding book to database: {e}")
                raise
        return None

def format_isbn(isbn: str) -> str:
    # Remove any existing hyphens and spaces
    isbn = ''.join(c for c in isbn if c.isdigit())
    
    if len(isbn) == 13:  # ISBN-13
        return f"{isbn[0:3]}-{isbn[3]}-{isbn[4:8]}-{isbn[8:12]}-{isbn[12]}"
    elif len(isbn) == 10:  # ISBN-10
        return f"{isbn[0]}-{isbn[1:4]}-{isbn[4:9]}-{isbn[9]}"
    return isbn

# Example usage
if __name__ == "__main__":
    library = LibraryManager()
    
    # Add a book by ISBN
    library.add_book_by_isbn("9780007525546", chapters=20)  # The Hobbit
    
    # Add a book manually
    new_book = BookDTO(
        title="Manual Entry Book",
        author="John Doe",
        isbn="1234567890",
        publication_date="2023",
        pages=300,
        chapters=15,
        acquisition_date=datetime.now().strftime('%Y-%m-%d'),
        categories=[]
    )
    library.add_book(new_book)
    
    # List all books
    books = library.list_all_books()
    for book in books:
        print(f"\nTitle: {book.title}")
        print(f"Author: {book.author}")
        print(f"ISBN: {format_isbn(book.isbn)}")
        print(f"Publication Date: {book.publication_date}")
        print(f"Pages: {book.pages}")
        print(f"Chapters: {book.chapters}")
        print(f"Acquisition Date: {book.acquisition_date}")
        print(f"Categories: {', '.join(book.categories)}")
