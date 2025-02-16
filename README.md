a[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/stratum01)
really, i like it a lot.

# Fruit Stand Sales Targeting System

A Python-based desktop application for managing customer relationships and analyzing sales data for a fruit stand business. This application helps fruit vendors track customer purchases, analyze sales patterns, and identify potential sales opportunities.

## Features

### Sales Analysis
- Compare performance between time periods
- Track sales by fruit category (Apples, Grapes, Oranges)
- Analyze seasonal trends
- Visualize performance metrics with interactive charts

### Customer Targeting
- Find potential customers based on purchase history
- "Big Banana" analysis for top product buyers
- Cross-sell recommendations between fruit categories
- Advanced filtering by inactivity and contact history

### Call Tracking
- Record customer interactions
- Track call outcomes
- View customer purchase history
- Export call histories

## Technology Stack
- Python 3.8+
- SQLite database
- Tkinter for GUI
- Pandas for data analysis
- Matplotlib for visualizations

## Installation

1. Clone the repository
```bash
git clone https://github.com/yourusername/fruit-stand-targeting.git
cd fruit-stand-targeting
```

2. Create and activate virtual environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux/Mac
python -m venv venv
source venv/bin/activate
```

3. Install required packages
```bash
pip install -r requirements.txt
```

4. Run the application
```bash
python sales_target-inator.py
```

## Data Import Format

### Customer Data (CSV)
| Column | Description |
|--------|-------------|
| Customer ID | Unique identifier |
| First Name | Customer's first name |
| Last Name | Customer's last name |
| Email | Contact email |
| Phone | Contact phone number |
| Address | Street address |
| City | City name |
| State | State code |
| Postal Code | ZIP/Postal code |

### Sales Data (CSV)
| Column | Description |
|--------|-------------|
| Invoice ID | Unique sale identifier |
| Customer ID | Customer reference |
| Category | Fruit category (Apples/Grapes/Oranges) |
| Variety | Specific fruit variety |
| Units | Number of units sold |
| Date | Sale date (YYYY-MM-DD) |

## Usage

1. Import customer and sales data using the Import Data tab
2. Use the Fruit Analysis tab to view sales performance
3. Find potential customers in the Find Customers tab
4. Track customer calls and follow-ups in the Call Tracking tab

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License
[MIT](https://choosealicense.com/licenses/mit/)

## Screenshots
