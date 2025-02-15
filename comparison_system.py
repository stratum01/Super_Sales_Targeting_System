import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib
matplotlib.use('TkAgg')
from tkcalendar import DateEntry
from datetime import datetime, timedelta
import numpy as np
from logging_config import setup_logging, get_logger
from db_config import db_config

setup_logging()

class ComparisonSystem:
    # Define our fruit categories
    FRUIT_BRANDS = [
        'Apples',  # Premium fruit
        'Grapes',  # Specialty items
        'Oranges'  # Standard produce
    ]

    FRUIT_COLORS = {
        'Apples': '#ff6b6b',  # Red
        'Grapes': '#cc5de8',  # Purple
        'Oranges': '#ffa94d'  # Orange
    }

    def __init__(self):
        self.logger = get_logger('comparison_system')

    def get_brand_performance(self, start_date1, end_date1, start_date2, end_date2):
        """Get sales performance data by fruit category and variety"""
        self.logger.info(f"Querying data for periods: {start_date1} to {end_date1} and {start_date2} to {end_date2}")

        with db_config.get_cursor() as cursor:
            query = """
                WITH PeriodSales AS (
                    SELECT 
                        brand,
                        item,
                        SUM(CASE 
                            WHEN date_sold BETWEEN ? AND ? THEN units_sold 
                            ELSE 0 
                        END) as prev_year,
                        SUM(CASE 
                            WHEN date_sold BETWEEN ? AND ? THEN units_sold 
                            ELSE 0 
                        END) as curr_year
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
                        ELSE ROUND(((curr_year - prev_year) * 100.0 / prev_year), 1)
                    END as growth
                FROM PeriodSales
                WHERE prev_year > 0 OR curr_year > 0
                ORDER BY brand, prev_year DESC
            """

            cursor.execute(query, (start_date1, end_date1, start_date2, end_date2))
            columns = ['brand', 'item', 'prev_year', 'curr_year', 'growth']
            data = cursor.fetchall()

            df = pd.DataFrame(data, columns=columns)
            return df

    def get_current_period_info(self):
        """Get current period information"""
        with db_config.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    month,
                    description,
                    start_date,
                    end_date,
                    julianday('now') - julianday(start_date) + 1 as days_elapsed,
                    julianday(end_date) - julianday(start_date) + 1 as total_days
                FROM promotion_periods
                WHERE start_date <= date('now') 
                AND end_date >= date('now')
                ORDER BY year DESC, month DESC
                LIMIT 1
            """)

            result = cursor.fetchone()
            if not result:
                raise ValueError("No active promotion period found for current date")

            month, description, start_date, end_date, days_elapsed, total_days = result
            progress_percent = (days_elapsed / total_days) * 100

            return {
                'month': month,
                'description': description,
                'start_date': datetime.strptime(start_date, '%Y-%m-%d').date(),
                'end_date': datetime.strptime(end_date, '%Y-%m-%d').date(),
                'days_elapsed': int(days_elapsed),
                'total_days': int(total_days),
                'progress_percent': round(progress_percent, 1)
            }

    def analyze_brand_performance(self, df):
        """Analyze performance metrics for each fruit category"""
        results = {}

        for brand in self.FRUIT_BRANDS:
            brand_data = df[df['brand'] == brand]

            if not brand_data.empty:
                total_prev = brand_data['prev_year'].sum()
                total_curr = brand_data['curr_year'].sum()
                growth = ((total_curr - total_prev) / total_prev * 100) if total_prev > 0 else 100

                # Get top products
                top_products = brand_data.nlargest(10, 'curr_year')

                results[brand] = {
                    'total_prev': total_prev,
                    'total_curr': total_curr,
                    'growth': growth,
                    'products': top_products.to_dict('records'),
                    'color': self.FRUIT_COLORS.get(brand, '#868e96')  # Default gray if brand not found
                }

        return results

    def get_seasonal_trends(self, year=None):
        """Get seasonal sales trends by fruit category"""
        if not year:
            year = datetime.now().year

        with db_config.get_cursor() as cursor:
            query = """
                SELECT 
                    brand,
                    strftime('%m', date_sold) as month,
                    SUM(units_sold) as total_units
                FROM sales_history
                WHERE strftime('%Y', date_sold) = ?
                GROUP BY brand, month
                ORDER BY month, brand
            """

            cursor.execute(query, (str(year),))
            data = cursor.fetchall()

            df = pd.DataFrame(data, columns=['brand', 'month', 'total_units'])
            df['month'] = pd.to_numeric(df['month'])

            return df

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
        self.notebook.add(self.comparison_frame, text='Fruit Analysis')

        # Main container with fixed controls
        self.fixed_container = ttk.Frame(self.comparison_frame)
        self.fixed_container.pack(fill='x', expand=False)

        # Add period info frame at the top
        self.period_info_frame = ttk.Frame(self.fixed_container)
        self.period_info_frame.pack(fill='x', padx=10, pady=5)

        # Period info with tooltip
        info_frame = ttk.Frame(self.period_info_frame)
        info_frame.pack(side='left', padx=5)

        self.period_label = ttk.Label(info_frame, font=('TkDefaultFont', 10, 'bold'))
        self.period_label.pack(side='top', anchor='w')

        # Progress bar frame
        progress_frame = ttk.Frame(self.period_info_frame)
        progress_frame.pack(side='left', fill='x', expand=True, padx=5)

        self.progress_label = ttk.Label(progress_frame)
        self.progress_label.pack(side='top', anchor='w')

        # Progress bar
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate', length=200)
        self.progress_bar.pack(side='top', fill='x', pady=2)

        # Date selection frame
        date_frame = ttk.LabelFrame(self.fixed_container, text="Select Time Periods")
        date_frame.pack(fill='x', padx=10, pady=5)

        # Quick selection buttons
        quick_frame = ttk.Frame(date_frame)
        quick_frame.pack(fill='x', padx=5, pady=5)

        buttons = [
            ("Last Week", self.set_last_week),
            ("This Week", self.set_this_week),
            ("Current Month", self.set_current_month),
            ("Last 30 Days", self.set_last_30_days)
        ]

        for text, command in buttons:
            ttk.Button(quick_frame, text=text, command=command).pack(side='left', padx=5)

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

        # Setup scrollable area
        self.setup_scrollable_area()

        # Add tab selection binding
        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)

        # Create frames for fruit category buttons
        self.categories_frame = ttk.Frame(self.scrollable_frame)
        self.categories_frame.pack(fill='x', padx=5, pady=2)

        # Add category buttons
        for category in self.comparison_system.FRUIT_BRANDS:
            btn = ttk.Button(
                self.categories_frame,
                text=category,
                command=lambda c=category: self.show_brand_content(c)
            )
            btn.pack(side='left', padx=5, pady=2)

        # Content frame for selected category
        self.brand_content_frame = ttk.Frame(self.scrollable_frame)
        self.brand_content_frame.pack(fill='both', expand=True, padx=5, pady=5)

        # Set initial dates
        self.set_last_30_days()

    def setup_scrollable_area(self):
        """Setup scrollable canvas for content"""
        self.canvas_container = ttk.Frame(self.comparison_frame)
        self.canvas_container.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(self.canvas_container)
        self.scrollbar = ttk.Scrollbar(self.canvas_container, orient="vertical",
                                       command=self.canvas.yview)

        self.scrollable_frame = ttk.Frame(self.canvas)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame,
                                                       anchor="nw")

        self.scrollable_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

    def _on_frame_configure(self, event=None):
        """Reset the scroll region to encompass the inner frame"""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        """When canvas is resized, resize the inner frame to match"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def set_last_30_days(self):
        """Set dates for last 30 days comparison"""
        today = datetime.now().date()
        current_end = today - timedelta(days=1)  # Yesterday
        current_start = current_end - timedelta(days=29)  # 30 days ago

        prev_end = current_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=29)

        self.start_date1.set_date(prev_start)
        self.end_date1.set_date(prev_end)
        self.start_date2.set_date(current_start)
        self.end_date2.set_date(current_end)

    def set_last_week(self):
        """Set dates for last complete week"""
        today = datetime.now().date()
        current_end = today - timedelta(days=1)  # Yesterday
        current_start = current_end - timedelta(days=6)  # Last 7 days

        prev_end = current_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)

        self.start_date1.set_date(prev_start)
        self.end_date1.set_date(prev_end)
        self.start_date2.set_date(current_start)
        self.end_date2.set_date(current_end)

    def set_this_week(self):
        """Set dates for current week vs last week"""
        today = datetime.now().date()
        days_since_monday = today.weekday()

        current_start = today - timedelta(days=days_since_monday)  # This week's Monday
        current_end = today - timedelta(days=1)  # Yesterday

        prev_start = current_start - timedelta(days=7)  # Last week's Monday
        prev_end = current_start - timedelta(days=1)  # Last week's Sunday

        self.start_date1.set_date(prev_start)
        self.end_date1.set_date(prev_end)
        self.start_date2.set_date(current_start)
        self.end_date2.set_date(current_end)

    def set_current_month(self):
        """Set dates for current month vs last month"""
        today = datetime.now().date()
        current_start = today.replace(day=1)
        current_end = today - timedelta(days=1)

        if current_start.month == 1:
            prev_start = current_start.replace(year=current_start.year - 1, month=12)
        else:
            prev_start = current_start.replace(month=current_start.month - 1)

        prev_end = current_start - timedelta(days=1)

        self.start_date1.set_date(prev_start)
        self.end_date1.set_date(prev_end)
        self.start_date2.set_date(current_start)
        self.end_date2.set_date(current_end)

    def on_tab_changed(self, event):
        """Handle tab selection"""
        try:
            current = self.notebook.select()
            if self.notebook.index(current) == self.notebook.index(self.comparison_frame):
                self.logger.debug("Fruit Analysis tab selected")
                self.update_period_info()

        except Exception as e:
            self.logger.error(f"Error in tab changed handler: {str(e)}")
            messagebox.showerror("Error", f"Error loading comparison tab: {str(e)}")

    def update_period_info(self):
        """Update the period info display"""
        try:
            month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                           'July', 'August', 'September', 'October', 'November', 'December']

            today = datetime.now().date()
            current_month = today.month
            current_year = today.year

            self.period_label.config(
                text=f"Current Month: {month_names[current_month - 1]} {current_year}"
            )

            days_in_month = (today.replace(month=current_month % 12 + 1, day=1) - \
                             timedelta(days=1)).day
            days_elapsed = today.day
            progress = (days_elapsed / days_in_month) * 100

            self.progress_label.config(
                text=f"Progress: Day {days_elapsed} of {days_in_month} ({progress:.1f}%)"
            )

            self.progress_bar['value'] = progress

        except Exception as e:
            self.logger.error(f"Error updating period info: {str(e)}")
            self.period_label.config(text="Error loading period info")
            self.progress_label.config(text="")
            self.progress_bar['value'] = 0

    def compare_periods(self):
        """Perform comparison and update visualizations"""
        try:
            # Get dates from date pickers
            start1 = self.start_date1.get_date().strftime('%Y-%m-%d')
            end1 = self.end_date1.get_date().strftime('%Y-%m-%d')
            start2 = self.start_date2.get_date().strftime('%Y-%m-%d')
            end2 = self.end_date2.get_date().strftime('%Y-%m-%d')

            # Get comparison data
            df = self.comparison_system.get_brand_performance(start1, end1, start2, end2)

            # Store results for brand details views
            self.last_results = self.comparison_system.analyze_brand_performance(df)

            # Show performance summary
            self.show_performance_summary(df)

            # Clear any current brand selection
            self.current_brand = None

        except Exception as e:
            messagebox.showerror("Error", f"Error comparing periods: {str(e)}")

    def show_performance_summary(self, df):
        """Show performance summary for all fruit categories"""
        try:
            # Clear existing content
            for widget in self.brand_content_frame.winfo_children():
                widget.destroy()

            # Create category summary
            summary_frame = ttk.LabelFrame(self.brand_content_frame, text="Fruit Category Performance")
            summary_frame.pack(fill='x', padx=5, pady=5)

            # Calculate category totals
            category_totals = {}
            for category in self.comparison_system.FRUIT_BRANDS:
                category_data = df[df['brand'] == category]
                if not category_data.empty:
                    prev_total = category_data['prev_year'].sum()
                    curr_total = category_data['curr_year'].sum()
                    growth = ((curr_total - prev_total) / prev_total * 100) if prev_total > 0 else 100
                    category_totals[category] = {
                        'prev_total': prev_total,
                        'curr_total': curr_total,
                        'growth': growth,
                        'color': self.comparison_system.FRUIT_COLORS[category]
                    }

            # Create summary grid
            for i, (category, data) in enumerate(category_totals.items()):
                frame = ttk.Frame(summary_frame)
                frame.grid(row=i // 2, column=i % 2, padx=10, pady=5, sticky='ew')

                # Category header with colored indicator
                header_frame = ttk.Frame(frame)
                header_frame.pack(fill='x')

                indicator = tk.Canvas(header_frame, width=15, height=15)
                indicator.pack(side='left', padx=2)
                indicator.create_oval(2, 2, 13, 13, fill=data['color'])

                ttk.Label(header_frame,
                          text=f"{category}",
                          font=('TkDefaultFont', 10, 'bold')).pack(side='left')

                # Growth indicator
                growth = data['growth']
                arrow = "↑" if growth > 0 else "↓" if growth < 0 else "→"
                color = "green" if growth > 0 else "red" if growth < 0 else "black"

                ttk.Label(frame,
                          text=f"{arrow} {abs(growth):.1f}%",
                          foreground=color).pack()

                # Units information
                ttk.Label(frame,
                          text=f"Current: {int(data['curr_total'])} units\n"
                               f"Previous: {int(data['prev_total'])} units").pack()

            # Create visualization section
            viz_frame = ttk.LabelFrame(self.brand_content_frame, text="Performance Visualization")
            viz_frame.pack(fill='both', expand=True, padx=5, pady=5)

            # Create figure for visualization
            fig = Figure(figsize=(10, 5))
            ax = fig.add_subplot(111)

            # Plot data
            categories = list(category_totals.keys())
            curr_values = [category_totals[c]['curr_total'] for c in categories]
            prev_values = [category_totals[c]['prev_total'] for c in categories]
            colors = [category_totals[c]['color'] for c in categories]

            x = range(len(categories))
            width = 0.35

            ax.bar([i - width / 2 for i in x], prev_values, width,
                   label='Previous Period', color='lightgray')
            ax.bar([i + width / 2 for i in x], curr_values, width,
                   label='Current Period', color=colors)

            ax.set_ylabel('Units Sold')
            ax.set_title('Category Performance Comparison')
            ax.set_xticks(x)
            ax.set_xticklabels(categories)
            ax.legend()

            # Add value labels
            for i, v in enumerate(curr_values):
                growth = category_totals[categories[i]]['growth']
                ax.text(i + width / 2, v, f'{growth:+.1f}%',
                        ha='center', va='bottom')

            # Add chart to frame
            canvas = FigureCanvasTkAgg(fig, viz_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)

            # Update the frame
            self.brand_content_frame.update()

        except Exception as e:
            self.logger.error(f"Error in show_performance_summary: {str(e)}")
            messagebox.showerror("Error", f"Error showing performance summary: {str(e)}")

    def show_brand_content(self, brand):
        """Show detailed content for selected fruit category"""
        try:
            # Clear existing content
            for widget in self.brand_content_frame.winfo_children():
                widget.destroy()

            # Update current brand
            self.current_brand = brand

            if brand not in self.last_results:
                return

            data = self.last_results[brand]

            # Create header with category info
            header_frame = ttk.Frame(self.brand_content_frame)
            header_frame.pack(fill='x', padx=5, pady=5)

            ttk.Label(header_frame,
                      text=brand,
                      font=('TkDefaultFont', 14, 'bold')).pack(side='left')

            # Growth indicator
            growth = data['growth']
            color = "green" if growth > 0 else "red" if growth < 0 else "black"
            ttk.Label(header_frame,
                      text=f"{'↑' if growth > 0 else '↓' if growth < 0 else '→'} {abs(growth):.1f}%",
                      foreground=color,
                      font=('TkDefaultFont', 12)).pack(side='left', padx=10)

            # Create visualization frame
            viz_frame = ttk.Frame(self.brand_content_frame)
            viz_frame.pack(fill='both', expand=True, padx=5, pady=5)

            # Create bar chart for varieties
            fig = Figure(figsize=(12, 6))
            ax = fig.add_subplot(111)

            products = data['products'][:10]  # Top 10 varieties
            x = range(len(products))
            width = 0.35

            prev_bars = ax.bar([i - width / 2 for i in x],
                               [p['prev_year'] for p in products],
                               width,
                               label='Previous Period',
                               color='lightgray')

            curr_bars = ax.bar([i + width / 2 for i in x],
                               [p['curr_year'] for p in products],
                               width,
                               label='Current Period',
                               color=self.comparison_system.FRUIT_COLORS[brand])

            ax.set_ylabel('Units Sold')
            ax.set_title(f'{brand} Variety Performance')
            ax.set_xticks(x)
            ax.set_xticklabels([p['item'] for p in products], rotation=45, ha='right')
            ax.legend()

            # Add growth labels
            for i, product in enumerate(products):
                growth = product['growth']
                curr_value = product['curr_year']
                ax.text(i + width / 2, curr_value,
                        f'{growth:+.1f}%',
                        ha='center', va='bottom')

            fig.tight_layout()

            # Add chart to frame
            canvas = FigureCanvasTkAgg(fig, viz_frame)
            canvas.draw()
            canvas_widget = canvas.get_tk_widget()
            canvas_widget.pack(fill='both', expand=True)

        except Exception as e:
            self.logger.error(f"Error in show_brand_content: {str(e)}")
            messagebox.showerror("Error", f"Error showing brand content: {str(e)}")


class PromotionManager:
    def __init__(self):
        self._cache = {}
        self._last_cache_update = None
        self._cache_duration = timedelta(hours=1)  # Cache for 1 hour
        self.logger = get_logger('comparison_system')

    def _needs_cache_refresh(self):
        """Check if cache needs to be refreshed"""
        return (self._last_cache_update is None or
                datetime.now() - self._last_cache_update > self._cache_duration)

    def get_current_period_info(self):
        """Get current period information with caching"""
        try:
            cache_key = 'current_period'
            if cache_key not in self._cache or self._needs_cache_refresh():
                self.logger.debug("Fetching current period info from database")
                with db_config.get_cursor() as cursor:
                    cursor.execute("""
                        SELECT 
                            month,
                            description,
                            start_date,
                            end_date,
                            julianday('now') - julianday(start_date) + 1 as days_elapsed,
                            julianday(end_date) - julianday(start_date) + 1 as total_days
                        FROM promotion_periods
                        WHERE start_date <= date('now') 
                        AND end_date >= date('now')
                        ORDER BY year DESC, month DESC
                        LIMIT 1
                    """)

                    result = cursor.fetchone()
                    if not result:
                        raise ValueError("No active promotion period found for current date")

                    month, description, start_date, end_date, days_elapsed, total_days = result
                    progress_percent = (days_elapsed / total_days) * 100

                    self._cache[cache_key] = {
                        'month': month,
                        'description': description,
                        'start_date': datetime.strptime(start_date, '%Y-%m-%d').date(),
                        'end_date': datetime.strptime(end_date, '%Y-%m-%d').date(),
                        'days_elapsed': int(days_elapsed),
                        'total_days': int(total_days),
                        'progress_percent': round(progress_percent, 1)
                    }
                    self._last_cache_update = datetime.now()

            return self._cache[cache_key]

        except Exception as e:
            self.logger.error(f"Error getting current period info: {str(e)}")
            raise ValueError(f"Could not determine current promotion period: {str(e)}")

    def get_comparison_dates(self):
        """Get comparison dates for current period vs last year"""
        current_period = self.get_current_period_info()

        with db_config.get_cursor() as cursor:
            # Find matching period from last year
            cursor.execute("""
                SELECT start_date, end_date 
                FROM promotion_periods
                WHERE month = ? 
                AND year = strftime('%Y', 'now') - 1
                AND start_date IS NOT NULL
            """, (current_period['month'],))

            last_year = cursor.fetchone()
            if not last_year:
                raise ValueError(
                    f"No matching period found for last year (Month {current_period['month']})")

            last_start, last_end = last_year

            # Calculate days elapsed
            days_elapsed = current_period['days_elapsed']

            return {
                'current_start': current_period['start_date'],
                'current_end': min(current_period['start_date'] + timedelta(days=days_elapsed - 1),
                                   datetime.now().date() - timedelta(days=1)),
                'previous_start': datetime.strptime(last_start, '%Y-%m-%d').date(),
                'previous_end': datetime.strptime(last_start, '%Y-%m-%d').date() + timedelta(days=days_elapsed - 1)
            }