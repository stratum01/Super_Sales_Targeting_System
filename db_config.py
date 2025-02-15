import sqlite3
from pathlib import Path
from contextlib import contextmanager


class DatabaseConfig:
    def __init__(self, db_path='fruit_sales.db'):
        """Initialize database configuration

        Args:
            db_path (str): Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.connection = None

    def connect(self):
        """Create a database connection"""
        if not self.connection:
            self.connection = sqlite3.connect(self.db_path)
            # Enable foreign keys
            self.connection.execute("PRAGMA foreign_keys = ON")

    @contextmanager
    def get_cursor(self):
        """Get a database cursor"""
        self.connect()
        cursor = self.connection.cursor()
        try:
            yield cursor
            self.connection.commit()
        except Exception as e:
            self.connection.rollback()
            raise e
        finally:
            cursor.close()

    def close(self):
        """Close the database connection"""
        if self.connection:
            self.connection.close()
            self.connection = None

    def setup_database(self):
        """Initialize the database schema"""
        with self.get_cursor() as cursor:
            # Create customers table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    email TEXT,
                    phone TEXT,
                    address TEXT,
                    city TEXT,
                    state TEXT,
                    postal_code TEXT
                )
            ''')

            # Create indexes for better performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer_email ON customers(email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer_postal ON customers(postal_code)')

            # Sales history table with fruit categories
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sales_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    invoice_id TEXT,
                    customer_id TEXT REFERENCES customers(customer_id),
                    brand TEXT CHECK(brand IN ('Apples', 'Grapes', 'Oranges')),
                    units_sold INTEGER,
                    item TEXT,
                    customer_name TEXT,
                    date_sold DATE
                )
            ''')

            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_invoice_id ON sales_history(invoice_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sales_customer_id ON sales_history(customer_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sales_date ON sales_history(date_sold)')

            # Call tracking table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS call_tracking (
                    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id TEXT REFERENCES customers(customer_id),
                    call_date DATE,
                    status TEXT CHECK(status IN ('successful_sale', 'considering', 'left_message', 'no_answer', 'other')),
                    notes TEXT,
                    brand TEXT,
                    item TEXT
                )
            ''')

            # Promotion periods table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS promotion_periods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER,
                    month INTEGER CHECK(month BETWEEN 1 AND 12),
                    start_date DATE,
                    end_date DATE,
                    description TEXT,
                    UNIQUE(year, month)
                )
            ''')

            # Insert sample promotion periods
            cursor.execute('''
                INSERT OR IGNORE INTO promotion_periods (year, month, start_date, end_date, description)
                VALUES 
                    (2024, 1, '2024-01-01', '2024-01-31', 'Winter Citrus Festival'),
                    (2024, 2, '2024-02-01', '2024-02-29', 'Valentine''s Red Fruits'),
                    (2024, 3, '2024-03-01', '2024-03-31', 'Early Spring Varieties'),
                    (2024, 4, '2024-04-01', '2024-04-30', 'Spring Harvest Special'),
                    (2024, 5, '2024-05-01', '2024-05-31', 'May Fresh Picks'),
                    (2024, 6, '2024-06-01', '2024-06-30', 'Summer Fruit Festival'),
                    (2024, 7, '2024-07-01', '2024-07-31', 'Peak Season Celebration'),
                    (2024, 8, '2024-08-01', '2024-08-31', 'August Abundance'),
                    (2024, 9, '2024-09-01', '2024-09-30', 'Fall Harvest Kickoff'),
                    (2024, 10, '2024-10-01', '2024-10-31', 'Autumn Selections'),
                    (2024, 11, '2024-11-01', '2024-11-30', 'Thanksgiving Specials'),
                    (2024, 12, '2024-12-01', '2024-12-31', 'Holiday Fruit Baskets')
            ''')


# Global database configuration instance
db_config = DatabaseConfig()