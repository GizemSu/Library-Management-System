
import sqlite3
import json
import secrets
from datetime import date, timedelta
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

FOLDER = Path(__file__).parent
DATABASE = FOLDER / "library.db"
TOKEN = secrets.token_hex(16)


# Database connection
def connect_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA foreign_keys = ON")

    with open(FOLDER / "schema.sql", encoding="utf-8") as file:
        db.executescript(file.read())

    return db


# Add a new book
def add_book(db, title, author):
    if not title.strip() or not author.strip():
        raise ValueError("Please enter title and author.")

    db.execute(
        "INSERT INTO books (title, author) VALUES (?, ?)",
        (title.strip(), author.strip())
    )
    db.commit()


# Add a new member
def add_member(db, name, email):
    if not name.strip() or "@" not in email:
        raise ValueError("Please enter a valid name and email.")

    db.execute(
        "INSERT INTO members (name, email) VALUES (?, ?)",
        (name.strip(), email.strip())
    )
    db.commit()


# Get all books
def get_books(db):
    return db.execute("""
        SELECT b.book_id, b.title, b.author,
        CASE
            WHEN l.loan_id IS NULL THEN 'Available'
            ELSE 'On loan'
        END
        FROM books b
        LEFT JOIN loans l
        ON b.book_id = l.book_id
        AND l.returned_on IS NULL
        ORDER BY b.book_id
    """).fetchall()


# Borrow books
def borrow_books(db, member_id, book_ids, due_on):
    if not book_ids:
        raise ValueError("Please select a book.")

    due = date.fromisoformat(due_on)

    if due < date.today():
        raise ValueError("Due date cannot be in the past.")

    try:
        for book_id in book_ids:
            active = db.execute("""
                SELECT loan_id FROM loans
                WHERE book_id = ?
                AND returned_on IS NULL
            """, (book_id,)).fetchone()

            if active:
                raise ValueError("This book is already borrowed.")

            db.execute("""
                INSERT INTO loans
                (member_id, book_id, borrowed_on, due_on)
                VALUES (?, ?, ?, ?)
            """, (
                member_id,
                book_id,
                date.today().isoformat(),
                due_on
            ))

        db.commit()

    except Exception:
        db.rollback()
        raise


# Return books
def return_books(db, loan_ids):
    if not loan_ids:
        raise ValueError("Please select a loan.")

    try:
        for loan_id in loan_ids:
            result = db.execute("""
                UPDATE loans
                SET returned_on = ?
                WHERE loan_id = ?
                AND returned_on IS NULL
            """, (date.today().isoformat(), loan_id))

            if result.rowcount == 0:
                raise ValueError("Active loan not found.")

        db.commit()

    except Exception:
        db.rollback()
        raise


# Convert database rows to dictionaries
def make_records(columns, rows):
    result = []

    for row in rows:
        result.append(dict(zip(columns, row)))

    return result


# Send data to the HTML page
def get_state(db, field="title", search=""):
    books = get_books(db)

    if field not in ("title", "author"):
        raise ValueError("Invalid search field.")

    if search:
        index = 1 if field == "title" else 2
        books = [
            book for book in books
            if book[index].lower().startswith(search.lower())
        ]

    members = db.execute("""
        SELECT m.member_id, m.name, m.email,
               COUNT(l.loan_id),
               SUM(CASE
                   WHEN l.loan_id IS NOT NULL
                   AND l.returned_on IS NULL
                   THEN 1 ELSE 0
               END)
        FROM members m
        LEFT JOIN loans l ON m.member_id = l.member_id
        GROUP BY m.member_id
    """).fetchall()

    loans = db.execute("""
        SELECT l.loan_id, m.member_id, m.name,
               b.book_id, b.title,
               l.borrowed_on, l.due_on, l.returned_on
        FROM loans l
        JOIN members m ON l.member_id = m.member_id
        JOIN books b ON l.book_id = b.book_id
        ORDER BY l.loan_id DESC
    """).fetchall()

    popular = db.execute("""
        SELECT b.book_id, b.title, COUNT(l.loan_id)
        FROM books b
        LEFT JOIN loans l ON b.book_id = l.book_id
        GROUP BY b.book_id
        ORDER BY COUNT(l.loan_id) DESC
    """).fetchall()

    active = sum(1 for loan in loans if loan[7] is None)

    overdue = sum(
        1 for loan in loans
        if loan[7] is None and loan[6] < date.today().isoformat()
    )

    total_books = db.execute(
        "SELECT COUNT(*) FROM books"
    ).fetchone()[0]

    return {
        "today": date.today().isoformat(),
        "token": TOKEN,
        "books": make_records(
            ["id", "title", "author", "status"], books
        ),
        "members": make_records(
            ["id", "name", "email", "total", "active"], members
        ),
        "loans": make_records(
            ["id", "member_id", "member", "book_id",
             "title", "borrowed", "due", "returned"], loans
        ),
        "popular": make_records(
            ["id", "title", "total"], popular
        ),
        "stats": {
            "books": total_books,
            "members": len(members),
            "active": active,
            "overdue": overdue
        }
    }


# Web server
class LibraryServer(BaseHTTPRequestHandler):

    def send_data(self, data, status=200):
        content = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/":
            with open(FOLDER / "interface.html", "rb") as file:
                page = file.read()

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(page)

        elif url.path == "/api/state":
            params = parse_qs(url.query)

            field = params.get("field", ["title"])[0]
            search = params.get("q", [""])[0]

            db = connect_db()

            try:
                self.send_data(get_state(db, field, search))
            except ValueError as error:
                self.send_data({"error": str(error)}, 400)
            finally:
                db.close()

        else:
            self.send_data({"error": "Page not found"}, 404)

    def do_POST(self):
        if self.headers.get("X-Library-Token") != TOKEN:
            self.send_data({"error": "Invalid request"}, 403)
            return

        try:
            length = int(self.headers.get("Content-Length", 0))

            if length < 1 or length > 16384:
                raise ValueError("Invalid request size.")

            data = json.loads(self.rfile.read(length))

            if not isinstance(data, dict):
                raise ValueError("Invalid data.")

            db = connect_db()

            try:
                if self.path == "/api/books":
                    add_book(db, data["title"], data["author"])

                elif self.path == "/api/members":
                    add_member(db, data["name"], data["email"])

                elif self.path == "/api/borrow":
                    borrow_books(
                        db,
                        data["member_id"],
                        data["book_ids"],
                        data["due_on"]
                    )

                elif self.path == "/api/return":
                    return_books(db, data["loan_ids"])

                else:
                    self.send_data({"error": "Unknown action"}, 404)
                    return

                self.send_data({"ok": True})

            finally:
                db.close()

        except (ValueError, KeyError, TypeError,
                sqlite3.Error) as error:
            self.send_data({"error": str(error)}, 400)


# Start the application
def main():
    db = connect_db()
    db.close()

    server = HTTPServer(("127.0.0.1", 8765), LibraryServer)

    print("Library Management System")
    print("Open: http://127.0.0.1:8765")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
