-- Library Management System Database Schema
-- Each book row represents one physical copy.
CREATE TABLE IF NOT EXISTS members (
    member_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS books (
    book_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS loans (
    loan_id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(member_id),
    book_id INTEGER NOT NULL REFERENCES books(book_id),
    borrowed_on TEXT NOT NULL,
    due_on TEXT NOT NULL,
    returned_on TEXT,
    CHECK (due_on >= borrowed_on),
    CHECK (returned_on IS NULL OR returned_on >= borrowed_on)
);

-- NOCASE indexes support English title/author prefix searches with LIKE.
CREATE INDEX IF NOT EXISTS books_title_index ON books(title COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS books_author_index ON books(author COLLATE NOCASE);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_loan_per_book
ON loans(book_id) WHERE returned_on IS NULL;
CREATE INDEX IF NOT EXISTS loans_member_index ON loans(member_id);
