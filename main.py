from datetime import datetime
import isbnlib
from dataclasses import dataclass
from typing import List
import requests
from sqlalchemy import or_, func
from models import db, Book as SQLBook
import json

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

    def search_books(self, query: str):
        try:
            # Split query to check for author: or title: prefix
            parts = query.lower().split(':')
            search_type = None
            search_term = query.strip()
            
            if len(parts) == 2:
                if parts[0].strip() in ['author', 'by']:
                    search_type = 'author'
                    search_term = parts[1].strip()
                elif parts[0].strip() == 'title':
                    search_type = 'title'
                    search_term = parts[1].strip()
            else:
                # Check if the query looks like an author name (contains spaces)
                if ' ' in search_term:
                    search_type = 'author'
            
            # Search both APIs with the appropriate parameters
            google_results = []
            if search_type == 'author':
                # Only search by author
                google_results = self.search_google_books_by_title_and_author('', search_term)
            elif search_type == 'title':
                # Only search by title
                google_results = self.search_google_books_by_title_and_author(search_term)
            else:
                # First try exact title match
                google_results = self.search_google_books_by_title_and_author(search_term)
                
                # If no results, try author search
                if not google_results:
                    google_results = self.search_google_books_by_title_and_author('', search_term)
            
            # Get OpenLibrary results with the same search type
            openlib_results = []
            if search_type == 'author':
                openlib_results = self._search_openlibrary(f"author:{search_term}")
            else:
                openlib_results = self._search_openlibrary(search_term)
            
            # Combine and deduplicate results
            all_results = []
            seen_titles = set()
            
            # Helper function to create result entry
            def add_result(book, source):
                key = f"{book.get('title', '')}|{book.get('author', '')}"
                if key not in seen_titles:
                    seen_titles.add(key)
                    all_results.append(book)
            
            # Process Google results first
            if google_results:
                for book in google_results:
                    if not book.get('title'):
                        continue
                        
                    # For author searches, verify author name is in the result
                    if search_type == 'author' and search_term.lower() not in ', '.join(book.get('authors', [])).lower():
                        continue
                        
                    add_result({
                        'title': book.get('title'),
                        'author': ', '.join(book.get('authors', [])),
                        'isbn': book.get('isbn'),
                        'publication_date': book.get('publishedDate'),
                        'pages': book.get('pageCount'),
                        'categories': ', '.join(book.get('categories', [])),
                        'source': 'Google Books'
                    }, 'Google Books')
            
            # Add unique OpenLibrary results
            if openlib_results:
                for book in openlib_results:
                    if not book.get('title'):
                        continue
                        
                    # For author searches, verify author name in the result
                    if search_type == 'author' and search_term.lower() not in book.get('author', '').lower():
                        continue
                        
                    add_result(book, 'OpenLibrary')
            
            return all_results[:10]  # Limit to top 10 results
            
        except Exception as e:
            print(f"Error searching books: {e}")
            return []

    def get_all_categories(self):
        try:
            # Get all non-deleted books with categories
            books = SQLBook.query.filter(
                SQLBook.deleted == False,
                SQLBook.categories.isnot(None),
                SQLBook.categories != ''
            ).all()
            
            # Create a set of all unique categories
            all_categories = set()
            for book in books:
                if book.categories:
                    # Split categories if they contain commas
                    categories = [cat.strip() for cat in book.categories.split(',')]
                    all_categories.update(cat for cat in categories if cat)
            
            return sorted(list(all_categories))
        except Exception as e:
            print(f"Error getting categories: {e}")
            return []

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
            # Get data from both sources
            google_data = self._get_google_books_data(isbn)
            openlib_data = self._get_openlibrary_data(isbn)
            
            # If neither source has data, return None
            if not google_data and not openlib_data:
                return None
            
            # Merge the data, preferring Google Books when both exist
            merged_data = {
                'title': None,
                'author': None,
                'isbn': isbn,
                'publication_date': None,
                'pages': None,
                'categories': None
            }
            
            # Helper function to merge categories
            def merge_categories(cat1, cat2):
                categories = set()
                # Add non-empty categories from both sources
                if cat1:
                    categories.update(cat1.split(', '))
                if cat2:
                    categories.update(cat2.split(', '))
                return ', '.join(sorted(categories)) if categories else None
            
            # Merge logic for each field
            if google_data and openlib_data:
                merged_data.update({
                    'title': google_data.get('title') or openlib_data.get('title'),
                    'author': google_data.get('author') or openlib_data.get('author'),
                    'publication_date': google_data.get('publishedDate') or openlib_data.get('publish_date'),
                    'pages': google_data.get('pageCount') or openlib_data.get('number_of_pages'),
                    'categories': merge_categories(google_data.get('categories'), openlib_data.get('categories'))
                })
            elif google_data:
                merged_data.update(google_data)
            else:
                merged_data.update(openlib_data)
            
            # Final validation and cleanup
            if not merged_data['title']:
                return None
            
            print(f"Merged book data for ISBN {isbn}:")
            print(f"Title: {merged_data['title']}")
            print(f"Author: {merged_data['author']}")
            print(f"Categories: {merged_data['categories']}")
            print(f"Pages: {merged_data['pages']}")
            
            return merged_data
            
        except Exception as e:
            print(f"Error merging ISBN data: {e}")
            return None

    def _get_google_books_data(self, isbn: str):
        try:
            url = f'https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}'
            response = requests.get(url)
            data = response.json()
            
            if data.get('items'):
                volume_info = data['items'][0]['volumeInfo']
                categories = volume_info.get('categories', [])
                
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
            print(f"Error fetching Google Books data: {e}")
            return None

    def _get_openlibrary_data(self, isbn: str):
        try:
            print(f"\n=== OpenLibrary ISBN Lookup Debug ===")
            print(f"Looking up ISBN: {isbn}")
            
            url = f'https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data'
            print(f"URL: {url}")
            
            response = requests.get(url)
            data = response.json()
            print(f"Raw Response: {json.dumps(data, indent=2)}")
            
            book_key = f'ISBN:{isbn}'
            if book_key in data:
                book_info = data[book_key]
                print(f"Book Info: {json.dumps(book_info, indent=2)}")
                
                # Extract authors - handle both string and dict formats
                authors = []
                raw_authors = book_info.get('authors', [])
                print(f"Raw Authors: {raw_authors}")
                
                for author in raw_authors:
                    if isinstance(author, dict):
                        authors.append(author.get('name', ''))
                    else:
                        authors.append(str(author))
                
                # Handle subjects - similar approach
                categories = []
                raw_subjects = book_info.get('subjects', [])
                print(f"Raw Subjects: {raw_subjects}")
                
                for subject in raw_subjects[:2]:  # Limit to 2 subjects
                    if isinstance(subject, dict):
                        categories.append(subject.get('name', ''))
                    else:
                        categories.append(str(subject))
                
                # Add a place if available
                raw_places = book_info.get('subject_places', [])
                if raw_places:
                    place = raw_places[0]
                    if isinstance(place, dict):
                        categories.append(place.get('name', ''))
                    else:
                        categories.append(str(place))
                
                result = {
                    'title': book_info.get('title'),
                    'author': ', '.join(authors),
                    'isbn': isbn,
                    'publication_date': book_info.get('publish_date'),
                    'pages': book_info.get('number_of_pages'),
                    'categories': ', '.join(categories) if categories else None
                }
                print(f"Final Processed Result: {json.dumps(result, indent=2)}")
                return result
                
            print("ISBN not found in initial lookup, trying works API...")
            return None
            
        except Exception as e:
            print(f"Error in OpenLibrary lookup: {str(e)}")
            print(f"Error type: {type(e)}")
            import traceback
            print(traceback.format_exc())
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

    def _search_openlibrary(self, query: str):
        try:
            print("\n=== OpenLibrary Search Debug ===")
            print(f"Query: {query}")
            
            # Check if query looks like an ISBN
            is_isbn = query.replace('-', '').replace(' ', '').isdigit()
            
            if is_isbn:
                clean_isbn = query.replace('-', '').replace(' ', '')
                url = f'https://openlibrary.org/api/books?bibkeys=ISBN:{clean_isbn}&format=json&jscmd=data'
                print(f"\nTrying URL: {url}")
                
                response = requests.get(url)
                data = response.json()
                
                print("\nRaw OpenLibrary Response:")
                print(json.dumps(data, indent=2))
                
                if data:
                    book_key = f'ISBN:{clean_isbn}'
                    if book_key in data:
                        book_info = data[book_key]
                        print("\nBook Info Structure:")
                        print(json.dumps(book_info, indent=2))
                        
                        # Debug authors structure
                        if 'authors' in book_info:
                            print("\nAuthors structure:")
                            print(json.dumps(book_info['authors'], indent=2))
                        
                        # Debug subjects structure
                        if 'subjects' in book_info:
                            print("\nSubjects structure:")
                            print(json.dumps(book_info['subjects'], indent=2))
                        
                        return [{
                            'title': book_info.get('title'),
                            'author': ', '.join(author['name'] for author in book_info.get('authors', [])) if isinstance(book_info.get('authors'), list) else '',
                            'isbn': clean_isbn,
                            'publication_date': book_info.get('publish_date'),
                            'pages': book_info.get('number_of_pages'),
                            'categories': ', '.join(book_info.get('subjects', [])) if isinstance(book_info.get('subjects'), list) else '',
                            'source': 'OpenLibrary'
                        }]
                
                print("\nNo results found in direct lookup, trying search endpoint...")
                return []
            
        except Exception as e:
            print(f"\nError in OpenLibrary search: {str(e)}")
            print(f"Error type: {type(e)}")
            import traceback
            print(traceback.format_exc())
            return []

    def search_combined(self, title: str, author: str):
        try:
            all_results = []
            seen_keys = set()
            
            # Search Google Books
            google_results = self.search_google_books_by_title_and_author(title, author)
            if google_results:
                for book in google_results:
                    key = f"{book.get('title')}|{', '.join(book.get('authors', []))}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_results.append({
                            'title': book.get('title'),
                            'author': ', '.join(book.get('authors', [])),
                            'isbn': book.get('isbn'),
                            'publication_date': book.get('publishedDate'),
                            'pages': book.get('pageCount'),
                            'categories': ', '.join(book.get('categories', [])),
                            'source': 'Google Books'
                        })
            
            # Search OpenLibrary with better query construction
            try:
                url = f'https://openlibrary.org/search.json?q={title}'
                if author:
                    url += f'+author:{author}'
                
                print(f"OpenLibrary search URL: {url}")
                response = requests.get(url)
                data = response.json()
                
                if data.get('docs'):
                    for doc in data['docs'][:5]:  # Limit to first 5 results
                        key = f"{doc.get('title')}|{', '.join(doc.get('author_name', []))}"
                        if key not in seen_keys:
                            seen_keys.add(key)
                            categories = []
                            if doc.get('subject', []):
                                categories.extend(doc['subject'][:2])
                            if doc.get('place', []):
                                categories.extend(doc['place'][:1])
                            
                            all_results.append({
                                'title': doc.get('title'),
                                'author': ', '.join(doc.get('author_name', [])),
                                'isbn': doc.get('isbn', [''])[0] if doc.get('isbn') else '',
                                'publication_date': str(doc.get('first_publish_year', '')),
                                'pages': doc.get('number_of_pages'),
                                'categories': ', '.join(categories) if categories else '',
                                'source': 'OpenLibrary'
                            })
            
            except Exception as e:
                print(f"Error in OpenLibrary search: {e}")
            
            return all_results[:10]
        
        except Exception as e:
            print(f"Error in combined search: {e}")
            return []

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
