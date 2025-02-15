[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/stratum01)
really, i like it a lot.

# Sales Targeting System

A Python-based application for managing customer relationships, analyzing sales data, and tracking promotional performance for wine retailers.

## Features

- **Customer Targeting**
  - Find potential customers based on purchase history
  - Cross-sell targeting from entry-level to premium wines
  - Hot Potato analysis for top product buyers
  - Advanced filtering by inactivity and contact history

- **Call Tracking**
  - Record customer interactions
  - Track call outcomes
  - View customer purchase history
  - Export call histories

- **Sales Analysis**
  - Compare performance between time periods
  - Track brand performance
  - Analyze promotional period results
  - View top/bottom performing products

## Prerequisites

- Python 3.8 or higher
- PostgreSQL database access
- Network access to corkscrew.mywinesense.com

## Installation

1. Clone the repository
```bash
git clone [repository-url]
cd sales-targeting-system
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
4. Create .env file in project root with database credentials:
```bash
DB_NAME=sales_targeting
DB_USER=sales_app
DB_PASSWORD=your_password
DB_HOST=corkscrew.mywinesense.com
DB_PORT=5432
```

5. Running the Application
```bash
python sales_target-inator.py
```

## Data Import Process
For initial setup, data needs to be imported in this order:

- Customer data 
- Sales history
- Promotion periods (optional)

Refer to the Import Data tab in the application for detailed instructions.
## File Structure

```bash
sales-targeting-system/
├── sales_target-inator.py   # Main application
├── comparison_system.py     # Sales comparison logic
├── db_config.py            # Database configuration
├── logging_config.py       # Logging setup
├── requirements.txt        # Package dependencies
└── .env                    # Database credentials (not in git)
```

## Database Tables

- customers - Customer contact information
- sales_history - Transaction records
- call_tracking - Call interaction records
- promotion_periods - Promotional period definitions

## Common Issues

### Database Connection

- Verify .env file exists with correct credentials
- Check network connectivity to database server
- Ensure database port (5432) is accessible


### Data Import

- Customer data must be imported before sales history
- CSV files should match expected format
- Check CSV for special characters or formatting issues

## Development

Code repository is maintained in version control
Use Python's built-in venv for dependency management
Follow existing code style and documentation patterns
Test changes in development environment before deploying

## License
Internal company use only. All rights reserved.

Last updated: February 2024