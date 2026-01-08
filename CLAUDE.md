# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MyTrader is a Django-based trading management system for tracking trades, accounts, strategies, and performance analysis. The system uses Django 5.2 with a Chinese-language interface enhanced by django-jazzmin for a modern admin UI.

## Development Commands

### Environment Setup
This project uses `uv` as the package manager (not pip).

```bash
# Install dependencies
uv pip install <package_name>

# Install all required packages for development
uv pip install django django-jazzmin Pillow
```

### Running the Server
Always use the virtual environment's Python executable:

```bash
# Start development server
.venv/bin/python manage.py runserver

# Or run in background
.venv/bin/python manage.py runserver &
```

### Database Operations
```bash
# Create migrations after model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Create superuser for admin access
python manage.py createsuperuser
```

## Architecture

### Core Domain Models (trading/models.py)

The system is built around these core entities with specific relationships:

1. **Account** - Trading accounts (stock, futures, forex, crypto, options)
   - Tracks balance, profit/loss
   - Owned by Django User

2. **Symbol** - Trading instruments with contract specifications
   - Critical for automatic calculations
   - Contains: contract_size (multiplier), commission settings, margin rates
   - Methods: `calculate_profit_loss()`, `calculate_commission()`
   - MUST be configured before creating TradeLog entries

3. **Strategy** - Trading strategy definitions
   - Simple metadata model (name, description, status)
   - Not linked to accounts (strategies are independent concepts)

4. **TradeLog** - Individual trade records
   - Links: Account → Symbol (FK, PROTECT), Strategy (optional)
   - Includes: quantity, price, executed_price, commission, slippage
   - Property: `total_amount` (quantity × price, handles None values)

5. **TradeImage** - Trade screenshots (inline to TradeLog)
   - Supports multiple images per trade
   - Upload path: `trade_images/%Y/%m/%d/`

6. **Position** - Current holdings
   - Links: Account → Symbol (FK, PROTECT)
   - Unique constraint on (account, symbol)

7. **Performance Models**
   - DailyReport, MonthlyReport - Pre-calculated aggregations
   - PerformanceMetrics - Per-strategy analytics (sharpe, sortino, calmar ratios)

### Key Relationships
- TradeLog and Position reference Symbol with `on_delete=PROTECT` (cannot delete symbols in use)
- All financial fields use DecimalField for precision
- Timestamps use China timezone (Asia/Shanghai)

### Admin Configuration (trading/admin.py)

- Uses django-jazzmin for UI customization
- Inline admin for TradeImage within TradeLog
- Dynamic fieldsets in TradeLogAdmin (shows total_amount only on edit, not create)
- Custom colored display methods for profit/loss (green/red)

### Static Assets for TradeLog Upload (trading/static/)

Custom JavaScript and CSS for image upload functionality:
- `trading/js/trade_log_admin.js` - Handles paste (Ctrl+V) and drag-drop image uploads
- `trading/css/trade_log_admin.css` - Styles for upload interface

## Important Constraints

### Decimal Formatting in Admin
When using `format_html()` with decimals, format the string BEFORE passing to format_html:

```python
# ❌ WRONG - will cause ValueError
format_html('<span>{:.2f}</span>', value)

# ✅ CORRECT
format_html('<span>{}</span>', f'{value:.2f}')
```

### Property Methods
Several models use `@property` decorators for calculated values:
- Account.total_profit_loss, Account.profit_loss_ratio
- TradeLog.total_amount (must handle None values)
- Symbol.contract_value

Always check if values are None before calculations in properties.

### Symbol Configuration Prerequisite
TradeLog entries require Symbol to be configured first with proper:
- contract_size for futures/index calculations
- commission_rate and/or commission_per_contract for fee calculations
- symbol_type to determine calculation method

## Settings Configuration

### Internationalization
- LANGUAGE_CODE = 'zh-hans' (Simplified Chinese)
- TIME_ZONE = 'Asia/Shanghai'

### Jazzmin Configuration
Located in mytrader/settings.py JAZZMIN_SETTINGS:
- Theme: 'forest' (18 themes available via theme_selector)
- Custom navigation with Chinese labels
- FontAwesome icons for all models
- Language chooser disabled (set to False)

### Static Files
- STATIC_URL = 'static/'
- Custom static files in trading/static/trading/

## Project Structure

```
mytrader/
├── mytrader/          # Project settings
│   └── settings.py    # Contains JAZZMIN_SETTINGS
├── trading/           # Main trading app
│   ├── models.py      # All domain models
│   ├── admin.py       # Admin configurations + inline classes
│   ├── static/        # Custom CSS/JS for image upload
│   └── migrations/    # Database migrations
└── manage.py
```

## Common Patterns

### Adding Calculated Fields to Admin
```python
# In admin.py
def calculated_field(self, obj):
    value = obj.calculate_something()
    color = 'green' if value >= 0 else 'red'
    return format_html('<span style="color: {};">{}</span>', color, f'{value:.2f}')
calculated_field.short_description = '显示名称'
```

### Inline Model Relationships
For one-to-many relationships shown on parent admin page (like TradeImage → TradeLog):
1. Create TabularInline class
2. Add to parent Admin's inlines list
3. Use readonly_fields for computed display fields
