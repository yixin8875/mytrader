# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MyTrader is a Django-based trading management system for tracking trades, accounts, strategies, and performance analysis. The system uses Django 5.2 with a Chinese-language interface enhanced by django-jazzmin for a modern admin UI.

### Key Features
- 交易记录管理 - 完整的交易日志、持仓、账户管理
- 量化回测 - 策略回测和绩效分析
- 风险管理 - 仓位计算器、风险预警、止损止盈提醒
- 数据管理 - 一键备份/恢复、数据质量检查
- 自动化扩展 - 策略信号推送、定时报告、Webhook集成
- 用户体验 - PWA支持、深色模式、键盘快捷键、自定义仪表盘

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

### Automation Models

8. **Webhook** - 外部信号接收配置
   - 支持 inbound（接收）和 outbound（发送）类型
   - 自动生成安全密钥 `secret_key`
   - 关联 WebhookLog 记录调用日志

9. **ScheduledReport** - 定时报告配置
   - 支持每日/每周/每月频率
   - 报告类型：交易总结、绩效报告、风险报告

10. **StrategySignal** - 策略信号记录
    - 信号类型：买入/卖出/持有
    - 来源：回测/实盘/Webhook

11. **UserPreference** - 用户偏好设置
    - 主题模式（浅色/深色/跟随系统）
    - 仪表盘布局配置
    - 快捷键启用状态

### Key Relationships
- TradeLog and Position reference Symbol with `on_delete=PROTECT` (cannot delete symbols in use)
- All financial fields use DecimalField for precision
- Timestamps use China timezone (Asia/Shanghai)

### Admin Configuration (trading/admin.py)

- Uses django-jazzmin for UI customization
- Inline admin for TradeImage within TradeLog
- Dynamic fieldsets in TradeLogAdmin (shows total_amount only on edit, not create)
- Custom colored display methods for profit/loss (green/red)

### Static Assets (trading/static/trading/)

- `js/trade_log_admin.js` - Handles paste (Ctrl+V) and drag-drop image uploads
- `css/trade_log_admin.css` - Styles for upload interface
- `manifest.json` - PWA 配置文件
- `sw.js` - Service Worker 离线缓存
- `icons/` - PWA 应用图标

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
├── mytrader/              # Project settings
│   ├── settings.py        # Contains JAZZMIN_SETTINGS
│   └── urls.py            # URL routing
├── trading/               # Main trading app
│   ├── models.py          # All domain models
│   ├── views.py           # API endpoints and page views
│   ├── admin.py           # Admin configurations
│   ├── analytics.py       # Trade analytics calculations
│   ├── notifications.py   # Notification service
│   ├── static/trading/    # Static assets (CSS/JS/PWA)
│   │   ├── manifest.json  # PWA manifest
│   │   ├── sw.js          # Service Worker
│   │   └── icons/         # App icons
│   └── migrations/        # Database migrations
├── quant/                 # Quantitative trading app
│   ├── models.py          # Stock data, strategies, backtest results
│   └── views.py           # Quant-related views
├── templates/trading/     # HTML templates
│   ├── home.html          # Main dashboard
│   ├── settings.html      # User settings page
│   ├── risk_dashboard.html
│   ├── data_management.html
│   └── automation_extended.html
└── manage.py
```

## API Endpoints

### 用户偏好设置
- `GET /api/preference/` - 获取用户偏好
- `POST /api/preference/update/` - 更新偏好设置
- `POST /api/preference/dashboard/` - 更新仪表盘布局

### 数据管理
- `POST /api/data/backup/` - 创建数据库备份
- `POST /api/data/restore/` - 恢复数据库
- `GET /api/data/backups/` - 列出备份文件
- `GET /api/data/quality-check/` - 数据质量检查

### 自动化扩展
- `GET/POST /api/signals/` - 策略信号管理
- `GET/POST /api/webhooks/` - Webhook配置
- `POST /api/webhook/<secret_key>/` - 外部Webhook接收（无需登录）
- `GET/POST /api/reports/` - 定时报告管理

## User Experience Features

### PWA Support
- 支持"添加到主屏幕"
- Service Worker 离线缓存
- Push 通知支持

### Dark Mode
- 三种模式：浅色、深色、跟随系统
- 偏好保存到 localStorage 和数据库
- 顶部导航栏快速切换

### Keyboard Shortcuts
- `T` - 切换主题
- `B` - 切换侧边栏
- `G H` - 返回首页
- `G R` - 风控中心
- `G A` - 数据分析
- `G S` - 设置页面
- `?` - 显示快捷键帮助

### Custom Dashboard
- 拖拽排序仪表盘模块
- 启用/禁用各个模块
- 设置页面可视化配置

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

### CSRF Exempt for External APIs
For webhook endpoints that receive external requests:
```python
from django.views.decorators.csrf import csrf_exempt

@require_http_methods(['POST'])
@csrf_exempt
def api_webhook_receive(request, secret_key):
    # Handle external webhook
    pass
```
