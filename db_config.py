import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2 import pool
from contextlib import contextmanager

# Load environment variables
load_dotenv()


class DatabaseConfig:
    def __init__(self):
        self.connection_pool = None
        self.min_connections = 1
        self.max_connections = 20

        # Database connection parameters
        self.db_params = {
            'dbname': os.getenv('DB_NAME', 'sales_targeting'),
            'user': os.getenv('DB_USER', 'sales_app'),
            'password': os.getenv('DB_PASSWORD'),
            'host': os.getenv('DB_HOST', 'corkscrew.mywinesense.com'),
            'port': os.getenv('DB_PORT', '5432')
        }

    def initialize_pool(self):
        """Initialize the connection pool"""
        if self.connection_pool is None:
            try:
                self.connection_pool = psycopg2.pool.SimpleConnectionPool(
                    self.min_connections,
                    self.max_connections,
                    **self.db_params
                )
            except psycopg2.Error as e:
                raise Exception(f"Error creating connection pool: {e}")

    @contextmanager
    def get_connection(self):
        """Get a database connection from the pool"""
        if self.connection_pool is None:
            self.initialize_pool()

        conn = None
        try:
            conn = self.connection_pool.getconn()
            yield conn
            conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            raise e
        finally:
            if conn:
                self.connection_pool.putconn(conn)

    @contextmanager
    def get_cursor(self):
        """Get a database cursor"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

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
                    province TEXT,
                    postal_code TEXT
                )
            ''')

            # Create indexes for better performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer_email ON customers(email)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer_postal ON customers(postal_code)')

            # Sales history table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sales_history (
                    id SERIAL PRIMARY KEY,
                    invoice_id TEXT,
                    customer_id TEXT REFERENCES customers(customer_id),
                    brand TEXT,
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
                    call_id SERIAL PRIMARY KEY,
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
                    id SERIAL PRIMARY KEY,
                    year INTEGER,
                    period_number INTEGER,
                    start_date DATE,
                    end_date DATE,
                    description TEXT,
                    UNIQUE(year, period_number)
                )
            ''')

    def close_pool(self):
        """Close the connection pool"""
        if self.connection_pool:
            self.connection_pool.closeall()
            self.connection_pool = None


# Global database configuration instance
db_config = DatabaseConfig()