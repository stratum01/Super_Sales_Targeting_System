import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from PIL import Image, ImageTk
from db_config import db_config
from comparison_system import ComparisonSystem, ComparisonTab
from logging_config import setup_logging, get_logger
from tkcalendar import DateEntry
import matplotlib
matplotlib.use('TkAgg')
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

setup_logging()


class SalesTargetingSystem:
    # Define fruit categories and their properties
    FRUIT_CATEGORIES = {
        'Apples': {
            'type': 'premium',
            'items': ['Honeycrisp', 'Fuji', 'Gala', 'Pink Lady', 'Granny Smith', 'McIntosh'],
            'cross_sell_to': ['Grapes']  # Premium fruit buyers might like specialty grapes
        },
        'Grapes': {
            'type': 'specialty',
            'items': ['Red Globe', 'Cotton Candy', 'Moon Drops', 'Concord', 'Champagne', 'Crimson Seedless'],
            'cross_sell_to': ['Apples']  # Specialty buyers might like premium apples
        },
        'Oranges': {
            'type': 'standard',
            'items': ['Navel', 'Valencia', 'Mandarin', 'Blood Orange', 'Cara Cara', 'Clementine'],
            'cross_sell_to': ['Apples', 'Grapes']  # Standard buyers might upgrade to premium or specialty
        }
    }

    def __init__(self):
        self.logger = get_logger('sales_targeting')
        db_config.setup_database()

    def get_customer_info(self, customer_id):
        """Get customer contact and purchase information"""
        with db_config.get_cursor() as cursor:
            query = """
                SELECT 
                    c.*,
                    COALESCE(sh.total_purchases, 0) as total_purchases,
                    COALESCE(sh.total_units, 0) as total_units,
                    sh.last_purchase,
                    sh.favorite_category
                FROM customers c
                LEFT JOIN (
                    SELECT 
                        customer_id,
                        COUNT(DISTINCT invoice_id) as total_purchases,
                        SUM(units_sold) as total_units,
                        MAX(date_sold) as last_purchase,
                        (
                            SELECT brand
                            FROM sales_history sh2
                            WHERE sh2.customer_id = sales_history.customer_id
                            GROUP BY brand
                            ORDER BY COUNT(*) DESC
                            LIMIT 1
                        ) as favorite_category
                    FROM sales_history
                    GROUP BY customer_id
                ) sh ON c.customer_id = sh.customer_id
                WHERE c.customer_id = ?
            """

            cursor.execute(query, (customer_id,))
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()

            if row:
                return dict(zip(columns, row))
            return None

    def get_big_banana_customers(self, target_item, limit=20):
        """Get customers who have bought the most of a specific fruit variety"""
        if not target_item:
            raise ValueError("Item must be specified for Big Banana search")

        with db_config.get_cursor() as cursor:
            query = """
            WITH CustomerPurchases AS (
                SELECT 
                    sh.customer_id,
                    MAX(sh.customer_name) as customer_name,
                    COUNT(*) as purchase_count,
                    SUM(sh.units_sold) as total_units,
                    MAX(sh.date_sold) as last_purchase_date,
                    MAX(CASE WHEN sh.brand = 'Apples' THEN 1 ELSE 0 END) as buys_premium,
                    MAX(CASE WHEN sh.brand = 'Grapes' THEN 1 ELSE 0 END) as buys_specialty
                FROM sales_history sh
                WHERE sh.item = ?
                GROUP BY sh.customer_id
            )
            SELECT 
                cp.*,
                ct.call_date as last_call_date,
                ct.status as last_call_status
            FROM CustomerPurchases cp
            LEFT JOIN (
                SELECT 
                    customer_id,
                    MAX(call_date) as call_date,
                    MAX(status) as status
                FROM call_tracking
                GROUP BY customer_id
            ) ct ON cp.customer_id = ct.customer_id
            ORDER BY cp.total_units DESC
            LIMIT ?
            """

            cursor.execute(query, (target_item, limit))
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()

            return pd.DataFrame(data, columns=columns)

    def get_potential_customers(self, target_item=None, target_brand=None, days_inactive=75,
                                call_filter_days=90, limit=20, offset=0,
                                cross_sell_category=None):
        """Find potential customers based on purchase history and targeting criteria"""
        try:
            with db_config.get_cursor() as cursor:
                # Initialize parameters
                where_clauses = []
                params = []

                # Add brand filter
                if target_brand:
                    where_clauses.append("sh.brand = ?")
                    params.append(target_brand)

                # Add item filter
                if target_item:
                    where_clauses.append("sh.item = ?")
                    params.append(target_item)

                # If no where clauses, add TRUE condition
                if not where_clauses:
                    where_clauses.append("1=1")

                # Build count query
                count_query = f"""
                    WITH LastPurchase AS (
                        SELECT 
                            customer_id,
                            MAX(date_sold) as last_purchase_date
                        FROM sales_history sh
                        {f'WHERE {" AND ".join(where_clauses)}' if where_clauses else ''}
                        GROUP BY customer_id
                    ),
                    RecentCalls AS (
                        SELECT DISTINCT customer_id
                        FROM call_tracking
                        WHERE date('now', '-' || ? || ' days') <= call_date
                        AND status != 'no_answer'
                    )
                    SELECT COUNT(DISTINCT sh.customer_id)
                    FROM sales_history sh
                    JOIN LastPurchase lp ON sh.customer_id = lp.customer_id
                    LEFT JOIN RecentCalls rc ON sh.customer_id = rc.customer_id
                    WHERE date('now', '-' || ? || ' days') >= lp.last_purchase_date
                    AND rc.customer_id IS NULL
                """

                # Execute count query with parameters
                count_params = params + [call_filter_days, days_inactive]
                cursor.execute(count_query, count_params)
                total_count = cursor.fetchone()[0]

                # Build main query
                main_query = f"""
                    WITH LastPurchase AS (
                        SELECT 
                            customer_id,
                            customer_name,
                            MAX(date_sold) as last_purchase_date,
                            COUNT(DISTINCT invoice_id) as purchase_count
                        FROM sales_history sh
                        {f'WHERE {" AND ".join(where_clauses)}' if where_clauses else ''}
                        GROUP BY customer_id, customer_name
                    ),
                    RecentCalls AS (
                        SELECT DISTINCT customer_id
                        FROM call_tracking
                        WHERE date('now', '-' || ? || ' days') <= call_date
                        AND status != 'no_answer'
                    ),
                    CustomerPreferences AS (
                        SELECT 
                            customer_id,
                            MAX(CASE WHEN brand = 'Apples' THEN 1 ELSE 0 END) as buys_premium,
                            MAX(CASE WHEN brand = 'Grapes' THEN 1 ELSE 0 END) as buys_specialty
                        FROM sales_history
                        GROUP BY customer_id
                    )
                    SELECT 
                        sh.customer_id,
                        sh.customer_name,
                        lp.last_purchase_date,
                        lp.purchase_count,
                        cp.buys_premium,
                        cp.buys_specialty,
                        MAX(ct.call_date) as last_call_date,
                        MAX(ct.status) as last_call_status
                    FROM LastPurchase lp
                    JOIN sales_history sh ON lp.customer_id = sh.customer_id
                    LEFT JOIN CustomerPreferences cp ON lp.customer_id = cp.customer_id
                    LEFT JOIN RecentCalls rc ON lp.customer_id = rc.customer_id
                    LEFT JOIN call_tracking ct ON lp.customer_id = ct.customer_id
                    WHERE date('now', '-' || ? || ' days') >= lp.last_purchase_date
                    AND rc.customer_id IS NULL
                    {f'AND {" AND ".join(where_clauses)}' if where_clauses else ''}
                    GROUP BY sh.customer_id, sh.customer_name, lp.last_purchase_date, lp.purchase_count, 
                             cp.buys_premium, cp.buys_specialty
                    ORDER BY lp.last_purchase_date DESC
                    LIMIT ? OFFSET ?
                """

                # Execute main query with parameters
                main_params = params + [call_filter_days, days_inactive] + params + [limit, offset]

                # Debug output
                self.logger.debug(f"Executing query with params: {main_params}")
                self.logger.debug(f"Where clauses: {where_clauses}")

                cursor.execute(main_query, main_params)

                columns = [desc[0] for desc in cursor.description]
                data = cursor.fetchall()

                return pd.DataFrame(data, columns=columns), total_count

        except Exception as e:
            self.logger.error(f"Error in get_potential_customers: {str(e)}", exc_info=True)
            raise

    def check_data(self):
        """Check if we have data for each category"""
        with db_config.get_cursor() as cursor:
            cursor.execute("""
                SELECT brand, COUNT(*) as count, 
                       COUNT(DISTINCT customer_id) as customers,
                       MIN(date_sold) as earliest,
                       MAX(date_sold) as latest
                FROM sales_history
                GROUP BY brand
            """)
            return cursor.fetchall()

    def record_call(self, customer_id, status, notes, brand=None, item=None):
        """Record the outcome of a sales call"""
        with db_config.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO call_tracking (
                    customer_id, call_date, status, notes, brand, item
                ) VALUES (?, date('now'), ?, ?, ?, ?)
            ''', (customer_id, status, notes, brand, item))

    def get_call_history(self, days_back=30, customer_id=None):
        """Retrieve call history for specified period and/or customer"""
        with db_config.get_cursor() as cursor:
            query = """
                SELECT 
                    ct.*,
                    c.first_name || ' ' || c.last_name as customer_name,
                    sh.brand as last_brand_purchased,
                    sh.item as last_item_purchased,
                    COUNT(DISTINCT sh2.invoice_id) as lifetime_orders
                FROM call_tracking ct
                JOIN customers c ON ct.customer_id = c.customer_id
                LEFT JOIN (
                    SELECT DISTINCT ON (customer_id) 
                        customer_id, brand, item
                    FROM sales_history 
                    ORDER BY customer_id, date_sold DESC
                ) sh ON ct.customer_id = sh.customer_id
                LEFT JOIN sales_history sh2 ON ct.customer_id = sh2.customer_id
                WHERE ct.call_date >= date('now', '-' || ? || ' days')
            """

            params = [days_back]
            if customer_id:
                query = query.replace(
                    "WHERE ct.call_date",
                    "WHERE ct.customer_id = ? AND ct.call_date"
                )
                params = [customer_id] + params

            query += " GROUP BY ct.call_id, ct.customer_id, c.first_name, c.last_name, sh.brand, sh.item"
            cursor.execute(query, params)

            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()

            return pd.DataFrame(data, columns=columns)

    def import_customer_data(self, csv_path):
        """Import customer contact information from CSV file"""
        try:
            self.logger.info(f"Starting import from {csv_path}")

            # Read CSV file
            df = pd.read_csv(csv_path, dtype=str)

            # Map column names
            column_mapping = {
                'Customer ID': 'customer_id',
                'First Name': 'first_name',
                'Last Name': 'last_name',
                'Email': 'email',
                'Phone': 'phone',
                'Address': 'address',
                'City': 'city',
                'State': 'state',
                'Postal Code': 'postal_code'
            }

            df = df.rename(columns=column_mapping)

            # Clean data
            for col in df.columns:
                df[col] = df[col].fillna('')
                if df[col].dtype == 'object':
                    df[col] = df[col].str.strip()

            # Standardize phone numbers
            df['phone'] = df['phone'].apply(
                lambda x: ''.join(filter(str.isdigit, str(x))) if pd.notna(x) and x != '' else '')
            df['phone'] = df['phone'].apply(
                lambda x: f"({x[0:3]}) {x[3:6]}-{x[6:]}" if len(x) >= 10 else x)

            with db_config.get_cursor() as cursor:
                # Get existing customer IDs
                cursor.execute('SELECT customer_id FROM customers')
                existing_customers = {row[0] for row in cursor.fetchall()}

                # Prepare counters
                new_records = 0
                updated_records = 0

                # Process each row
                for _, row in df.iterrows():
                    if pd.isna(row['customer_id']) or str(row['customer_id']).strip() == '':
                        continue

                    customer_data = (
                        row['customer_id'],
                        row['first_name'],
                        row['last_name'],
                        row['email'],
                        row['phone'],
                        row['address'],
                        row['city'],
                        row['state'],
                        row['postal_code']
                    )

                    if row['customer_id'] in existing_customers:
                        # Update existing customer
                        cursor.execute("""
                            UPDATE customers 
                            SET first_name=?, last_name=?, email=?, phone=?,
                                address=?, city=?, state=?, postal_code=?
                            WHERE customer_id=?
                        """, customer_data[1:] + (customer_data[0],))
                        updated_records += 1
                    else:
                        # Insert new customer
                        cursor.execute("""
                            INSERT INTO customers (
                                customer_id, first_name, last_name, email, phone,
                                address, city, state, postal_code
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, customer_data)
                        new_records += 1

                return f"Successfully processed {len(df)} records: {new_records} new, {updated_records} updated"

        except Exception as e:
            self.logger.error(f"Error in import_customer_data: {str(e)}", exc_info=True)
            raise Exception(f"Error importing customer data: {str(e)}")

    def import_csv(self, csv_path, mode='append', progress_callback=None):
        """Import sales data from CSV file"""
        try:
            if progress_callback:
                progress_callback(0, 100, "Reading CSV file...")

            # Read CSV with all columns as strings initially
            df = pd.read_csv(csv_path, dtype=str)
            # Drop any completely empty columns
            df = df.dropna(axis=1, how='all')
            total_rows = len(df)

            if progress_callback:
                progress_callback(10, 100, "Processing data...")

            # Clean column names
            df.columns = df.columns.str.strip()

            # Rename columns
            column_mapping = {
                'Units': 'units_sold',
                'Date': 'date_sold',
                'Customer Name': 'customer_name',
                'Category': 'brand',  # Map Category to brand for database consistency
                'Variety': 'item',  # Map Variety to item for database consistency
                'Customer ID': 'customer_id',
                'Invoice ID': 'invoice_id'
            }
            df = df.rename(columns=column_mapping)

            # Validate required columns
            required_columns = ['units_sold', 'date_sold', 'customer_name', 'brand',
                                'item', 'customer_id', 'invoice_id']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

            if progress_callback:
                progress_callback(20, 100, "Validating data...")

            # Validate fruit categories
            valid_categories = set(self.FRUIT_CATEGORIES.keys())
            invalid_categories = set(df['brand'].unique()) - valid_categories
            if invalid_categories:
                raise ValueError(f"Invalid fruit categories found: {', '.join(invalid_categories)}")

            # Validate varieties for each category
            for category in valid_categories:
                valid_varieties = set(self.FRUIT_CATEGORIES[category]['items'])
                category_data = df[df['brand'] == category]
                if not category_data.empty:
                    invalid_varieties = set(category_data['item'].unique()) - valid_varieties
                    if invalid_varieties:
                        raise ValueError(
                            f"Invalid varieties found for {category}: {', '.join(invalid_varieties)}")

            # Convert Date to datetime
            df['date_sold'] = pd.to_datetime(df['date_sold']).dt.strftime('%Y-%m-%d')

            # Convert Units to numeric
            df['units_sold'] = pd.to_numeric(df['units_sold'], errors='coerce')

            # Clean string columns
            string_columns = ['customer_id', 'brand', 'item', 'customer_name', 'invoice_id']
            for col in string_columns:
                df[col] = df[col].str.strip()

            if progress_callback:
                progress_callback(30, 100, "Preparing for import...")

            # Track successful and failed records
            successful_records = []
            failed_records = []

            with db_config.get_cursor() as cursor:
                if mode == 'replace':
                    if progress_callback:
                        progress_callback(35, 100, "Clearing existing data...")
                    cursor.execute('DELETE FROM sales_history')
                else:
                    # Get existing invoice IDs
                    if progress_callback:
                        progress_callback(35, 100, "Checking for duplicates...")
                    cursor.execute('SELECT DISTINCT invoice_id FROM sales_history')
                    existing_invoices = {row[0] for row in cursor.fetchall()}
                    df = df[~df['invoice_id'].isin(existing_invoices)]

                # First, verify which customers exist
                if progress_callback:
                    progress_callback(40, 100, "Verifying customer records...")
                cursor.execute('SELECT customer_id FROM customers')
                valid_customers = {row[0] for row in cursor.fetchall()}

                # Process each record
                total_to_process = len(df)
                for idx, (_, row) in enumerate(df.iterrows()):
                    try:
                        if pd.isna(row['customer_id']) or str(row['customer_id']).strip() == '':
                            continue

                        # Check if customer exists
                        if row['customer_id'] not in valid_customers:
                            failed_records.append({
                                'invoice_id': row['invoice_id'],
                                'customer_id': row['customer_id'],
                                'customer_name': row['customer_name'],
                                'date_sold': row['date_sold'],
                                'error': 'Customer ID not found in database'
                            })
                            continue

                        # Insert the record
                        cursor.execute("""
                                INSERT INTO sales_history (
                                    invoice_id, customer_id, brand, units_sold, 
                                    item, customer_name, date_sold
                                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (
                            row['invoice_id'], row['customer_id'], row['brand'],
                            row['units_sold'], row['item'], row['customer_name'],
                            row['date_sold']
                        ))
                        successful_records.append(row['invoice_id'])

                        # Update progress
                        if progress_callback and idx % 10 == 0:
                            progress_value = 40 + (idx / total_to_process * 50)
                            progress_callback(
                                progress_value, 100,
                                f"Processing records: {idx}/{total_to_process}"
                            )

                    except Exception as e:
                        failed_records.append({
                            'invoice_id': row['invoice_id'],
                            'customer_id': row['customer_id'],
                            'customer_name': row['customer_name'],
                            'date_sold': row['date_sold'],
                            'error': str(e)
                        })

                # Save failed records if any
                if failed_records:
                    if progress_callback:
                        progress_callback(90, 100, "Saving failed records...")
                    failed_df = pd.DataFrame(failed_records)
                    failed_csv_path = csv_path.replace('.csv', '_failed_imports.csv')
                    failed_df.to_csv(failed_csv_path, index=False)

                if progress_callback:
                    progress_callback(100, 100, "Import complete!")

                summary = (
                    f"Successfully imported {len(successful_records)} records.\n"
                    f"Failed to import {len(failed_records)} records.\n"
                )

                if failed_records:
                    summary += f"Failed records saved to: {failed_csv_path}"

                return summary

        except Exception as e:
            if progress_callback:
                progress_callback(100, 100, f"Error: {str(e)}")
            raise Exception(f"Error importing CSV: {str(e)}")


class SalesTargetingGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Fruit Stand Sales Targeting")
        self.root.geometry("1000x800")

        # Initialize systems
        self.system = SalesTargetingSystem()
        self.comparison_system = ComparisonSystem()
        self.logger = get_logger('sales_targeting')

        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=5)

        # Create tabs
        self.setup_landing_tab()
        self.setup_comparison_tab()
        self.setup_targeting_tab()
        self.setup_call_tracking_tab()
        self.setup_import_tab()

    def setup_landing_tab(self):
        """Initialize the landing page tab with fruit theme"""
        landing_frame = ttk.Frame(self.notebook)
        self.notebook.add(landing_frame, text='Home')

        # Title at the top
        title_label = ttk.Label(
            landing_frame,
            text="Fruit Stand Sales Targeting",
            font=('Helvetica', 24, 'bold')
        )
        title_label.pack(pady=20)

        # Create info frame
        info_frame = ttk.Frame(landing_frame)
        info_frame.pack(expand=True, fill='both', padx=20)

        # System features description
        features = [
            ("📊 Sales Analysis", "Track performance by fruit category and variety"),
            ("🎯 Customer Targeting", "Find customers based on purchase history"),
            ("📞 Call Tracking", "Manage customer contacts and follow-ups"),
            ("📅 Seasonal Trends", "Monitor fruit sales patterns throughout the year")
        ]

        for icon, text in features:
            feature_frame = ttk.Frame(info_frame)
            feature_frame.pack(pady=10, fill='x')

            ttk.Label(
                feature_frame,
                text=f"{icon}  {text}",
                font=('Helvetica', 12)
            ).pack(anchor='w')

        # Quick start guide
        guide_frame = ttk.LabelFrame(landing_frame, text="Quick Start Guide")
        guide_frame.pack(fill='x', padx=20, pady=10)

        steps = [
            "1. Import your customer data using the Import Data tab",
            "2. Add sales records through CSV import",
            "3. Use the Fruit Analysis tab to view performance",
            "4. Find potential customers in the Find Customers tab",
            "5. Track your calls and follow-ups"
        ]

        for step in steps:
            ttk.Label(
                guide_frame,
                text=step,
                font=('Helvetica', 10)
            ).pack(anchor='w', padx=10, pady=2)

    def setup_comparison_tab(self):
        """Initialize the comparison system and create comparison interface"""
        self.logger.debug("Main App: Setting up comparison tab...")
        self.comparison_tab = ComparisonTab(self.notebook, self.comparison_system)
        self.logger.debug("Main App: Comparison tab setup complete")

    def setup_targeting_tab(self):
        """Initialize the customer targeting tab"""
        targeting_frame = ttk.Frame(self.notebook)
        self.notebook.add(targeting_frame, text='Find Customers')

        # Search criteria
        criteria_frame = ttk.LabelFrame(targeting_frame, text="Search Criteria")
        criteria_frame.pack(fill='x', padx=10, pady=5)

        # Category selection
        ttk.Label(criteria_frame, text="Fruit Category:").grid(row=0, column=0, padx=5, pady=5)
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(
            criteria_frame,
            textvariable=self.category_var,
            values=['', 'Apples', 'Grapes', 'Oranges']
        )
        self.category_combo.grid(row=0, column=1, padx=5, pady=5)
        self.category_combo.bind('<<ComboboxSelected>>', self.on_category_selected)

        # Variety selection
        ttk.Label(criteria_frame, text="Variety:").grid(row=1, column=0, padx=5, pady=5)
        self.variety_var = tk.StringVar()
        self.variety_combo = ttk.Combobox(criteria_frame, textvariable=self.variety_var)
        self.variety_combo.grid(row=1, column=1, padx=5, pady=5)

        # Refresh dropdowns button
        ttk.Button(
            criteria_frame,
            text="Refresh Lists",
            command=self.refresh_dropdowns
        ).grid(row=0, column=4, rowspan=2, padx=5, pady=5)

        # Big Banana button
        ttk.Button(
            criteria_frame,
            text="🍌 Big Banana",
            command=self.big_banana_search
        ).grid(row=0, column=2, rowspan=2, padx=5, pady=5)

        # Inactive days
        ttk.Label(criteria_frame, text="Days Inactive:").grid(row=2, column=0, padx=5, pady=5)
        self.days_var = tk.StringVar(value="75")
        ttk.Entry(criteria_frame, textvariable=self.days_var).grid(row=2, column=1, padx=5, pady=5)

        # Call Filter Days
        ttk.Label(criteria_frame, text="Call Filter Days:").grid(row=2, column=2, padx=5, pady=5)
        self.call_filter_days = tk.StringVar(value="90")
        ttk.Entry(criteria_frame, textvariable=self.call_filter_days).grid(row=2, column=3, padx=5, pady=5)

        # Cross-sell filter
        ttk.Label(criteria_frame, text="Cross-Sell Filter:").grid(row=3, column=2, padx=5, pady=5)
        self.cross_sell_var = tk.StringVar(value="")
        cross_sell_combo = ttk.Combobox(criteria_frame, textvariable=self.cross_sell_var)
        cross_sell_combo['values'] = [
            '',
            'Oranges → Apples',  # Standard to Premium
            'Oranges → Grapes',  # Standard to Specialty
            'Apples → Grapes',  # Premium to Specialty
            'Grapes → Apples'  # Specialty to Premium
        ]
        cross_sell_combo.grid(row=3, column=3, padx=5, pady=5)

        # Results limit
        ttk.Label(criteria_frame, text="Limit Results:").grid(row=3, column=0, padx=5, pady=5)
        self.limit_var = tk.StringVar(value="20")
        ttk.Entry(criteria_frame, textvariable=self.limit_var).grid(row=3, column=1, padx=5, pady=5)

        # Add current page tracking
        self.current_offset = 0
        self.total_count = 0

        # Navigation frame
        nav_frame = ttk.Frame(targeting_frame)
        nav_frame.pack(pady=5)

        # Add Export button
        ttk.Button(
            nav_frame,
            text="Export List",
            command=self.export_results
        ).pack(side='left', padx=5)

        # Search button
        ttk.Button(
            nav_frame,
            text="Find Potential Customers",
            command=lambda: self.find_customers(reset_offset=True)
        ).pack(side='left', padx=5)

        # Navigation buttons
        self.prev_button = ttk.Button(
            nav_frame,
            text="← Previous",
            command=self.previous_page,
            state='disabled'
        )
        self.prev_button.pack(side='left', padx=5)

        self.next_button = ttk.Button(
            nav_frame,
            text="Next →",
            command=self.next_page,
            state='disabled'
        )
        self.next_button.pack(side='left', padx=5)

        # Page info label
        self.page_info = ttk.Label(nav_frame, text="")
        self.page_info.pack(side='left', padx=5)

        # Results frame with scrollbar
        results_frame = ttk.Frame(targeting_frame)
        results_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Create scrollbar
        scrollbar = ttk.Scrollbar(results_frame)
        scrollbar.pack(side='right', fill='y')

        # Create treeview with scrollbar
        self.results_tree = ttk.Treeview(
            results_frame,
            columns=('ID', 'Name', 'Last Purchase', 'Count', 'Premium', 'Specialty', 'Last Call', 'Call Status'),
            show='headings',
            yscrollcommand=scrollbar.set
        )

        # Configure scrollbar
        scrollbar.config(command=self.results_tree.yview)

        # Setup headings
        self.results_tree.heading('ID', text='Customer ID')
        self.results_tree.heading('Name', text='Customer Name')
        self.results_tree.heading('Last Purchase', text='Last Purchase')
        self.results_tree.heading('Count', text='Orders')
        self.results_tree.heading('Premium', text='Premium')
        self.results_tree.heading('Specialty', text='Specialty')
        self.results_tree.heading('Last Call', text='Last Call')
        self.results_tree.heading('Call Status', text='Call Status')

        # Configure column widths
        self.results_tree.column('ID', width=80)
        self.results_tree.column('Name', width=150)
        self.results_tree.column('Last Purchase', width=85)
        self.results_tree.column('Count', width=50)
        self.results_tree.column('Premium', width=60)
        self.results_tree.column('Specialty', width=60)
        self.results_tree.column('Last Call', width=85)
        self.results_tree.column('Call Status', width=85)

        # Pack the treeview
        self.results_tree.pack(side='left', fill='both', expand=True)

        # Bind context menu and double-click
        self.results_tree.bind("<Button-3>", self.show_context_menu)
        self.results_tree.bind("<Double-1>", self.transfer_to_call_tracking)

        # Create context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Copy Customer ID", command=lambda: self.copy_to_clipboard("ID"))
        self.context_menu.add_command(label="Copy Customer Name", command=lambda: self.copy_to_clipboard("Name"))
        self.context_menu.add_command(label="Transfer to Call Tracking",
                                      command=lambda: self.transfer_to_call_tracking(None))

        # Initial population of dropdowns
        self.refresh_dropdowns()

    def setup_import_tab(self):
        """Initialize the import tab with fruit-specific terminology"""
        import_frame = ttk.Frame(self.notebook)
        self.notebook.add(import_frame, text='Import Data')

        # Create separate frames for sales and customer imports
        sales_frame = ttk.LabelFrame(import_frame, text="Fruit Sales Data Import")
        sales_frame.pack(fill='x', padx=10, pady=5)

        customer_frame = ttk.LabelFrame(import_frame, text="Customer Data Import")
        customer_frame.pack(fill='x', padx=10, pady=5)

        # Sales data import instructions
        ttk.Label(sales_frame,
                  text="Import your fruit sales data from a CSV file.\n"
                       "File should include: Invoice ID, Customer ID, Category, Variety, Units, Date",
                  justify='left').pack(pady=5)

        mode_frame = ttk.Frame(sales_frame)
        mode_frame.pack(fill='x', padx=10, pady=5)

        self.import_mode = tk.StringVar(value='append')
        ttk.Radiobutton(mode_frame,
                        text="Add New Records",
                        variable=self.import_mode,
                        value='append').pack(side='left', padx=5)
        ttk.Radiobutton(mode_frame,
                        text="Replace All Data",
                        variable=self.import_mode,
                        value='replace').pack(side='left', padx=5)

        ttk.Button(sales_frame,
                   text="Import Sales CSV",
                   command=self.import_csv).pack(pady=10)

        # Customer data import instructions
        ttk.Label(customer_frame,
                  text="Import your customer list from a CSV file.\n"
                       "File should include: Customer ID, Name, Email, Phone, Address, etc.",
                  justify='left').pack(pady=5)

        ttk.Button(customer_frame,
                   text="Import Customer CSV",
                   command=self.import_customer_csv).pack(pady=10)

        # Sample data frame
        sample_frame = ttk.LabelFrame(import_frame, text="Sample Data")
        sample_frame.pack(fill='x', padx=10, pady=5)

        ttk.Label(sample_frame,
                  text="Download sample CSV files to see the correct format:",
                  justify='left').pack(pady=5)

        ttk.Button(sample_frame,
                   text="Download Sample Customer CSV",
                   command=self.save_sample_customer_csv).pack(pady=2)

        ttk.Button(sample_frame,
                   text="Download Sample Sales CSV",
                   command=self.save_sample_sales_csv).pack(pady=2)

        # Status label
        self.import_status = ttk.Label(import_frame, text="")
        self.import_status.pack(pady=5)

    def save_sample_customer_csv(self):
        """Save sample customer CSV file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="sample_customers.csv"
        )
        if filename:
            with open(filename, 'w', newline='') as f:
                f.write("""Customer ID,First Name,Last Name,Email,Phone,Address,City,State,Postal Code
    CUST001,John,Smith,john.smith@email.com,(555) 123-4567,123 Main St,Springfield,IL,62701
    CUST002,Emily,Johnson,emily.j@email.com,(555) 234-5678,456 Oak Ave,Riverside,CA,92501
    CUST003,Michael,Davis,m.davis@email.com,(555) 345-6789,789 Maple Dr,Georgetown,TX,78626
    CUST004,Sarah,Wilson,s.wilson@email.com,(555) 456-7890,321 Pine Rd,Franklin,TN,37064
    CUST005,David,Brown,d.brown@email.com,(555) 567-8901,654 Cedar Ln,Salem,OR,97301""")
            self.import_status.config(
                text="Sample customer CSV saved successfully!",
                foreground="green"
            )

    def save_sample_sales_csv(self):
        """Save sample sales CSV file"""
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="sample_sales.csv"
        )
        if filename:
            with open(filename, 'w', newline='') as f:
                f.write("""Invoice ID,Customer ID,Customer Name,Category,Variety,Units,Date
    INV001,CUST001,John Smith,Apples,Honeycrisp,3,2024-02-01
    INV002,CUST001,John Smith,Grapes,Cotton Candy,2,2024-02-01
    INV003,CUST002,Emily Johnson,Oranges,Navel,5,2024-02-02
    INV004,CUST003,Michael Davis,Apples,Pink Lady,2,2024-02-02
    INV005,CUST002,Emily Johnson,Grapes,Moon Drops,4,2024-02-03
    INV006,CUST004,Sarah Wilson,Oranges,Blood Orange,3,2024-02-03
    INV007,CUST005,David Brown,Apples,Fuji,6,2024-02-04
    INV008,CUST001,John Smith,Oranges,Mandarin,4,2024-02-04
    INV009,CUST003,Michael Davis,Grapes,Concord,2,2024-02-05
    INV010,CUST004,Sarah Wilson,Apples,Granny Smith,3,2024-02-05""")
            self.import_status.config(
                text="Sample sales CSV saved successfully!",
                foreground="green"
            )

    def setup_call_tracking_tab(self):
        """Initialize the call tracking tab"""
        tracking_frame = ttk.Frame(self.notebook)
        self.notebook.add(tracking_frame, text='Call Tracking')

        # Customer info frame with 2 columns
        info_frame = ttk.LabelFrame(tracking_frame, text="Customer Information")
        info_frame.pack(fill='x', padx=10, pady=5)

        # Left column - Basic info
        left_frame = ttk.Frame(info_frame)
        left_frame.grid(row=0, column=0, padx=5, pady=5, sticky='nw')

        # Customer ID with lookup button
        id_frame = ttk.Frame(left_frame)
        id_frame.pack(fill='x')
        ttk.Label(id_frame, text="Customer ID:").pack(side='left')
        self.call_customer_id = tk.StringVar()
        ttk.Entry(id_frame, textvariable=self.call_customer_id).pack(side='left', padx=5)
        ttk.Button(id_frame, text="🔍", width=3,
                   command=self.lookup_customer).pack(side='left')

        # Customer name (read-only)
        name_frame = ttk.Frame(left_frame)
        name_frame.pack(fill='x', pady=5)
        ttk.Label(name_frame, text="Name:").pack(side='left')
        self.customer_name_var = tk.StringVar()
        ttk.Label(name_frame, textvariable=self.customer_name_var,
                  font=('TkDefaultFont', 10, 'bold')).pack(side='left', padx=5)

        # Right column - Contact info
        right_frame = ttk.Frame(info_frame)
        right_frame.grid(row=0, column=1, padx=5, pady=5, sticky='ne')

        # Phone number (with copy button)
        phone_frame = ttk.Frame(right_frame)
        phone_frame.pack(fill='x')
        ttk.Label(phone_frame, text="Phone:").pack(side='left')
        self.phone_var = tk.StringVar()
        ttk.Label(phone_frame, textvariable=self.phone_var,
                  font=('TkDefaultFont', 10, 'bold')).pack(side='left', padx=5)
        ttk.Button(phone_frame, text="📋", width=3,
                   command=lambda: self.copy_to_clipboard(self.phone_var.get())).pack(side='left')

        # Email (with copy button)
        email_frame = ttk.Frame(right_frame)
        email_frame.pack(fill='x', pady=5)
        ttk.Label(email_frame, text="Email:").pack(side='left')
        self.email_var = tk.StringVar()
        ttk.Label(email_frame, textvariable=self.email_var).pack(side='left', padx=5)
        ttk.Button(email_frame, text="📋", width=3,
                   command=lambda: self.copy_to_clipboard(self.email_var.get())).pack(side='left')

        # Address
        address_frame = ttk.Frame(right_frame)
        address_frame.pack(fill='x')
        self.address_var = tk.StringVar()
        ttk.Label(address_frame, textvariable=self.address_var).pack(side='left')

        # Purchase History Summary
        history_summary = ttk.LabelFrame(tracking_frame, text="Purchase History")
        history_summary.pack(fill='x', padx=10, pady=5)

        # Create grid for purchase history
        self.purchase_summary = {}
        categories = ['Apples', 'Grapes', 'Oranges']
        for i, category in enumerate(categories):
            ttk.Label(history_summary, text=f"{category}:").grid(row=i, column=0, padx=5, pady=2, sticky='w')
            var = tk.StringVar(value="0 units")
            ttk.Label(history_summary, textvariable=var).grid(row=i, column=1, padx=5, pady=2, sticky='w')
            self.purchase_summary[category] = var

        # Favorite category
        fav_frame = ttk.Frame(history_summary)
        fav_frame.grid(row=len(categories), column=0, columnspan=2, pady=5, sticky='w')
        ttk.Label(fav_frame, text="Favorite Category:").pack(side='left', padx=5)
        self.favorite_category = tk.StringVar()
        ttk.Label(fav_frame, textvariable=self.favorite_category,
                  font=('TkDefaultFont', 10, 'bold')).pack(side='left')

        # Call status and notes
        call_frame = ttk.LabelFrame(tracking_frame, text="Call Details")
        call_frame.pack(fill='x', padx=10, pady=5)

        # Call status
        status_frame = ttk.Frame(call_frame)
        status_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(status_frame, text="Call Status:").pack(side='left')
        self.call_status = tk.StringVar()
        self.status_combo = ttk.Combobox(
            status_frame,
            textvariable=self.call_status,
            values=['successful_sale', 'considering', 'left_message', 'no_answer', 'other']
        )
        self.status_combo.pack(side='left', padx=5)

        # Category and variety selection for the call
        category_frame = ttk.Frame(call_frame)
        category_frame.pack(fill='x', padx=5, pady=5)

        ttk.Label(category_frame, text="Discussed Category:").pack(side='left')
        self.call_category = tk.StringVar()
        category_combo = ttk.Combobox(
            category_frame,
            textvariable=self.call_category,
            values=['Apples', 'Grapes', 'Oranges']
        )
        category_combo.pack(side='left', padx=5)

        ttk.Label(category_frame, text="Variety:").pack(side='left', padx=5)
        self.call_variety = tk.StringVar()
        self.variety_combo = ttk.Combobox(
            category_frame,
            textvariable=self.call_variety
        )
        self.variety_combo.pack(side='left', padx=5)

        # Bind category selection to update varieties
        category_combo.bind('<<ComboboxSelected>>', self.update_call_varieties)

        # Notes
        ttk.Label(call_frame, text="Notes:").pack(anchor='w', padx=5, pady=2)
        self.call_notes = tk.Text(call_frame, height=4)
        self.call_notes.pack(fill='x', padx=5, pady=2)

        # Save button
        ttk.Button(
            tracking_frame,
            text="Record Call",
            command=self.record_call
        ).pack(pady=10)

        # Call history frame
        history_frame = ttk.LabelFrame(tracking_frame, text="Recent Call History")
        history_frame.pack(fill='both', expand=True, padx=10, pady=5)

        # Call history treeview
        self.history_tree = ttk.Treeview(
            history_frame,
            columns=('Date', 'Customer', 'Status', 'Notes', 'Category', 'Variety', 'Orders'),
            show='headings'
        )

        # Setup headings
        self.history_tree.heading('Date', text='Call Date')
        self.history_tree.heading('Customer', text='Customer')
        self.history_tree.heading('Status', text='Status')
        self.history_tree.heading('Notes', text='Notes')
        self.history_tree.heading('Category', text='Category')
        self.history_tree.heading('Variety', text='Variety')
        self.history_tree.heading('Orders', text='Total Orders')

        # Configure column widths
        self.history_tree.column('Date', width=100)
        self.history_tree.column('Customer', width=150)
        self.history_tree.column('Status', width=100)
        self.history_tree.column('Notes', width=200)
        self.history_tree.column('Category', width=100)
        self.history_tree.column('Variety', width=100)
        self.history_tree.column('Orders', width=100)

        # Add scrollbar
        history_scroll = ttk.Scrollbar(history_frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=history_scroll.set)

        # Pack elements
        self.history_tree.pack(side='left', fill='both', expand=True)
        history_scroll.pack(side='right', fill='y')

        # Refresh and export buttons frame
        button_frame = ttk.Frame(tracking_frame)
        button_frame.pack(fill='x', padx=10, pady=5)

        ttk.Button(
            button_frame,
            text="Refresh History",
            command=self.refresh_history
        ).pack(side='left', padx=5)

        ttk.Button(
            button_frame,
            text="Export Call History",
            command=self.export_call_history
        ).pack(side='left', padx=5)

    def update_call_varieties(self, event=None):
        """Update variety dropdown based on selected category"""
        category = self.call_category.get()
        if category in self.system.FRUIT_CATEGORIES:
            varieties = self.system.FRUIT_CATEGORIES[category]['items']
            self.variety_combo['values'] = varieties
            self.call_variety.set('')  # Clear current selection

    def refresh_dropdowns(self):
        """Refresh category and variety dropdowns"""
        try:
            with db_config.get_cursor() as cursor:
                # Get unique categories with sales
                cursor.execute("""
                    SELECT DISTINCT brand 
                    FROM sales_history 
                    WHERE brand IS NOT NULL 
                    AND brand != ''
                    ORDER BY brand
                """)
                categories = [row[0] for row in cursor.fetchall()]
                self.category_combo['values'] = [''] + categories

                # Get varieties for all categories initially
                placeholders = ','.join(['?'] * len(categories))
                cursor.execute(f"""
                    SELECT DISTINCT item 
                    FROM sales_history 
                    WHERE brand IN ({placeholders})
                    AND item IS NOT NULL 
                    AND item != '' 
                    ORDER BY item
                """, categories)
                varieties = [row[0] for row in cursor.fetchall()]
                self.variety_combo['values'] = [''] + varieties

        except Exception as e:
            messagebox.showerror("Error", f"Error refreshing lists: {str(e)}")

    def on_category_selected(self, event):
        """Handle category selection change"""
        try:
            selected_category = self.category_var.get()
            if selected_category:
                # Get varieties for selected category
                with db_config.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT DISTINCT item 
                        FROM sales_history 
                        WHERE brand = ?
                        AND item IS NOT NULL 
                        AND item != '' 
                        ORDER BY item
                    """, (selected_category,))
                    varieties = [row[0] for row in cursor.fetchall()]
                    self.variety_combo['values'] = [''] + varieties
                    self.variety_var.set('')  # Clear current selection
            else:
                # If no category selected, show all varieties
                self.refresh_dropdowns()

        except Exception as e:
            messagebox.showerror("Error", f"Error updating variety list: {str(e)}")

    def find_customers(self, reset_offset=True):
        """Find potential customers based on criteria"""
        try:
            category = self.category_var.get() or None
            variety = self.variety_var.get() or None
            days = int(self.days_var.get())
            call_days = int(self.call_filter_days.get())
            limit = int(self.limit_var.get())
            cross_sell = self.cross_sell_var.get()

            # If this is a new search, reset offset
            if reset_offset:
                self.current_offset = 0

            # Clear existing items
            for item in self.results_tree.get_children():
                self.results_tree.delete(item)

            # Get results
            results, self.total_count = self.system.get_potential_customers(
                target_item=variety,
                target_brand=category,
                days_inactive=days,
                call_filter_days=call_days,
                limit=limit,
                offset=self.current_offset,
                cross_sell_category=cross_sell if cross_sell else None
            )

            # Populate treeview
            for _, row in results.iterrows():
                self.results_tree.insert('', 'end', values=(
                    row['customer_id'],
                    row['customer_name'],
                    row['last_purchase_date'],
                    row['purchase_count'],
                    'Yes' if row['buys_premium'] else 'No',
                    'Yes' if row['buys_specialty'] else 'No',
                    row['last_call_date'] if pd.notna(row['last_call_date']) else '',
                    row['last_call_status'] if pd.notna(row['last_call_status']) else ''
                ))

            # Update navigation
            self.update_navigation()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def update_navigation(self):
        """Update navigation buttons and page information"""
        limit = int(self.limit_var.get())
        current_page = (self.current_offset // limit) + 1
        total_pages = (self.total_count + limit - 1) // limit

        # Update page info
        if self.total_count > 0:
            self.page_info.config(text=f"Page {current_page} of {total_pages} (Total: {self.total_count})")
        else:
            self.page_info.config(text="No results found")

        # Update button states
        self.prev_button.config(state='normal' if self.current_offset > 0 else 'disabled')
        self.next_button.config(state='normal' if self.current_offset + limit < self.total_count else 'disabled')

    def next_page(self):
        """Load next page of results"""
        limit = int(self.limit_var.get())
        self.current_offset += limit
        self.find_customers(reset_offset=False)

    def previous_page(self):
        """Load previous page of results"""
        limit = int(self.limit_var.get())
        self.current_offset = max(0, self.current_offset - limit)
        self.find_customers(reset_offset=False)

    def big_banana_search(self):
        """Perform Big Banana search for selected variety"""
        try:
            variety = self.variety_var.get()
            if not variety:
                messagebox.showerror("Error", "Please select a fruit variety first")
                return

            self.logger.debug(f"Starting Big Banana search for variety: {variety}")

            # Clear existing items
            for item in self.results_tree.get_children():
                self.results_tree.delete(item)

            # Get results
            results = self.system.get_big_banana_customers(variety)

            self.logger.debug(f"Found {len(results)} customers for Big Banana search")

            # Populate treeview
            for _, row in results.iterrows():
                self.results_tree.insert('', 'end', values=(
                    row['customer_id'],
                    row['customer_name'],
                    row['last_purchase_date'],
                    row['total_units'],
                    'Yes' if row['buys_premium'] else 'No',
                    'Yes' if row['buys_specialty'] else 'No',
                    row['last_call_date'] if pd.notna(row['last_call_date']) else '',
                    row['last_call_status'] if pd.notna(row['last_call_status']) else ''
                ))

            # Update navigation info
            self.page_info.config(text=f"Big Banana Results - Top {len(results)} Customers")
            self.prev_button.config(state='disabled')
            self.next_button.config(state='disabled')

        except Exception as e:
            self.logger.error(f"Error in big_banana_search: {str(e)}", exc_info=True)
            messagebox.showerror("Error", str(e))

    def export_results(self):
        """Export current results to CSV with contact information"""
        try:
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                initialfile="customer_list.csv"
            )

            if not filename:
                return

            # Get all items from treeview
            data = []
            customer_ids = []
            for item in self.results_tree.get_children():
                values = self.results_tree.item(item)['values']
                data.append({
                    'Customer ID': values[0],
                    'Customer Name': values[1],
                    'Last Purchase': values[2],
                    'Purchase Count': values[3],
                    'Buys Premium': values[4],
                    'Buys Specialty': values[5],
                    'Last Call': values[6],
                    'Call Status': values[7]
                })
                customer_ids.append(values[0])

            df = pd.DataFrame(data)

            # Get contact information
            with db_config.get_cursor() as cursor:
                placeholders = ','.join(['?' * len(customer_ids)])
                contact_query = f"""
                    SELECT 
                        customer_id,
                        first_name,
                        last_name,
                        email,
                        phone,
                        address,
                        city,
                        state,
                        postal_code
                    FROM customers
                    WHERE customer_id IN ({placeholders})
                """
                cursor.execute(contact_query, customer_ids)
                columns = [desc[0] for desc in cursor.description]
                contact_data = cursor.fetchall()
                contact_df = pd.DataFrame(contact_data, columns=columns)

            # Merge data
            final_df = pd.merge(df, contact_df, left_on='Customer ID', right_on='customer_id', how='left')
            final_df = final_df.drop('customer_id', axis=1)

            # Reorder columns
            column_order = [
                'Customer ID',
                'first_name',
                'last_name',
                'phone',
                'email',
                'address',
                'city',
                'state',
                'postal_code',
                'Last Purchase',
                'Purchase Count',
                'Buys Premium',
                'Buys Specialty',
                'Last Call',
                'Call Status'
            ]
            final_df = final_df[column_order]

            # Rename columns
            column_renames = {
                'first_name': 'First Name',
                'last_name': 'Last Name',
                'phone': 'Phone',
                'email': 'Email',
                'address': 'Address',
                'city': 'City',
                'state': 'State',
                'postal_code': 'Postal Code'
            }
            final_df = final_df.rename(columns=column_renames)

            # Export to CSV
            final_df.to_csv(filename, index=False)
            messagebox.showinfo("Success", "Results exported successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Error exporting results: {str(e)}")

    def lookup_customer(self):
        """Look up and display customer information"""
        customer_id = self.call_customer_id.get()
        if not customer_id:
            return

        self.logger.debug(f"Looking up customer: {customer_id}")

        try:
            customer_info = self.system.get_customer_info(customer_id)

            if customer_info:
                # Update display
                name = f"{customer_info.get('first_name', '')} {customer_info.get('last_name', '')}"
                self.customer_name_var.set(name)
                self.phone_var.set(customer_info.get('phone', ''))
                self.email_var.set(customer_info.get('email', ''))

                # Format address
                address_parts = []
                if customer_info.get('address'):
                    address_parts.append(customer_info['address'])
                if customer_info.get('city'):
                    address_parts.append(customer_info['city'])
                if customer_info.get('state'):
                    address_parts.append(customer_info['state'])
                if customer_info.get('postal_code'):
                    address_parts.append(customer_info['postal_code'])

                address = ', '.join(filter(None, address_parts))
                self.address_var.set(address)

                # Get purchase history by category
                with db_config.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            brand,
                            SUM(units_sold) as total_units,
                            COUNT(DISTINCT invoice_id) as order_count
                        FROM sales_history
                        WHERE customer_id = ?
                        GROUP BY brand
                    """, (customer_id,))

                    purchase_data = cursor.fetchall()

                    # Reset all category totals
                    for category in self.purchase_summary:
                        self.purchase_summary[category].set("0 units")

                    # Update with actual data
                    total_orders = 0
                    for brand, units, orders in purchase_data:
                        if brand in self.purchase_summary:
                            self.purchase_summary[brand].set(f"{int(units)} units ({orders} orders)")
                            total_orders += orders

                    # Set favorite category
                    favorite = max(purchase_data, key=lambda x: x[1])[0] if purchase_data else "None"
                    self.favorite_category.set(favorite)

            else:
                self.logger.info("No customer info found")
                messagebox.showwarning("Not Found", "Customer not found in database.")

        except Exception as e:
            self.logger.error(f"Error looking up customer: {str(e)}")
            messagebox.showerror("Error", f"Error looking up customer: {str(e)}")

    def record_call(self):
        """Record a customer call"""
        try:
            customer_id = self.call_customer_id.get()
            status = self.call_status.get()
            notes = self.call_notes.get("1.0", tk.END).strip()
            category = self.call_category.get()
            variety = self.call_variety.get()

            if not all([customer_id, status]):
                messagebox.showerror("Error", "Please fill in all required fields")
                return

            self.system.record_call(
                customer_id=customer_id,
                status=status,
                notes=notes,
                brand=category,
                item=variety
            )

            messagebox.showinfo("Success", "Call recorded successfully")
            self.refresh_history()

            # Clear fields
            self.call_status.set("")
            self.call_notes.delete("1.0", tk.END)
            self.call_category.set("")
            self.call_variety.set("")

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh_history(self):
        """Refresh the call history display"""
        try:
            # Clear existing items
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)

            # Get call history
            history = self.system.get_call_history()

            # Populate treeview
            for _, row in history.iterrows():
                self.history_tree.insert('', 'end', values=(
                    row['call_date'],
                    row['customer_name'],
                    row['status'],
                    row['notes'],
                    row['brand'] if pd.notna(row['brand']) else '',
                    row['item'] if pd.notna(row['item']) else '',
                    row['lifetime_orders']
                ))

        except Exception as e:
            messagebox.showerror("Error", f"Error refreshing history: {str(e)}")

    def export_call_history(self):
        """Export call history to CSV"""
        try:
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                initialfile="call_history.csv"
            )

            if filename:
                # Get all call history
                history = self.system.get_call_history(days_back=36500)  # Get all history

                # Rename columns for export
                column_renames = {
                    'call_date': 'Call Date',
                    'customer_name': 'Customer Name',
                    'status': 'Call Status',
                    'notes': 'Notes',
                    'brand': 'Fruit Category',
                    'item': 'Variety',
                    'lifetime_orders': 'Total Orders'
                }

                history = history.rename(columns=column_renames)

                # Reorder columns for better readability
                column_order = [
                    'Call Date',
                    'Customer Name',
                    'Call Status',
                    'Fruit Category',
                    'Variety',
                    'Notes',
                    'Total Orders'
                ]

                # Select and order columns
                export_df = history[column_order]

                # Export to CSV
                export_df.to_csv(filename, index=False)
                messagebox.showinfo("Success", "Call history exported successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Error exporting call history: {str(e)}")

    def copy_to_clipboard(self, text):
        """Copy text to clipboard"""
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def transfer_to_call_tracking(self, event=None):
        """Transfer customer to call tracking tab"""
        selected_items = self.results_tree.selection()
        if not selected_items:
            return

        # Get selected customer info
        item = selected_items[0]
        values = self.results_tree.item(item)['values']
        customer_id = values[0]

        # Switch to call tracking tab
        self.notebook.select(2)  # Index 2 should be the call tracking tab

        # Set the customer ID and trigger lookup
        self.call_customer_id.set(customer_id)
        self.lookup_customer()

        # Focus on status combobox
        try:
            self.status_combo.focus_set()
        except:
            pass  # If we can't set focus, just continue

    def show_context_menu(self, event):
        """Show context menu on right click"""
        try:
            item = self.results_tree.identify_row(event.y)
            if item:
                self.results_tree.selection_set(item)
                self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def copy_to_clipboard(self, text_type):
        """Copy selected customer information to clipboard"""
        selected_items = self.results_tree.selection()
        if not selected_items:
            return

        item = selected_items[0]
        values = self.results_tree.item(item)['values']

        if text_type == "ID":
            self.root.clipboard_clear()
            self.root.clipboard_append(values[0])  # Customer ID is first column
        elif text_type == "Name":
            self.root.clipboard_clear()
            self.root.clipboard_append(values[1])  # Customer Name is second column

    def import_csv(self):
        """Handle sales data CSV import"""
        filename = filedialog.askopenfilename(
            filetypes=[("CSV Files", "*.csv")]
        )
        if filename:
            try:
                mode = self.import_mode.get()
                if mode == 'replace':
                    if not messagebox.askyesno("Confirm Replace",
                                               "This will delete all existing sales data. Are you sure?"):
                        return

                # Create progress dialog
                progress_window = tk.Toplevel(self.root)
                progress_window.title("Importing Data")
                progress_window.geometry("300x150")
                progress_window.transient(self.root)
                progress_window.grab_set()

                # Add progress bar and labels
                ttk.Label(progress_window, text="Importing sales data...").pack(pady=10)
                progress_var = tk.DoubleVar()
                progress_bar = ttk.Progressbar(progress_window,
                                               variable=progress_var,
                                               maximum=100,
                                               mode='determinate')
                progress_bar.pack(fill='x', padx=20, pady=10)
                status_label = ttk.Label(progress_window, text="Reading file...")
                status_label.pack(pady=10)

                def update_progress(current, total, status=""):
                    progress_var.set((current / total) * 100)
                    if status:
                        status_label.config(text=status)
                    progress_window.update()

                def import_task():
                    try:
                        result = self.system.import_csv(filename, mode=mode, progress_callback=update_progress)
                        progress_window.destroy()
                        self.import_status.config(
                            text=result,
                            foreground="green"
                        )
                        self.refresh_dropdowns()
                    except Exception as e:
                        progress_window.destroy()
                        self.import_status.config(
                            text=f"Error importing file: {str(e)}",
                            foreground="red"
                        )

                # Start import in separate thread
                import threading
                thread = threading.Thread(target=import_task)
                thread.daemon = True
                thread.start()

            except Exception as e:
                self.import_status.config(
                    text=f"Error importing file: {str(e)}",
                    foreground="red"
                )

    def import_customer_csv(self):
        """Handle customer data CSV import"""
        filename = filedialog.askopenfilename(
            filetypes=[("CSV Files", "*.csv")]
        )
        if filename:
            try:
                result = self.system.import_customer_data(filename)
                self.import_status.config(
                    text=result,
                    foreground="green"
                )
            except Exception as e:
                self.import_status.config(
                    text=f"Error importing customer data: {str(e)}",
                    foreground="red"
                )

    def run(self):
        """Start the application main loop"""
        self.root.mainloop()


if __name__ == "__main__":
    app = SalesTargetingGUI()
    app.run()