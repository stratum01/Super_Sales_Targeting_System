import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib
matplotlib.use('TkAgg')  # Force TkAgg backend
from tkcalendar import DateEntry
from datetime import datetime, timedelta
import numpy as np
from logging_config import setup_logging, get_logger
from db_config import db_config

setup_logging()


class ComparisonSystem:
    WINE_BRANDS = [
        'PRIVATE RESERVE', 'RESERVE', 'ESTATE', 'CLASSIC', 'ORIGINAL',
        'ON THE HOUSE', 'ISLAND MIST', 'NIAGARA MIST',
        'REVELATION', 'LIMITED EDITION', 'PASSPORT', 'APRES'
    ]

    def __init__(self):
        self.logger = get_logger('comparison_system')

    def get_brand_performance(self, start_date1, end_date1, start_date2, end_date2):
        """Get sales performance data by brand and product"""
        self.logger.info(f"Querying data for periods: {start_date1} to {end_date1} and {start_date2} to {end_date2}")

        with db_config.get_cursor() as cursor:
            query = """
                WITH PeriodSales AS (
                    SELECT 
                        brand,
                        item,
                        SUM(CASE 
                            WHEN date_sold BETWEEN %s AND %s THEN units_sold 
                            ELSE 0 
                        END)::numeric as prev_year,
                        SUM(CASE 
                            WHEN date_sold BETWEEN %s AND %s THEN units_sold 
                            ELSE 0 
                        END)::numeric as curr_year
                    FROM sales_history
                    GROUP BY brand, item
                )
                SELECT 
                    brand,
                    item,
                    prev_year,
                    curr_year,
                    CASE 
                        WHEN prev_year = 0 THEN 100.0
                        ELSE ROUND(((curr_year - prev_year) * 100.0 / NULLIF(prev_year, 0))::numeric, 1)
                    END::float as growth
                FROM PeriodSales
                WHERE prev_year > 0 OR curr_year > 0
                ORDER BY brand, prev_year DESC
            """

            cursor.execute(query, (start_date1, end_date1, start_date2, end_date2))
            columns = [desc[0] for desc in cursor.description]
            data = cursor.fetchall()

            df = pd.DataFrame(data, columns=columns)
            # Ensure numeric types
            df['prev_year'] = pd.to_numeric(df['prev_year'])
            df['curr_year'] = pd.to_numeric(df['curr_year'])
            df['growth'] = pd.to_numeric(df['growth'])

            return df


    def analyze_brand_performance(self, df):
        """Analyze performance metrics for each brand"""
        results = {}

        for brand in self.WINE_BRANDS + ['OTHER']:
            if brand == 'OTHER':
                brand_data = df[~df['brand'].isin(self.WINE_BRANDS)]
            else:
                brand_data = df[df['brand'] == brand]

            if not brand_data.empty:
                total_prev = brand_data['prev_year'].sum()
                total_curr = brand_data['curr_year'].sum()
                growth = ((total_curr - total_prev) / total_prev * 100) if total_prev > 0 else 100

                top_products = brand_data.nlargest(15, 'curr_year')
                results[brand] = {
                    'total_prev': total_prev,
                    'total_curr': total_curr,
                    'growth': growth,
                    'products': top_products.to_dict('records')
                }

        return results


class PromotionManager:
    def __init__(self):
        self.current_year_promos = {}
        self.previous_year_promos = {}

    def add_promotion(self, year, period_number, start_date, end_date):
        """Add a promotion period to the manager"""
        promo = PromotionPeriod(period_number, start_date, end_date)
        if year == datetime.now().year:
            self.current_year_promos[period_number] = promo
        else:
            self.previous_year_promos[period_number] = promo

    def get_current_promo_comparison_dates(self):
        """Get the date ranges for comparing the current promotion period"""
        today = datetime.now().date()

        # Find current promotion period
        current_period = None
        for period in self.current_year_promos.values():
            if period.start_date <= today <= period.end_date:
                current_period = period
                break

        if not current_period:
            raise ValueError("No active promotion period found for today's date")

        days_elapsed = (today - current_period.start_date).days
        prev_period = self.previous_year_promos.get(current_period.period_number)

        if not prev_period:
            raise ValueError(f"No matching period {current_period.period_number} found for previous year")

        return (
            current_period.start_date,
            current_period.start_date + timedelta(days=days_elapsed),
            prev_period.start_date,
            prev_period.start_date + timedelta(days=days_elapsed)
        )


class PromotionPeriod:
    def __init__(self, period_number, start_date, end_date):
        self.period_number = period_number
        self.start_date = start_date
        self.end_date = end_date


class PromoSetupDialog:
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Promotion Period Setup")
        self.dialog.geometry("800x600")
        self.dialog.grab_set()  # Make dialog modal

        # Center dialog on parent window
        self.dialog.transient(parent)

        # Add scrollbar for many periods
        self.setup_scrollable_area()

        # Create period entries
        self.period_entries = {}
        self.setup_period_entries()

        # Create control buttons
        self.setup_controls()

        # Load existing periods
        self.load_existing_periods()

    def setup_scrollable_area(self):
        """Create scrollable canvas for period entries"""
        self.canvas = tk.Canvas(self.dialog)
        self.scrollbar = ttk.Scrollbar(self.dialog, orient="vertical", command=self.canvas.yview)
        self.content_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.content_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def setup_period_entries(self):
        """Create entry fields for promotion periods"""
        current_year = datetime.now().year
        years = [current_year - 1, current_year, current_year + 1]

        for year in years:
            year_frame = ttk.LabelFrame(self.content_frame, text=f"Promotion Periods {year}")
            year_frame.pack(padx=10, pady=5, fill='x')

            ttk.Label(year_frame, text="Period", width=10).grid(row=0, column=0, padx=5, pady=5)
            ttk.Label(year_frame, text="Start Date", width=15).grid(row=0, column=1, padx=5, pady=5)
            ttk.Label(year_frame, text="End Date", width=15).grid(row=0, column=2, padx=5, pady=5)
            ttk.Label(year_frame, text="Description", width=30).grid(row=0, column=3, padx=5, pady=5)

            for period in range(1, 18):
                ttk.Label(year_frame, text=f"Period {period}").grid(row=period, column=0, padx=5, pady=2)
                start_date = DateEntry(year_frame, width=12, date_pattern='yyyy-mm-dd')
                start_date.grid(row=period, column=1, padx=5, pady=2)
                end_date = DateEntry(year_frame, width=12, date_pattern='yyyy-mm-dd')
                end_date.grid(row=period, column=2, padx=5, pady=2)
                description = ttk.Entry(year_frame, width=30)
                description.grid(row=period, column=3, padx=5, pady=2)

                self.period_entries[f"{year}_p{period}"] = {
                    'start': start_date,
                    'end': end_date,
                    'description': description
                }

    def setup_controls(self):
        """Setup control buttons"""
        button_frame = ttk.Frame(self.dialog)
        button_frame.pack(pady=10, fill='x')
        ttk.Button(button_frame, text="Save Periods", command=self.save_periods).pack(side='left', padx=5)
        ttk.Button(button_frame, text="Close", command=self.dialog.destroy).pack(side='left', padx=5)

    def save_periods(self):
        """Save promotion periods to database"""
        try:
            with db_config.get_cursor() as cursor:
                # Clear existing periods
                cursor.execute("TRUNCATE promotion_periods")

                # Insert new periods
                for key, entries in self.period_entries.items():
                    year = int(key.split('_')[0])
                    period = int(key.split('_p')[1])

                    start_date = entries['start'].get_date()
                    end_date = entries['end'].get_date()
                    description = entries['description'].get()

                    # Only insert if dates are set
                    if start_date and end_date:
                        cursor.execute("""
                            INSERT INTO promotion_periods 
                            (year, period_number, start_date, end_date, description)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (year, period, start_date, end_date, description))

            messagebox.showinfo("Success", "Promotion periods saved successfully!")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to save promotion periods: {str(e)}")

    def load_existing_periods(self):
        """Load existing promotion periods from database"""
        try:
            with db_config.get_cursor() as cursor:
                cursor.execute("""
                    SELECT year, period_number, start_date, end_date, description 
                    FROM promotion_periods 
                    ORDER BY year, period_number
                """)

                for row in cursor.fetchall():
                    year, period, start_date, end_date, description = row
                    key = f"{year}_p{period}"

                    if key in self.period_entries:
                        self.period_entries[key]['start'].set_date(start_date)
                        self.period_entries[key]['end'].set_date(end_date)
                        if description:
                            self.period_entries[key]['description'].insert(0, description)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load promotion periods: {str(e)}")

    def _on_frame_configure(self, event=None):
        """Reset the scroll region to encompass the inner frame"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """When canvas is resized, resize the inner frame to match"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class ComparisonTab:
    def __init__(self, parent_notebook, comparison_system):
        """Initialize the comparison tab"""
        self.logger = get_logger('comparison_system')
        self.logger.debug("ComparisonTab: Starting initialization...")

        self.notebook = parent_notebook
        self.comparison_system = comparison_system
        self.promo_manager = PromotionManager()
        self.current_brand = None
        self.last_results = {}

        # Create main comparison frame
        self.comparison_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.comparison_frame, text='Brand Analysis')

        # Main container with fixed controls
        self.fixed_container = ttk.Frame(self.comparison_frame)
        self.fixed_container.pack(fill='x', expand=False)

        # Setup the scrollable area
        self.setup_scrollable_area()

        # Load saved promotion periods
        self.load_promotion_periods()

        # Initialize the UI
        self.setup_ui()



    def setup_scrollable_area(self):
        """Setup scrollable canvas for brand content"""
        # Create canvas and scrollbar
        self.canvas_container = ttk.Frame(self.comparison_frame)
        self.canvas_container.pack(fill='both', expand=True)

        # Create canvas with scrollbar
        self.canvas = tk.Canvas(self.canvas_container)
        self.scrollbar = ttk.Scrollbar(self.canvas_container, orient="vertical", command=self.canvas.yview)

        # Create frame inside canvas for content
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        # Configure canvas
        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Pack scrollbar and canvas
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        # Bind mouse wheel events
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)


    def setup_ui(self):
        """Initialize all UI elements"""
        # Date selection frame - pack into fixed container
        date_frame = ttk.LabelFrame(self.fixed_container, text="Select Time Periods")
        date_frame.pack(fill='x', padx=10, pady=5)

        # Quick selection buttons frame
        quick_frame = ttk.Frame(date_frame)
        quick_frame.pack(fill='x', padx=5, pady=5)

        buttons = [
            ("Last Week", self.set_last_week),
            ("This Week", self.set_this_week),
            ("Current Promotion", self.set_current_promo),
            ("Setup Promotions", self.show_promo_setup)
        ]

        for text, command in buttons:
            ttk.Button(quick_frame, text=text, command=command).pack(side='left', padx=5)

        # Date entry fields
        # Previous Period
        prev_frame = ttk.Frame(date_frame)
        prev_frame.pack(fill='x', padx=5, pady=2)

        ttk.Label(prev_frame, text="Previous Period:").pack(side='left', padx=5)
        self.start_date1 = DateEntry(prev_frame, width=12, date_pattern='yyyy-mm-dd')
        self.start_date1.pack(side='left', padx=5)
        ttk.Label(prev_frame, text="to").pack(side='left', padx=5)
        self.end_date1 = DateEntry(prev_frame, width=12, date_pattern='yyyy-mm-dd')
        self.end_date1.pack(side='left', padx=5)

        # Current Period
        curr_frame = ttk.Frame(date_frame)
        curr_frame.pack(fill='x', padx=5, pady=2)

        ttk.Label(curr_frame, text="Current Period:").pack(side='left', padx=5)
        self.start_date2 = DateEntry(curr_frame, width=12, date_pattern='yyyy-mm-dd')
        self.start_date2.pack(side='left', padx=5)
        ttk.Label(curr_frame, text="to").pack(side='left', padx=5)
        self.end_date2 = DateEntry(curr_frame, width=12, date_pattern='yyyy-mm-dd')
        self.end_date2.pack(side='left', padx=5)

        # Compare button
        ttk.Button(
            self.fixed_container,
            text="Compare Periods",
            command=self.compare_periods
        ).pack(pady=10)

        # Create frames for two rows of brand tabs
        self.top_row_frame = ttk.Frame(self.scrollable_frame)
        self.top_row_frame.pack(fill='x', padx=5, pady=2)
        self.bottom_row_frame = ttk.Frame(self.scrollable_frame)
        self.bottom_row_frame.pack(fill='x', padx=5, pady=2)

        # Content frame for selected brand
        self.brand_content_frame = ttk.Frame(self.scrollable_frame)
        self.brand_content_frame.pack(fill='both', expand=True, padx=5, pady=5)

        # Define brand layout
        top_row_brands = ['PRIVATE RESERVE', 'RESERVE', 'ESTATE', 'REVELATION', 'LIMITED EDITION', 'PASSPORT']
        bottom_row_brands = ['CLASSIC', 'ORIGINAL', 'ISLAND MIST', 'NIAGARA MIST', 'ON THE HOUSE', 'APRES', 'OTHER']

        # Initialize brand tabs and buttons
        self.brand_tabs = {}

        # Create top row buttons
        for brand in top_row_brands:
            btn = ttk.Button(
                self.top_row_frame,
                text=brand,
                command=lambda b=brand: self.show_brand_content(b)
            )
            btn.pack(side='left', padx=2, pady=2)

        # Create bottom row buttons
        for brand in bottom_row_brands:
            btn = ttk.Button(
                self.bottom_row_frame,
                text=brand,
                command=lambda b=brand: self.show_brand_content(b)
            )
            btn.pack(side='left', padx=2, pady=2)


    def show_brand_content(self, brand):
        """Show content for selected brand"""
        # Clear existing content
        for widget in self.brand_content_frame.winfo_children():
            widget.destroy()

        # Update current brand
        self.current_brand = brand

        # Show the content frame
        self.brand_content_frame.pack(fill='both', expand=True)

        # If we have data, update the display
        if hasattr(self, 'last_results') and brand in self.last_results:
            self.update_brand_tab(brand, self.last_results[brand])

    def compare_periods(self):
        """Perform comparison and update visualizations"""
        try:
            print("Starting comparison...")
            # Get dates from date pickers
            start1 = self.start_date1.get_date().strftime('%Y-%m-%d')
            end1 = self.end_date1.get_date().strftime('%Y-%m-%d')
            start2 = self.start_date2.get_date().strftime('%Y-%m-%d')
            end2 = self.end_date2.get_date().strftime('%Y-%m-%d')

            print(f"Comparing periods: {start1}-{end1} vs {start2}-{end2}")

            # Get comparison data
            df = self.comparison_system.get_brand_performance(start1, end1, start2, end2)
            print(f"Got performance data, {len(df)} rows")

            # Store results for brand details views
            results = self.comparison_system.analyze_brand_performance(df)
            self.last_results = results

            print("Showing performance summary...")
            # Show initial performance summary
            self.show_performance_summary(df)

            # Clear any current brand selection
            self.current_brand = None

            print("Comparison complete")

        except Exception as e:
            print(f"Error in compare_periods: {str(e)}")
            import traceback
            print(traceback.format_exc())
            messagebox.showerror("Error", f"Error comparing periods: {str(e)}")


    def show_performance_summary(self, df):
        """Show top and bottom performers across major brands"""
        try:
            self.logger.debug("Starting performance summary generation")

            # Clear existing content
            for widget in self.brand_content_frame.winfo_children():
                widget.destroy()

            # Configure main frame
            self.brand_content_frame.pack(fill='both', expand=True, padx=5, pady=5)

            # Create brand summary at the top
            summary_frame = ttk.LabelFrame(self.brand_content_frame, text="Brand Performance Summary")
            summary_frame.pack(fill='x', padx=5, pady=5)

            # Calculate brand totals
            brand_totals = {}
            for brand in self.comparison_system.WINE_BRANDS:
                brand_data = df[df['brand'] == brand]
                if not brand_data.empty:
                    prev_total = brand_data['prev_year'].sum()
                    curr_total = brand_data['curr_year'].sum()
                    growth = ((curr_total - prev_total) / prev_total * 100) if prev_total > 0 else 100
                    brand_totals[brand] = {
                        'prev_total': prev_total,
                        'curr_total': curr_total,
                        'growth': growth
                    }

            # Create two columns for brand summary
            left_col = ttk.Frame(summary_frame)
            left_col.pack(side='left', fill='both', expand=True, padx=5, pady=5)
            right_col = ttk.Frame(summary_frame)
            right_col.pack(side='left', fill='both', expand=True, padx=5, pady=5)

            # Sort brands by current period units
            sorted_brands = sorted(brand_totals.items(),
                                   key=lambda x: x[1]['curr_total'],
                                   reverse=True)

            # Split brands between columns
            mid_point = len(sorted_brands) // 2 + len(sorted_brands) % 2

            self.logger.debug(f"Displaying summary for {len(sorted_brands)} brands")

            # Helper function to create brand row
            def create_brand_row(parent, brand, data):
                frame = ttk.Frame(parent)
                frame.pack(fill='x', pady=2)

                # Brand name with growth indicator
                growth = data['growth']
                indicator = "↑" if growth > 0 else "↓" if growth < 0 else "→"
                color = "green" if growth > 0 else "red" if growth < 0 else "black"

                label_text = f"{brand} {indicator} {abs(growth):.1f}%"
                ttk.Label(frame, text=label_text, foreground=color).pack(side='left')

                # Units information
                units_text = f"Current: {int(data['curr_total'])} | Previous: {int(data['prev_total'])}"
                ttk.Label(frame, text=units_text).pack(side='right')

            # Populate columns
            for i, (brand, data) in enumerate(sorted_brands):
                if i < mid_point:
                    create_brand_row(left_col, brand, data)
                else:
                    create_brand_row(right_col, brand, data)

            # Filter and sort data for top/bottom performers
            self.logger.debug("Calculating top and bottom performers")

            # Create a copy instead of a view and ensure numeric types
            major_brands_df = df[df['brand'].isin(self.comparison_system.WINE_BRANDS)].copy()
            if major_brands_df.empty:
                ttk.Label(self.brand_content_frame,
                          text="No data available for the selected period",
                          font=('TkDefaultFont', 10)).pack(pady=20)
                return

            # Ensure all numeric columns are properly typed
            numeric_columns = ['prev_year', 'curr_year', 'growth']
            for col in numeric_columns:
                major_brands_df.loc[:, col] = pd.to_numeric(major_brands_df[col], errors='coerce')

            # Filter out any null values
            major_brands_df = major_brands_df.dropna(subset=numeric_columns)

            # Now we can safely get top and bottom products
            top_products = major_brands_df.nlargest(5, 'growth')
            bottom_products = major_brands_df.nsmallest(5, 'growth')

            # Create fixed-size frame for charts
            charts_frame = ttk.Frame(self.brand_content_frame, height=250)
            charts_frame.pack(fill='x', expand=False)
            charts_frame.pack_propagate(False)

            # Create equal-width frames for charts (using grid)
            charts_frame.grid_columnconfigure(0, weight=1, uniform='chart')
            charts_frame.grid_columnconfigure(1, weight=1, uniform='chart')

            top_frame = ttk.LabelFrame(charts_frame, text="Top 5 Performing Products")
            top_frame.grid(row=0, column=0, padx=5, pady=5, sticky='nsew')

            bottom_frame = ttk.LabelFrame(charts_frame, text="Bottom 5 Performing Products")
            bottom_frame.grid(row=0, column=1, padx=5, pady=5, sticky='nsew')

            self.logger.debug("Creating performance charts")
            self.create_chart(top_frame, top_products, is_top=True)
            self.create_chart(bottom_frame, bottom_products, is_top=False)

            # Add explanatory text
            ttk.Label(self.brand_content_frame,
                      text="Click on any brand button above to see detailed analysis",
                      font=('TkDefaultFont', 8, 'italic')).pack(pady=5)

            self.brand_content_frame.update()
            self.logger.debug("Performance summary display complete")

        except Exception as e:
            self.logger.error(f"Error in show_performance_summary: {str(e)}", exc_info=True)
            messagebox.showerror("Error", f"Error showing performance summary: {str(e)}")

    def create_chart(self, frame, data, is_top=True):
        """Helper method to create performance charts"""
        try:
            self.logger.debug(f"Creating {'top' if is_top else 'bottom'} performers chart")

            fig = Figure(figsize=(5, 3), dpi=100)
            ax = fig.add_subplot(111)

            x = range(len(data))
            bars = ax.bar(x, data['growth'], width=0.6)

            # Customize chart
            ax.set_xticks([])
            ax.set_ylabel('Growth %', fontsize=8)

            # Add labels inside bars
            for i, bar in enumerate(bars):
                height = bar.get_height()
                item_name = f"{data.iloc[i]['brand']}\n{data.iloc[i]['item'][:20]}"

                y_pos = height / 2 if is_top else height / 2
                ax.text(bar.get_x() + bar.get_width() / 2., y_pos,
                        item_name,
                        ha='center', va='center',
                        fontsize=7, color='white',
                        weight='bold',
                        rotation=90)

                if not is_top:
                    bar.set_color('#ff9999')

            # Set y-axis limits
            if is_top:
                ymax = max(data['growth']) * 1.1
                ax.set_ylim(0, ymax)
            else:
                ymin = min(data['growth']) * 1.1
                ax.set_ylim(ymin, 0)

            fig.tight_layout(pad=1.0)

            canvas = FigureCanvasTkAgg(fig, frame)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill='both', expand=True, padx=2, pady=2)

            self.logger.debug(f"Chart creation complete for {'top' if is_top else 'bottom'} performers")
            return canvas

        except Exception as e:
            self.logger.error(f"Error creating chart: {str(e)}", exc_info=True)
            raise


    def update_brand_tab(self, brand, data):
        """Update visualization and table for a brand tab"""
        # Clear existing content
        for widget in self.brand_content_frame.winfo_children():
            widget.destroy()

        if not data['products']:
            return

        # Create chart frame
        chart_frame = ttk.Frame(self.brand_content_frame)
        chart_frame.pack(fill='both', expand=True)

        # Create table frame
        table_frame = ttk.Frame(self.brand_content_frame)
        table_frame.pack(fill='both', expand=True)

        # Create bar chart
        fig = Figure(figsize=(12, 6))
        ax = fig.add_subplot(111)

        products = data['products'][:10]  # Top 10 products
        x = range(len(products))
        width = 0.35

        # Add padding to y-axis limits
        max_value = max(max(p['prev_year'] for p in products),
                        max(p['curr_year'] for p in products))
        ax.set_ylim(0, max_value * 1.2)

        # Previous year bars
        prev_bars = ax.bar([i - width / 2 for i in x],
                           [p['prev_year'] for p in products],
                           width,
                           label='Previous Year',
                           color='#66cc66')

        # Current year bars
        curr_bars = ax.bar([i + width / 2 for i in x],
                           [p['curr_year'] for p in products],
                           width,
                           label='Current Year')

        # Color current year bars
        for i, bar in enumerate(curr_bars):
            bar.set_color(self.get_bar_color(
                products[i]['prev_year'],
                products[i]['curr_year']
            ))

        # Customize chart
        ax.set_ylabel('Units Sold')
        ax.set_title(f'{brand} Performance Analysis')
        ax.set_xticks(x)
        ax.set_xticklabels([p['item'] for p in products], rotation=45, ha='right')
        ax.legend()

        # Add growth labels
        for i, product in enumerate(products):
            growth = product['growth']
            max_height = max(product['prev_year'], product['curr_year'])
            ax.text(i, max_height + (max_value * 0.05),
                    f"{growth:+.1f}%",
                    ha='center', va='bottom')

        # Adjust layout
        fig.tight_layout()

        # Add chart to frame
        canvas = FigureCanvasTkAgg(fig, chart_frame)
        canvas.draw()
        canvas_widget = canvas.get_tk_widget()
        canvas_widget.pack(fill='both', expand=True)

        # Create table
        tree = ttk.Treeview(
            table_frame,
            columns=('Product', 'Prev', 'Curr', 'Growth'),
            show='headings',
            height=15
        )

        # Setup headings
        tree.heading('Product', text='Product')
        tree.heading('Prev', text='Previous Year')
        tree.heading('Curr', text='Current Year')
        tree.heading('Growth', text='Growth %')

        # Configure columns
        tree.column('Product', width=200)
        tree.column('Prev', width=100)
        tree.column('Curr', width=100)
        tree.column('Growth', width=100)

        # Add scrollbar
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        # Pack elements
        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Populate table
        for product in data['products']:
            growth = product['growth']
            tree.insert('', 'end', values=(
                product['item'],
                f"{product['prev_year']:.1f}",
                f"{product['curr_year']:.1f}",
                f"{growth:+.1f}%"
            ))

        self.brand_tabs[brand] = {
            'frame': self.brand_content_frame,
            'chart_frame': chart_frame,
            'table_frame': table_frame,
            'tree': tree
        }

    def get_bar_color(self, prev_value, curr_value):
        """Determine bar color based on performance rules"""
        if curr_value == 0:
            return '#ff9999'  # Light red for discontinued

        if prev_value == 0:
            return '#ffcc00'  # Yellow for new products

        growth = ((curr_value - prev_value) / prev_value * 100) if prev_value > 0 else 100

        if growth < 0:
            return '#ff9999'  # Pink for decline
        elif growth <= 10:
            return '#3366cc'  # Blue for 0-10% growth
        else:
            return '#ffcc00'  # Yellow for >10% growth

    def load_promotion_periods(self):
        """Load saved promotion periods from database"""
        try:
            with db_config.get_cursor() as cursor:
                # Check if promotions table exists
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM pg_tables
                        WHERE schemaname = 'public' 
                        AND tablename = 'promotion_periods'
                    )
                """)

                table_exists = cursor.fetchone()[0]

                if not table_exists:
                    cursor.execute("""
                        CREATE TABLE promotion_periods (
                            id SERIAL PRIMARY KEY,
                            year INTEGER,
                            period_number INTEGER,
                            start_date DATE,
                            end_date DATE,
                            description TEXT,
                            UNIQUE(year, period_number))
                    """)

                # Load all promotion periods
                cursor.execute("""
                    SELECT year, period_number, start_date, end_date 
                    FROM promotion_periods 
                    ORDER BY year DESC, period_number
                """)

                for row in cursor.fetchall():
                    year, period, start_date, end_date = row
                    self.promo_manager.add_promotion(
                        year,
                        period,
                        start_date,
                        end_date
                    )

        except Exception as e:
            messagebox.showwarning(
                "Warning",
                f"Could not load promotion periods: {str(e)}\nPlease use Setup Promotions to configure."
            )

    def get_week_dates(self, for_current_week=True):
        """Get date range for current or previous week (Monday to Sunday)"""
        with db_config.get_cursor() as cursor:
            if for_current_week:
                cursor.execute("""
                    SELECT 
                        date_trunc('week', CURRENT_DATE)::date as monday,
                        (date_trunc('week', CURRENT_DATE) + interval '6 days')::date as sunday
                """)
            else:
                cursor.execute("""
                    SELECT 
                        (date_trunc('week', CURRENT_DATE) - interval '7 days')::date as monday,
                        (date_trunc('week', CURRENT_DATE) - interval '1 day')::date as sunday
                """)

            return cursor.fetchone()

    def set_last_week(self):
        """Set dates for last week and its year-ago comparison"""
        with db_config.get_cursor() as cursor:
            cursor.execute("""
                WITH dates AS (
                    SELECT 
                        (date_trunc('week', CURRENT_DATE) - interval '7 days')::date as last_monday,
                        (date_trunc('week', CURRENT_DATE) - interval '1 day')::date as last_sunday,
                        date_part('week', CURRENT_DATE - interval '7 days') as week_num,
                        extract(year from CURRENT_DATE - interval '1 year') as last_year
                )
                SELECT 
                    last_monday,
                    last_sunday,
                    (date_trunc('year', make_date(last_year::int, 1, 1)) + 
                     ((week_num - 1) * interval '7 days'))::date as prev_monday,
                    (date_trunc('year', make_date(last_year::int, 1, 1)) + 
                     ((week_num - 1) * interval '7 days') + interval '6 days')::date as prev_sunday
                FROM dates
            """)

            last_monday, last_sunday, prev_monday, prev_sunday = cursor.fetchone()

            # Set the date pickers
            self.start_date2.set_date(last_monday)
            self.end_date2.set_date(last_sunday)
            self.start_date1.set_date(prev_monday)
            self.end_date1.set_date(prev_sunday)

    def set_this_week(self):
        """Set dates for this week (through yesterday) and its year-ago comparison"""
        with db_config.get_cursor() as cursor:
            cursor.execute("""
                WITH dates AS (
                    SELECT 
                        date_trunc('week', CURRENT_DATE)::date as current_monday,
                        CURRENT_DATE - interval '1 day' as yesterday,
                        date_part('week', CURRENT_DATE) as week_num,
                        extract(year from CURRENT_DATE - interval '1 year') as last_year
                )
                SELECT 
                    current_monday,
                    yesterday,
                    (date_trunc('year', make_date(last_year::int, 1, 1)) +
                     ((week_num - 1) * interval '7 days'))::date as prev_monday,
                    (date_trunc('year', make_date(last_year::int, 1, 1)) +
                     ((week_num - 1) * interval '7 days') +
                     (extract(day from yesterday - current_monday) * interval '1 day'))::date as prev_end
                FROM dates
            """)

            current_monday, yesterday, prev_monday, prev_end = cursor.fetchone()

            # Set the date pickers
            self.start_date2.set_date(current_monday)
            self.end_date2.set_date(yesterday)
            self.start_date1.set_date(prev_monday)
            self.end_date1.set_date(prev_end)

    def set_current_promo(self):
        """Set date ranges to compare current promotion period"""
        try:
            curr_start, curr_end, prev_start, prev_end = \
                self.promo_manager.get_current_promo_comparison_dates()

            # Set the date pickers
            self.start_date1.set_date(prev_start)
            self.end_date1.set_date(prev_end)
            self.start_date2.set_date(curr_start)
            self.end_date2.set_date(curr_end)

            # Automatically trigger comparison
            self.compare_periods()

        except ValueError as e:
            messagebox.showerror("Error", str(e))
        except Exception as e:
            messagebox.showerror(
                "Error",
                "Could not set promotion dates. Please check promotion period setup."
            )

    def show_promo_setup(self):
        """Show the promotion period setup dialog"""
        try:
            # Create and show dialog
            dialog = PromoSetupDialog(self.notebook.winfo_toplevel())
            dialog.dialog.wait_window()  # Wait for dialog to close

            # Reload periods
            self.load_promotion_periods()

            # Reset any cached data
            self.last_results = {}

            # Update display if needed
            if self.current_brand:
                self.show_brand_content(self.current_brand)

        except Exception as e:
            messagebox.showerror("Error", f"Error setting up promotions: {str(e)}")

    def _on_frame_configure(self, event=None):
        """Reset the scroll region to encompass the inner frame"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """When canvas is resized, resize the inner frame to match"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        """Handle mousewheel scrolling"""
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def __del__(self):
        """Cleanup any resources"""
        pass