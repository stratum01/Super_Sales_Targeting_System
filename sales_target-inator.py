import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from PIL import Image, ImageTk
from db_config import db_config
from comparison_system import ComparisonSystem, ComparisonTab
from logging_config import setup_logging, get_logger
from psycopg2.extras import execute_values

setup_logging()


class SalesTargetingSystem:
    def __init__(self):
        self.logger = get_logger('sales_targeting')
        # Initialize database if needed
        db_config.setup_database()

    def import_customer_data(self, csv_path):
        """Import customer contact information from CSV file"""
        try:
            self.logger.info(f"Starting import from {csv_path}")

            # Read CSV file
            df = pd.read_csv(csv_path, dtype=str)
            df = df.iloc[:, 1:]  # Drop the first column

            # Map column names
            column_mapping = {
                'Customer ID': 'customer_id',
                'First Name': 'first_name',
                'Last Name': 'last_name',
                'Email Address': 'email',
                'Phone (Home)': 'phone',
                'Address 1': 'address',
                'City': 'city',
                'Province': 'province',
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
                    if pd.isna(row['customer_id']) or str(row['customer_id']).strip() == '' or '(Totals)' in str(
                            row['customer_id']):
                        continue

                    customer_data = {
                        'customer_id': row['customer_id'],
                        'first_name': row['first_name'],
                        'last_name': row['last_name'],
                        'email': row['email'],
                        'phone': row['phone'],
                        'address': row['address'],
                        'city': row['city'],
                        'province': row['province'],
                        'postal_code': row['postal_code']
                    }

                    if row['customer_id'] in existing_customers:
                        # Update existing customer
                        cursor.execute("""
                            UPDATE customers 
                            SET first_name=%(first_name)s, 
                                last_name=%(last_name)s, 
                                email=%(email)s, 
                                phone=%(phone)s, 
                                address=%(address)s,
                                city=%(city)s, 
                                province=%(province)s, 
                                postal_code=%(postal_code)s
                            WHERE customer_id=%(customer_id)s
                        """, customer_data)
                        updated_records += 1
                    else:
                        # Insert new customer
                        cursor.execute("""
                            INSERT INTO customers (
                                customer_id, first_name, last_name, email, phone,
                                address, city, province, postal_code
                            ) VALUES (
                                %(customer_id)s, %(first_name)s, %(last_name)s, 
                                %(email)s, %(phone)s, %(address)s, %(city)s, 
                                %(province)s, %(postal_code)s
                            )
                        """, customer_data)
                        new_records += 1

            return f"Successfully processed {len(df)} records: {new_records} new, {updated_records} updated"

        except Exception as e:
            self.logger.error(f"Error in import_customer_data: {str(e)}", exc_info=True)
            raise Exception(f"Error importing customer data: {str(e)}")

    def import_csv(self, csv_path, mode='append'):
        """Import sales data from CSV file"""
        try:
            # Read CSV with all columns as strings initially
            df = pd.read_csv(csv_path, dtype=str)
            df = df.iloc[:, 1:]  # Drop the first column

            # Clean column names
            df.columns = df.columns.str.strip().str.strip('"')

            # Rename columns
            column_mapping = {
                'Units Sold': 'units_sold',
                'Date Sold': 'date_sold',
                'Name': 'customer_name',
                'BRAND': 'brand',
                'ITEM': 'item',
                'Customer ID': 'customer_id',
                'Invoice ID': 'invoice_id'
            }
            df = df.rename(columns=column_mapping)

            # Convert Date Sold to datetime
            df['date_sold'] = pd.to_datetime(df['date_sold'].str.strip('"'), format='%m/%d/%Y')

            # Convert Units Sold to numeric
            df['units_sold'] = pd.to_numeric(df['units_sold'].str.strip('"'), errors='coerce')

            # Clean string columns
            string_columns = ['customer_id', 'brand', 'item', 'customer_name', 'invoice_id']
            for col in string_columns:
                df[col] = df[col].str.strip('"')

            with db_config.get_cursor() as cursor:
                if mode == 'replace':
                    cursor.execute('TRUNCATE TABLE sales_history CASCADE')
                else:
                    # Get existing invoice IDs
                    cursor.execute('SELECT DISTINCT invoice_id FROM sales_history')
                    existing_invoices = {row[0] for row in cursor.fetchall()}
                    df = df[~df['invoice_id'].isin(existing_invoices)]

                if not df.empty:
                    # Prepare data for bulk insert
                    data = [
                        (row['invoice_id'], row['customer_id'], row['brand'],
                         row['units_sold'], row['item'], row['customer_name'],
                         row['date_sold'])
                        for _, row in df.iterrows()
                    ]

                    # Bulk insert using execute_values
                    execute_values(
                        cursor,
                        """
                        INSERT INTO sales_history (
                            invoice_id, customer_id, brand, units_sold, 
                            item, customer_name, date_sold
                        ) VALUES %s
                        """,
                        data,
                        template='(%s, %s, %s, %s, %s, %s, %s)'
                    )

                    return f"Successfully imported {len(df)} new records"
                return "No new records to import"

        except Exception as e:
            raise Exception(f"Error importing CSV: {str(e)}")

    def get_customer_info(self, customer_id):
        """Get customer contact information"""
        with db_config.get_cursor() as cursor:
            query = """
                SELECT 
                    c.*,
                    COALESCE(sh.total_purchases, 0) as total_purchases,
                    COALESCE(sh.total_units, 0) as total_units,
                    sh.last_purchase
                FROM customers c
                LEFT JOIN (
                    SELECT 
                        customer_id,
                        COUNT(DISTINCT invoice_id) as total_purchases,
                        SUM(units_sold) as total_units,
                        MAX(date_sold) as last_purchase
                    FROM sales_history
                    GROUP BY customer_id
                ) sh ON c.customer_id = sh.customer_id
                WHERE c.customer_id = %s
            """

            cursor.execute(query, (customer_id,))
            columns = [desc[0] for desc in cursor.description]
            row = cursor.fetchone()

            if row:
                return dict(zip(columns, row))
            return None

    def get_hot_potato_customers(self, target_item, limit=20):
        """Get customers who have bought the specified item the most"""
        if not target_item:
            raise ValueError("Item must be specified for Hot Potato search")

        with db_config.get_cursor() as cursor:
            query = """
            WITH CustomerPurchases AS (
                SELECT 
                    sh.customer_id,
                    MAX(sh.customer_name) as customer_name,
                    COUNT(*) as purchase_count,
                    SUM(sh.units_sold) as total_units,
                    MAX(sh.date_sold) as last_purchase_date,
                    MAX(CASE WHEN sh.brand IN ('RESERVE', 'PRIVATE RESERVE', 'REVELATION', 
                                           'LIMITED EDITION', 'PASSPORT', 'ESTATE') 
                        THEN 1 ELSE 0 END) as buys_premiums,
                    MAX(CASE WHEN sh.brand = 'WOP' THEN 1 ELSE 0 END) as makes_onsite
                FROM sales_history sh
                WHERE sh.item = %s
                GROUP BY sh.customer_id
            )
            SELECT 
                cp.*,
                latest_call.last_call_date,
                latest_call.last_call_status
            FROM CustomerPurchases cp
            LEFT JOIN LATERAL (
                SELECT 
                    call_date as last_call_date,
                    status as last_call_status
                FROM call_tracking ct
                WHERE ct.customer_id = cp.customer_id
                ORDER BY call_date DESC
                LIMIT 1
            ) latest_call ON true
            ORDER BY cp.total_units DESC
            LIMIT %s
            """

            cursor.execute(query, (target_item, limit))
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()

            return pd.DataFrame(data, columns=columns)

    def get_potential_customers(self, target_item=None, target_brand=None, days_inactive=75,
                                call_filter_days=90, limit=20, offset=0,
                                additional_where="", additional_params=None):
        """Find potential customers based on past purchases and inactivity period"""
        try:
            with db_config.get_cursor() as cursor:
                # Base parameters
                params = [call_filter_days]

                # Count query for pagination
                count_query = """
                    WITH LastPurchase AS (
                        SELECT 
                            customer_id,
                            customer_name,
                            MAX(date_sold) as last_purchase_date,
                            COUNT(DISTINCT invoice_id) as purchase_count
                        FROM sales_history
                        GROUP BY customer_id, customer_name
                    ),
                    RecentCalls AS (
                        SELECT DISTINCT customer_id
                        FROM call_tracking
                        WHERE CURRENT_DATE - call_date <= %s::integer
                          AND status != 'no_answer'
                    ),
                    CustomerBrandItem AS (
                        SELECT DISTINCT 
                            h.customer_id,
                            h.customer_name
                        FROM sales_history h
                        WHERE 1=1
                """

                if target_item:
                    count_query += " AND h.item = %s"
                    params.append(target_item)
                if target_brand:
                    count_query += " AND h.brand = %s"
                    params.append(target_brand)

                count_query += """
                    )
                    SELECT COUNT(*) as total_count
                    FROM CustomerBrandItem cbi
                    JOIN LastPurchase lp ON cbi.customer_id = lp.customer_id
                    LEFT JOIN RecentCalls rc ON cbi.customer_id = rc.customer_id
                    WHERE CURRENT_DATE - lp.last_purchase_date >= %s
                        AND rc.customer_id IS NULL
                """

                if additional_where:
                    count_query += " " + additional_where

                params.append(days_inactive)
                if additional_params:
                    params.extend(additional_params)

                cursor.execute(count_query, params)
                total_count = cursor.fetchone()[0]

                # Main query
                query = """
                    WITH LastPurchase AS (
                        SELECT 
                            customer_id,
                            customer_name,
                            MAX(date_sold) as last_purchase_date,
                            COUNT(DISTINCT invoice_id) as purchase_count
                        FROM sales_history
                        GROUP BY customer_id, customer_name
                    ),
                    RecentCalls AS (
                        SELECT DISTINCT customer_id
                        FROM call_tracking
                        WHERE CURRENT_DATE - call_date <= %s::integer
                          AND status != 'no_answer'
                    ),
                    CustomerBrandItem AS (
                        SELECT DISTINCT 
                            h.customer_id,
                            h.customer_name
                        FROM sales_history h
                        WHERE 1=1
                """

                # Reset params for main query
                params = [call_filter_days]

                if target_item:
                    query += " AND h.item = %s"
                    params.append(target_item)
                if target_brand:
                    query += " AND h.brand = %s"
                    params.append(target_brand)

                query += """
                    ),
                    CustomerPreferences AS (
                        SELECT 
                            customer_id,
                            MAX(CASE WHEN brand IN ('ESTATE', 'RESERVE', 'PRIVATE RESERVE', 
                                                  'LIMITED EDITION', 'PASSPORT', 'REVELATION')
                                THEN 1 ELSE 0 END) as buys_premiums,
                            MAX(CASE WHEN brand = 'WOP' THEN 1 ELSE 0 END) as makes_onsite
                        FROM sales_history
                        GROUP BY customer_id
                    )
                    SELECT 
                        cbi.customer_id,
                        cbi.customer_name,
                        lp.last_purchase_date,
                        lp.purchase_count,
                        cp.buys_premiums,
                        cp.makes_onsite,
                        latest_call.last_call_date,
                        latest_call.last_call_status
                    FROM CustomerBrandItem cbi
                    JOIN LastPurchase lp ON cbi.customer_id = lp.customer_id
                    LEFT JOIN CustomerPreferences cp ON cbi.customer_id = cp.customer_id
                    LEFT JOIN RecentCalls rc ON cbi.customer_id = rc.customer_id
                    LEFT JOIN LATERAL (
                        SELECT 
                            call_date as last_call_date,
                            status as last_call_status
                        FROM call_tracking ct
                        WHERE ct.customer_id = cbi.customer_id
                        ORDER BY call_date DESC
                        LIMIT 1
                    ) latest_call ON true
                    WHERE CURRENT_DATE - lp.last_purchase_date >= %s
                        AND rc.customer_id IS NULL
                """

                if additional_where:
                    query += " " + additional_where

                params.extend([days_inactive])
                if additional_params:
                    params.extend(additional_params)

                query += """
                    ORDER BY lp.last_purchase_date DESC
                    LIMIT %s OFFSET %s
                """
                params.extend([limit, offset])

                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                data = cursor.fetchall()

                df = pd.DataFrame(data, columns=columns)
                return df, total_count

        except Exception as e:
            self.logger.error(f"Error in get_potential_customers: {str(e)}", exc_info=True)
            raise

    def record_call(self, customer_id, status, notes, brand=None, item=None):
        """Record the outcome of a sales call"""
        with db_config.get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO call_tracking (
                    customer_id, call_date, status, notes, brand, item
                ) VALUES (
                    %s, CURRENT_DATE, %s, %s, %s, %s
                )
            ''', (customer_id, status, notes, brand, item))

    def get_call_history(self, days_back=30, customer_id=None):
        """Retrieve call history for specified period and/or customer"""
        with db_config.get_cursor() as cursor:
            query = """
                SELECT 
                    ct.*,
                    sh.customer_name,
                    sh.brand as last_brand_purchased,
                    sh.item as last_item_purchased,
                    SUM(sh2.units_sold) as lifetime_units,
                    COUNT(DISTINCT sh2.invoice_id) as lifetime_orders
                FROM call_tracking ct
                JOIN (
                    SELECT DISTINCT ON (customer_id) 
                        customer_id, 
                        customer_name, 
                        brand, 
                        item,
                        date_sold
                    FROM sales_history 
                    ORDER BY customer_id, date_sold DESC
                ) sh ON ct.customer_id = sh.customer_id
                LEFT JOIN sales_history sh2 ON ct.customer_id = sh2.customer_id
                WHERE ct.call_date >= CURRENT_DATE - interval '%s days'
            """

            params = [days_back]

            # Add customer_id filter if provided
            if customer_id:
                query = query.replace(
                    "WHERE ct.call_date",
                    "WHERE ct.customer_id = %s AND ct.call_date"
                )
                params = [customer_id] + params

            query += """
                GROUP BY 
                    ct.call_id, 
                    ct.customer_id, 
                    ct.call_date, 
                    ct.status,
                    ct.notes, 
                    ct.brand, 
                    ct.item, 
                    sh.customer_name, 
                    sh.brand, 
                    sh.item
                ORDER BY ct.call_date DESC
            """

            cursor.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()

            return pd.DataFrame(data, columns=columns)

    def __del__(self):
        """Cleanup database connections"""
        db_config.close_pool()

class SalesTargetingGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Sales Targeting System")
        self.root.geometry("800x600")

        # Initialize systems
        self.system = SalesTargetingSystem()
        self.comparison_system = ComparisonSystem()  # Updated for PostgreSQL
        self.logger = get_logger('sales_targeting')

        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=10, pady=5)

        # Create tabs
        self.setup_import_tab()
        self.setup_targeting_tab()
        self.setup_call_tracking_tab()
        self.setup_comparison_tab()

    def setup_comparison_tab(self):
        """Initialize the comparison system and create comparison interface"""
        self.logger.debug("Main App: Setting up comparison tab...")
        self.comparison_tab = ComparisonTab(self.notebook, self.comparison_system)
        self.logger.debug("Main App: Comparison tab setup complete")

    def setup_import_tab(self):
        import_frame = ttk.Frame(self.notebook)
        self.notebook.add(import_frame, text='Import Data')

        # Create separate frames for sales and customer imports
        sales_frame = ttk.LabelFrame(import_frame, text="Sales Data Import")
        sales_frame.pack(fill='x', padx=10, pady=5)

        customer_frame = ttk.LabelFrame(import_frame, text="Customer Data Import")
        customer_frame.pack(fill='x', padx=10, pady=5)

        # Sales data import widgets
        ttk.Button(
            sales_frame,
            text="How to Get Sales Data",
            command=self.show_import_instructions
        ).pack(pady=10)

        mode_frame = ttk.Frame(sales_frame)
        mode_frame.pack(fill='x', padx=10, pady=5)

        self.import_mode = tk.StringVar(value='append')
        ttk.Radiobutton(mode_frame, text="Append New Records",
                        variable=self.import_mode, value='append').pack(side='left', padx=5)
        ttk.Radiobutton(mode_frame, text="Replace All Data",
                        variable=self.import_mode, value='replace').pack(side='left', padx=5)

        ttk.Button(
            sales_frame,
            text="Import Sales CSV",
            command=self.import_csv
        ).pack(pady=10)

        # Customer data import widgets
        ttk.Button(
            customer_frame,
            text="Import Customer CSV",
            command=self.import_customer_csv
        ).pack(pady=10)

        # Status label (shared between both)
        self.import_status = ttk.Label(import_frame, text="")
        self.import_status.pack(pady=5)

        # Add Promotion Periods Import section
        promo_frame = ttk.LabelFrame(import_frame, text="Promotion Periods Import")
        promo_frame.pack(fill='x', padx=10, pady=5)

        # Add format instructions
        format_text = """CSV Format:
        year,period_number,start_date,end_date,description"""

        ttk.Label(promo_frame,
                  text=format_text,
                  justify='left',
                  font=('Courier', 9)).pack(pady=5, padx=5)

        ttk.Button(
            promo_frame,
            text="Import Promotion Periods",
            command=self.import_promotion_periods
        ).pack(pady=5)

    def show_import_instructions(self):
        """Show instructions dialog for getting data from Point of Sale"""
        dialog = tk.Toplevel(self.root)
        dialog.title("How to Get Data from Point of Sale")
        dialog.geometry("600x500")
        dialog.grab_set()  # Make the dialog modal

        # Make dialog appear near the center of the main window
        dialog.transient(self.root)

        # Instructions frame with scrollbar
        frame = ttk.Frame(dialog)
        frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side='right', fill='y')

        # Instructions text
        text_widget = tk.Text(frame, wrap='word', yscrollcommand=scrollbar.set,
                              width=60, height=20)
        text_widget.pack(side='left', fill='both', expand=True)

        # Configure scrollbar
        scrollbar.config(command=text_widget.yview)

        # Add instructions text
        instructions = """To get data for this application:

    1. Open Smart Vendor
    2. Under Reports, Select Report Generator
    3. Expand Customers, then Double Click Invoice Details
    4. Choose "1. Use Existing Report" from the Prompt
    5. On the Right Panel for Custom Reports, Double Click the "PromoSalesComparisionReport" report
    6. On the Left Panel for Report Menu, Double Click "Filter Data"
    7. On the Right Panel for Selected Fields, Adjust the Date Sold. Typical Range 1 Year back from Today
    8. Click "Page Down|Save", and back at the Filter Data Panel, Click F9|Continue
    9. On the Left Panel for Report Menu, Double Click "Export Report"
    10. Click "1. Comma Delimited (CSV)"
    11. Click "1. Detail, SubTotals and Totals"
    12. Save the file to your computer to Import Here
    """
        text_widget.insert('1.0', instructions)
        text_widget.config(state='disabled')  # Make text read-only

        # Close button
        close_btn = ttk.Button(dialog, text="Close", command=dialog.destroy)
        close_btn.pack(pady=10)

    def import_promotion_periods(self):
        """Handle promotion periods CSV import"""
        filename = filedialog.askopenfilename(
            filetypes=[("CSV Files", "*.csv")]
        )
        if filename:
            try:
                result = self.system.import_promotion_periods(filename)
                self.import_status.config(
                    text=result,
                    foreground="green"
                )
            except Exception as e:
                self.import_status.config(
                    text=f"Error importing promotion periods: {str(e)}",
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

    def import_csv(self):
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

                result = self.system.import_csv(filename, mode=mode)
                self.import_status.config(
                    text=result,
                    foreground="green"
                )
                self.refresh_dropdowns()
            except Exception as e:
                self.import_status.config(
                    text=f"Error importing file: {str(e)}",
                    foreground="red"
                )

    def setup_targeting_tab(self):
        targeting_frame = ttk.Frame(self.notebook)
        self.notebook.add(targeting_frame, text='Find Customers')

        # Search criteria
        criteria_frame = ttk.LabelFrame(targeting_frame, text="Search Criteria")
        criteria_frame.pack(fill='x', padx=10, pady=5)

        self.current_search = {
            'brand': None,
            'item': None,
            'days': None
        }

        # Brand combobox
        ttk.Label(criteria_frame, text="Brand:").grid(row=0, column=0, padx=5, pady=5)
        self.brand_var = tk.StringVar()
        self.brand_combo = ttk.Combobox(criteria_frame, textvariable=self.brand_var)
        self.brand_combo.grid(row=0, column=1, padx=5, pady=5)

        # Item combobox
        ttk.Label(criteria_frame, text="Item:").grid(row=1, column=0, padx=5, pady=5)
        self.item_var = tk.StringVar()
        self.item_combo = ttk.Combobox(criteria_frame, textvariable=self.item_var)
        self.item_combo.grid(row=1, column=1, padx=5, pady=5)

        # Refresh dropdowns button
        ttk.Button(
            criteria_frame,
            text="Refresh Lists",
            command=self.refresh_dropdowns
        ).grid(row=0, column=4, rowspan=2, padx=5, pady=5)

        # Add Hot Potato button below Refresh Lists
        ttk.Button(
            criteria_frame,
            text="🔥 Hot Potato",
            command=self.hot_potato_search
        ).grid(row=0, column=2, rowspan=2, padx=5, pady=5)

        # Inactive days
        ttk.Label(criteria_frame, text="Days Inactive:").grid(row=2, column=0, padx=5, pady=5)
        self.days_var = tk.StringVar(value="75")
        ttk.Entry(criteria_frame, textvariable=self.days_var).grid(row=2, column=1, padx=5, pady=5)

        # Call Filter Days
        ttk.Label(criteria_frame, text="Call Filter Days:").grid(row=2, column=2, padx=5, pady=5)
        self.call_filter_days = tk.StringVar(value="90")
        ttk.Entry(criteria_frame, textvariable=self.call_filter_days).grid(row=2, column=3, padx=5, pady=5)

        # Cross-sell filter option
        ttk.Label(criteria_frame, text="Cross-Sell Filter:").grid(row=3, column=2, padx=5, pady=5)
        self.cross_sell_var = tk.StringVar(value="")
        cross_sell_combo = ttk.Combobox(criteria_frame, textvariable=self.cross_sell_var)
        cross_sell_combo['values'] = [
            '',
            'CLASSIC → PREMIUM',
            'ISLAND MIST → CLASSIC',
            'NIAGARA MIST → CLASSIC',
            'ORIGINAL → CLASSIC'
        ]
        cross_sell_combo.grid(row=3, column=3, padx=5, pady=5)

        # Limit results
        ttk.Label(criteria_frame, text="Limit Results:").grid(row=3, column=0, padx=5, pady=5)
        self.limit_var = tk.StringVar(value="20")
        ttk.Entry(criteria_frame, textvariable=self.limit_var).grid(row=3, column=1, padx=5, pady=5)

        # Add current page tracking
        self.current_offset = 0
        self.total_count = 0

        # Navigation frame
        nav_frame = ttk.Frame(targeting_frame)
        nav_frame.pack(pady=5)

        # Add Export button next to navigation buttons
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

        # Previous button
        self.prev_button = ttk.Button(
            nav_frame,
            text="← Previous",
            command=self.previous_page,
            state='disabled'
        )
        self.prev_button.pack(side='left', padx=5)

        # Next button
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

        # Create scrollbar first
        scrollbar = ttk.Scrollbar(results_frame)
        scrollbar.pack(side='right', fill='y')

        # Create treeview with scrollbar
        self.results_tree = ttk.Treeview(
            results_frame,
            columns=('ID', 'Name', 'Last Purchase', 'Count', 'Prems', 'Onsite', 'Last Call', 'Call Status'),
            show='headings',
            yscrollcommand=scrollbar.set
        )

        # Configure scrollbar
        scrollbar.config(command=self.results_tree.yview)

        # Setup headings
        self.results_tree.heading('ID', text='Customer ID')
        self.results_tree.heading('Name', text='Customer Name')
        self.results_tree.heading('Last Purchase', text='Last Purchase')
        self.results_tree.heading('Count', text='Count')
        self.results_tree.heading('Prems', text='Prems')
        self.results_tree.heading('Onsite', text='Onsite')
        self.results_tree.heading('Last Call', text='Last Call')
        self.results_tree.heading('Call Status', text='Call Status')

        # Configure column widths
        self.results_tree.column('ID', width=80)
        self.results_tree.column('Name', width=150)
        self.results_tree.column('Last Purchase', width=85)
        self.results_tree.column('Count', width=50)
        self.results_tree.column('Prems', width=50)
        self.results_tree.column('Onsite', width=50)
        self.results_tree.column('Last Call', width=85)
        self.results_tree.column('Call Status', width=85)

        # Pack the treeview
        self.results_tree.pack(side='left', fill='both', expand=True)

        # Add right-click menu for copying
        self.results_tree.bind("<Button-3>", self.show_context_menu)
        # Add double-click handler
        self.results_tree.bind("<Double-1>", self.transfer_to_call_tracking)

        # Create right-click menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Copy Customer ID", command=lambda: self.copy_to_clipboard("ID"))
        self.context_menu.add_command(label="Copy Customer Name", command=lambda: self.copy_to_clipboard("Name"))
        self.context_menu.add_command(label="Transfer to Call Tracking",
                                      command=lambda: self.transfer_to_call_tracking(None))

        # Initial population of dropdowns
        self.refresh_dropdowns()

    def refresh_dropdowns(self):
        try:
            with db_config.get_cursor() as cursor:
                # Get unique brands
                cursor.execute("""
                    SELECT DISTINCT brand 
                    FROM sales_history 
                    WHERE brand IS NOT NULL AND brand != '' 
                    ORDER BY brand
                """)
                brands = [row[0] for row in cursor.fetchall()]
                self.brand_combo['values'] = [''] + brands

                # Get unique items
                cursor.execute("""
                    SELECT DISTINCT item 
                    FROM sales_history 
                    WHERE item IS NOT NULL AND item != '' 
                    ORDER BY item
                """)
                items = [row[0] for row in cursor.fetchall()]
                self.item_combo['values'] = [''] + items

        except Exception as e:
            messagebox.showerror("Error", f"Error refreshing lists: {str(e)}")

    def update_navigation(self):
        """Update navigation buttons and page information"""
        limit = int(self.limit_var.get())
        current_page = (self.current_offset // limit) + 1
        total_pages = (self.total_count + limit - 1) // limit  # Ceiling division

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
        if self.current_search['brand'] is None and self.current_search['item'] is None:
            messagebox.showerror("Error", "Please perform a search first")
            return

        limit = int(self.limit_var.get())
        self.current_offset += limit
        self.find_customers(reset_offset=False)

    def previous_page(self):
        """Load previous page of results"""
        if self.current_search['brand'] is None and self.current_search['item'] is None:
            messagebox.showerror("Error", "Please perform a search first")
            return

        limit = int(self.limit_var.get())
        self.current_offset = max(0, self.current_offset - limit)
        self.find_customers(reset_offset=False)

    def find_customers(self, reset_offset=True):
        """Find potential customers based on criteria"""
        try:
            brand = self.brand_var.get() or None
            item = self.item_var.get() or None
            days = int(self.days_var.get())
            call_days = int(self.call_filter_days.get())
            limit = int(self.limit_var.get())
            cross_sell = self.cross_sell_var.get()

            additional_where = ""
            additional_params = None

            # Handle cross-sell filter
            if cross_sell and "→ PREMIUM" in cross_sell:
                from_brand = cross_sell.split("→")[0].strip()

                with db_config.get_cursor() as cursor:
                    # Define premium brands
                    premium_brands = [
                        'ESTATE', 'RESERVE', 'PRIVATE RESERVE',
                        'LIMITED EDITION', 'PASSPORT', 'REVELATION'
                    ]
                    premium_placeholders = ','.join(['%s'] * len(premium_brands))

                    query = """
                    WITH ClassicBuyers AS (
                        -- Get customers who bought the from_brand
                        SELECT DISTINCT sh.customer_id
                        FROM sales_history sh
                        WHERE sh.brand = %s
                    ),
                    NonPremiumBuyers AS (
                        -- Get customers who have NEVER bought premium brands
                        SELECT DISTINCT cb.customer_id
                        FROM ClassicBuyers cb
                        WHERE NOT EXISTS (
                            SELECT 1 
                            FROM sales_history sh
                            WHERE sh.customer_id = cb.customer_id
                            AND sh.brand IN ({premium_brands})
                        )
                    )
                    SELECT customer_id
                    FROM NonPremiumBuyers
                    """.format(premium_brands=premium_placeholders)

                    # First parameter is from_brand, followed by premium brands list
                    params = [from_brand] + premium_brands
                    cursor.execute(query, params)

                    eligible_customers = [row[0] for row in cursor.fetchall()]

                    if not eligible_customers:
                        messagebox.showinfo(
                            "No Results",
                            f"No customers found who bought {from_brand} but haven't tried premium wines"
                        )
                        return

                    # Set up additional WHERE clause and parameters for main query
                    placeholders = ','.join(['%s'] * len(eligible_customers))
                    additional_where = f"AND cbi.customer_id IN ({placeholders})"
                    additional_params = eligible_customers

                    # Remove brand filter since we're using customer list
                    brand = None

            # If this is a new search (not pagination), update the search parameters
            if reset_offset:
                self.current_search = {
                    'brand': brand,
                    'item': item,
                    'days': days,
                    'call_days': call_days
                }
                self.current_offset = 0
            else:
                # Use the stored search parameters for pagination
                brand = self.current_search['brand']
                item = self.current_search['item']
                days = self.current_search['days']
                call_days = self.current_search['call_days']

            # Clear existing items
            for item_id in self.results_tree.get_children():
                self.results_tree.delete(item_id)

            # Get results with pagination
            results, self.total_count = self.system.get_potential_customers(
                target_item=item,
                target_brand=brand,
                days_inactive=days,
                call_filter_days=call_days,
                limit=limit,
                offset=self.current_offset,
                additional_where=additional_where,
                additional_params=additional_params
            )

            # Populate treeview
            for _, row in results.iterrows():
                self.results_tree.insert('', 'end', values=(
                    row['customer_id'],
                    row['customer_name'],
                    row['last_purchase_date'],
                    row['purchase_count'],
                    'Yes' if row['buys_premiums'] else 'No',
                    'Yes' if row['makes_onsite'] else 'No',
                    row['last_call_date'] if pd.notna(row['last_call_date']) else '',
                    row['last_call_status'] if pd.notna(row['last_call_status']) else ''
                ))

            # Update navigation buttons and info
            self.update_navigation()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def export_results(self):
        """Export current results to CSV with contact information"""
        try:
            # Get file save location
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                initialfile="customer_list.csv"
            )

            if not filename:
                return

            self.logger.debug(f"Exporting results to {filename}")

            # Get all items from treeview
            data = []
            tree_columns = ['Customer ID', 'Customer Name', 'Last Purchase', 'Count/Units',
                            'Buys Premium', 'Makes Onsite', 'Last Call', 'Call Status']

            # Get customer IDs for lookup
            customer_ids = []
            for item in self.results_tree.get_children():
                values = self.results_tree.item(item)['values']
                data.append(dict(zip(tree_columns, values)))
                customer_ids.append(values[0])  # Customer ID is first column

            self.logger.debug(f"Found {len(customer_ids)} customers to export")

            # Convert to DataFrame
            df = pd.DataFrame(data)

            # Get contact information from database
            with db_config.get_cursor() as cursor:
                placeholders = ','.join(['%s'] * len(customer_ids))
                contact_query = f"""
                    SELECT 
                        customer_id,
                        first_name,
                        last_name,
                        email,
                        phone,
                        address,
                        city,
                        province,
                        postal_code
                    FROM customers
                    WHERE customer_id IN ({placeholders})
                """
                cursor.execute(contact_query, customer_ids)
                columns = [desc[0] for desc in cursor.description]
                contact_data = cursor.fetchall()
                contact_df = pd.DataFrame(contact_data, columns=columns)

                self.logger.debug(f"Retrieved contact info for {len(contact_data)} customers")

            # Merge contact information with existing data
            final_df = pd.merge(df, contact_df, left_on='Customer ID', right_on='customer_id', how='left')

            # Drop duplicate customer_id column
            final_df = final_df.drop('customer_id', axis=1)

            # Reorder columns for better readability
            column_order = [
                'Customer ID',
                'first_name',
                'last_name',
                'phone',
                'email',
                'address',
                'city',
                'province',
                'postal_code',
                'Last Purchase',
                'Count/Units',
                'Buys Premium',
                'Makes Onsite',
                'Last Call',
                'Call Status'
            ]
            final_df = final_df[column_order]

            # Rename columns for clarity
            column_renames = {
                'first_name': 'First Name',
                'last_name': 'Last Name',
                'phone': 'Phone',
                'email': 'Email',
                'address': 'Address',
                'city': 'City',
                'province': 'Province',
                'postal_code': 'Postal Code'
            }
            final_df = final_df.rename(columns=column_renames)

            # Export to CSV
            self.logger.debug(f"Writing CSV to {filename}")
            final_df.to_csv(filename, index=False)
            messagebox.showinfo("Success", "Results exported successfully!")

        except Exception as e:
            self.logger.error(f"Export error: {str(e)}", exc_info=True)
            messagebox.showerror("Error", f"Error exporting results: {str(e)}")

    def hot_potato_search(self):
        """Perform Hot Potato search for selected item"""
        try:
            item = self.item_var.get()
            if not item:
                messagebox.showerror("Error", "Please select an item first")
                return

            # Clear existing items
            for item_id in self.results_tree.get_children():
                self.results_tree.delete(item_id)

            # Get results
            results = self.system.get_hot_potato_customers(item)

            # Populate treeview
            for _, row in results.iterrows():
                self.results_tree.insert('', 'end', values=(
                    row['customer_id'],
                    row['customer_name'],
                    row['last_purchase_date'],
                    row['total_units'],
                    'Yes' if row['buys_premiums'] else 'No',
                    'Yes' if row['makes_onsite'] else 'No',
                    row['last_call_date'] if pd.notna(row['last_call_date']) else '',
                    row['last_call_status'] if pd.notna(row['last_call_status']) else ''
                ))

            # Update navigation info
            self.page_info.config(text=f"Hot Potato Results - Top {len(results)} Customers")
            self.prev_button.config(state='disabled')
            self.next_button.config(state='disabled')

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def show_context_menu(self, event):
        """Show context menu on right click"""
        try:
            item = self.results_tree.identify_row(event.y)
            if item:
                self.results_tree.selection_set(item)
                self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def copy_to_clipboard(self, column):
        """Copy selected customer information to clipboard"""
        selected_items = self.results_tree.selection()
        if not selected_items:
            return

        item = selected_items[0]
        values = self.results_tree.item(item)['values']

        if column == "ID":
            self.root.clipboard_clear()
            self.root.clipboard_append(values[0])
        elif column == "Name":
            self.root.clipboard_clear()
            self.root.clipboard_append(values[1])

    def transfer_to_call_tracking(self, event):
        """Transfer customer info to call tracking tab"""
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

        # Find and focus the status combobox
        try:
            for widget in self.root.winfo_children():
                if isinstance(widget, ttk.Combobox) and str(widget.cget('textvariable')) == str(self.call_status):
                    widget.focus_set()
                    break
        except:
            pass  # If we can't set focus, just continue

    def setup_call_tracking_tab(self):
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

        # Call status and notes
        call_frame = ttk.LabelFrame(tracking_frame, text="Call Details")
        call_frame.pack(fill='x', padx=10, pady=5)

        # Call status
        ttk.Label(call_frame, text="Call Status:").pack(anchor='w', padx=5, pady=2)
        self.call_status = tk.StringVar()
        self.status_combo = ttk.Combobox(
            call_frame,
            textvariable=self.call_status,
            values=['successful_sale', 'considering', 'left_message', 'no_answer', 'other']
        )
        self.status_combo.pack(fill='x', padx=5, pady=2)

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
            columns=('Date', 'Customer', 'Status', 'Notes', 'Last Brand', 'Last Item', 'Total Orders'),
            show='headings'
        )

        # Setup headings
        self.history_tree.heading('Date', text='Call Date')
        self.history_tree.heading('Customer', text='Customer')
        self.history_tree.heading('Status', text='Status')
        self.history_tree.heading('Notes', text='Notes')
        self.history_tree.heading('Last Brand', text='Last Brand')
        self.history_tree.heading('Last Item', text='Last Item')
        self.history_tree.heading('Total Orders', text='Total Orders')

        # Configure column widths
        self.history_tree.column('Date', width=100)
        self.history_tree.column('Customer', width=150)
        self.history_tree.column('Status', width=100)
        self.history_tree.column('Notes', width=200)
        self.history_tree.column('Last Brand', width=100)
        self.history_tree.column('Last Item', width=100)
        self.history_tree.column('Total Orders', width=100)

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

    def lookup_customer(self):
        """Look up and display customer information"""
        customer_id = self.call_customer_id.get()
        if not customer_id:
            return

        self.logger.debug(f"Looking up customer: {customer_id}")

        customer_info = self.system.get_customer_info(customer_id)
        self.logger.debug(f"Customer info returned: {customer_info}")

        if customer_info:
            # Update display
            name = f"{customer_info.get('first_name', '')} {customer_info.get('last_name', '')}"
            self.logger.debug(f"Setting name to: {name}")
            self.customer_name_var.set(name)
            self.phone_var.set(customer_info.get('phone', ''))
            self.email_var.set(customer_info.get('email', ''))

            # Format address
            address_parts = []
            if customer_info.get('address'):
                address_parts.append(customer_info['address'])
            if customer_info.get('city'):
                address_parts.append(customer_info['city'])
            if customer_info.get('province'):
                address_parts.append(customer_info['province'])
            if customer_info.get('postal_code'):
                address_parts.append(customer_info['postal_code'])

            address = ', '.join(filter(None, address_parts))
            self.logger.debug(f"Setting address to: {address}")
            self.address_var.set(address)
        else:
            self.logger.info("No customer info found")
            messagebox.showwarning("Not Found", "Customer not found in database.")

    def record_call(self):
        try:
            customer_id = self.call_customer_id.get()
            status = self.call_status.get()
            notes = self.call_notes.get("1.0", tk.END).strip()

            if not all([customer_id, status]):
                messagebox.showerror("Error", "Please fill in all required fields")
                return

            self.system.record_call(
                customer_id=customer_id,
                status=status,
                notes=notes
            )

            messagebox.showinfo("Success", "Call recorded successfully")
            self.refresh_history()

            # Clear fields
            self.call_customer_id.set("")
            self.call_status.set("")
            self.call_notes.delete("1.0", tk.END)

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def refresh_history(self):
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
                row['last_brand_purchased'],
                row['last_item_purchased'],
                row['lifetime_orders']
            ))

    def export_call_history(self):
        """Export all call history to CSV"""
        try:
            # Get file save location
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv")],
                initialfile="call_history.csv"
            )

            if filename:
                # Get call history
                history = self.system.get_call_history(days_back=36500)  # Get all history

                # Export to CSV
                history.to_csv(filename, index=False)
                messagebox.showinfo("Success", "Call history exported successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Error exporting call history: {str(e)}")

    def run(self):
        self.root.mainloop()

# Main entry point
if __name__ == "__main__":
    app = SalesTargetingGUI()
    app.run()