# 🎯 Sales Targeting and Analysis System

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-production-green)

A powerful, data-driven sales targeting and analysis system designed to supercharge your sales team's effectiveness. This application combines intelligent customer targeting, comprehensive sales analysis, and automated promotion period tracking to help you make informed decisions and boost your sales performance.

## ✨ Features

### 🎯 Smart Customer Targeting
- **Hot Potato Analysis**: Identify your most engaged customers for specific products
- **Cross-Sell Detection**: Find opportunities to upgrade customers to premium products
- **Intelligent Filtering**: Filter out recently contacted customers to avoid oversaturation
- **Export Ready**: Generate targeted customer lists with full contact information

### 📊 Sales Performance Analysis
- **Brand Performance Dashboard**: Real-time visualization of brand performance metrics
- **Growth Tracking**: Automated calculation of year-over-year and period-over-period growth
- **Top/Bottom Analysis**: Instant identification of best and worst performing products
- **Visual Insights**: Interactive charts and graphs for better decision making

### 📅 Promotion Period Management
- **Period Tracking**: Set up and manage promotional periods
- **Automated Comparisons**: Compare current promotion performance against historical data
- **Flexible Setup**: Support for multiple promotion periods with custom date ranges

### 📞 Call Tracking System
- **Customer History**: Track all customer interactions
- **Status Tracking**: Monitor call outcomes and follow-ups
- **Quick Access**: Instant access to customer purchase history and preferences
- **Export Capabilities**: Generate call history reports for analysis

## 🚀 Getting Started

### Prerequisites
```bash
pip install pyyaml pandas matplotlib tkinter pillow
```

### Installation
1. Clone the repository
```bash
git clone https://github.com/yourusername/sales-targeting-system.git
cd sales-targeting-system
```

2. Install required dependencies
```bash
pip install -r requirements.txt
```

3. Run the application
```bash
python sales_target-inator.py
```

## 📖 Usage

### Data Import
1. Export your sales data from Point of Sale system
2. Use the Import Data tab to load:
   - Sales history
   - Customer information
   - Promotion periods

### Finding Potential Customers
1. Select target brand or product
2. Set inactivity period
3. Click "Find Potential Customers"
4. Export results or transfer to call tracking

### Analyzing Sales Performance
1. Select comparison period
2. View brand performance dashboard
3. Drill down into specific brands for detailed analysis
4. Track promotion period performance

## 🎨 Features in Detail

### Brand Analysis Dashboard
- Overall brand performance metrics
- Top and bottom performing products
- Growth indicators and trends
- Period-over-period comparisons

### Customer Targeting Logic
- Intelligent analysis of purchase patterns
- Premium product affinity detection
- Purchase frequency analysis
- Cross-sell opportunity identification

### Call Tracking Integration
- Seamless transfer from targeting to call tracking
- Complete customer purchase history
- Contact information management
- Call outcome tracking and analysis

## 🛠 Configuration

### Logging Levels
Adjust logging configuration in `logging_config.yml`:
```yaml
loggers:
  sales_targeting:
    level: INFO  # Set to DEBUG for detailed logs
  comparison_system:
    level: INFO  # Set to DEBUG for detailed logs
```

### Database Configuration
- SQLite database for portability
- Automatic database creation and schema management
- Built-in data validation and error handling

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License

This project is licensed under the MIT License - see the LICENSE.md file for details.

## 🙏 Acknowledgments

- Built with Python and Tkinter
- Uses Matplotlib for visualization
- SQLite for data storage
- Special thanks to all contributors

---

Made with ❤️ for sales teams who want to work smarter, not harder.