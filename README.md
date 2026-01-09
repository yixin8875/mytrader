# MyTrader 交易管理系统

一个基于 Django 的量化交易管理系统，支持交易记录管理、策略回测、股票数据下载和自动化任务。

## 功能特性

### 交易管理
- 多账户管理（股票、期货、外汇、加密货币）
- 交易记录与复盘
- 持仓管理
- 盈亏分析与报表

### 量化交易
- 股票数据下载（支持 A 股，使用 AkShare）
- 策略回测（基于 Backtrader）
- A 股特性模拟：T+1、佣金、印花税、涨跌停
- 权益曲线与交易明细记录
- K线图表与多股票对比

### 数据分析
- 仪表盘数据概览
- 日报/月报自动生成
- 深度分析图表
- 交易标签分析、持仓时间分析、回撤分析、相关性分析

### 风险管理
- 仓位计算器
- 风险预警仪表盘
- 止损止盈提醒
- 风险敞口分析

### 数据管理
- 一键备份/恢复数据库
- 多数据源支持（AkShare、Tushare、BaoStock）
- 数据质量检查（缺失数据、异常价格检测）

### 自动化扩展
- 策略信号推送
- 定时报告邮件（每日/每周/每月）
- Webhook 集成（接收外部交易信号）
- Celery 异步任务

### 用户体验
- PWA 支持（可安装到手机桌面）
- 深色模式（浅色/深色/跟随系统）
- 键盘快捷键（T 切换主题、? 显示帮助）
- 自定义仪表盘（拖拽排序、模块开关）

## 技术栈

- **后端**: Django 5.2, Celery
- **数据库**: SQLite (开发) / PostgreSQL (生产)
- **消息队列**: Redis
- **数据源**: AkShare
- **回测引擎**: Backtrader
- **前端**: TailwindCSS, Chart.js, ECharts

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 克隆项目
git clone <repository-url>
cd mytrader

# 启动所有服务
docker-compose up -d --build

# 创建超级用户
docker-compose exec web python manage.py createsuperuser

# 访问
# Web: http://localhost:8000
# Admin: http://localhost:8000/admin/
```

### 方式二：本地开发

#### 1. 环境准备

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安装依赖（推荐使用 uv）
uv pip install -r requirements.txt
# 或使用 pip
pip install -r requirements.txt
```

#### 2. 启动 Redis

```bash
# macOS
brew install redis
redis-server

# Ubuntu
sudo apt install redis-server
sudo systemctl start redis
```

#### 3. 初始化数据库

```bash
python manage.py migrate
python manage.py createsuperuser
```

#### 4. 启动服务

```bash
# 终端 1: Django 开发服务器
python manage.py runserver

# 终端 2: Celery Worker
celery -A mytrader worker -l info

# 终端 3: Celery Beat (可选，定时任务)
celery -A mytrader beat -l info
```

#### 5. 访问系统

- 首页: http://127.0.0.1:8000/
- 管理后台: http://127.0.0.1:8000/admin/
- 股票数据管理: http://127.0.0.1:8000/quant/data/
- 用户设置: http://127.0.0.1:8000/settings/
- 风控中心: http://127.0.0.1:8000/risk/
- 数据管理: http://127.0.0.1:8000/data-management/

## 使用指南

### 下载股票数据

**Web 界面（推荐）**

1. 访问 http://127.0.0.1:8000/quant/data/
2. 输入股票代码（如 `000001 600519 300750`）
3. 选择日期范围
4. 点击"开始下载"

**命令行**

```bash
python manage.py fetch_stock_data --symbols 000001 600519 --start 20240101 --end 20241231
```

### 创建策略

1. 访问 Admin 后台
2. 进入 Quant → 量化策略
3. 添加策略，配置参数

### 执行回测

1. 访问 `/quant/strategy/<策略ID>/backtest/`
2. 选择股票、日期范围、初始资金
3. 点击"开始回测"
4. 查看回测结果和收益曲线

### 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `T` | 切换深色/浅色主题 |
| `B` | 切换侧边栏 |
| `G H` | 返回首页 |
| `G R` | 风控中心 |
| `G A` | 数据分析 |
| `G S` | 设置页面 |
| `?` | 显示快捷键帮助 |

## 项目结构

```
mytrader/
├── mytrader/           # 项目配置
│   ├── settings.py
│   ├── celery.py
│   └── urls.py
├── trading/            # 交易管理模块
│   ├── models.py       # 账户、交易、持仓、Webhook、用户偏好模型
│   ├── views.py        # API 端点和页面视图
│   ├── admin.py        # Admin 配置
│   ├── analytics.py    # 交易分析计算
│   ├── notifications.py # 通知服务
│   └── static/trading/ # 静态资源（PWA、CSS、JS）
├── quant/              # 量化交易模块
│   ├── models.py       # 股票数据、策略、回测结果
│   ├── views.py        # 数据管理、回测视图
│   ├── tasks.py        # Celery 任务
│   ├── data_fetcher.py # 数据下载服务
│   └── backtest_service.py  # 回测服务
├── templates/          # HTML 模板
│   └── trading/
│       ├── home.html           # 主仪表盘
│       ├── settings.html       # 用户设置
│       ├── risk_dashboard.html # 风控中心
│       ├── data_management.html # 数据管理
│       └── automation_extended.html # 自动化扩展
├── docs/               # 文档
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## API 端点

### 用户偏好
- `GET /api/preference/` - 获取用户偏好
- `POST /api/preference/update/` - 更新偏好设置

### 数据管理
- `POST /api/data/backup/` - 创建数据库备份
- `POST /api/data/restore/` - 恢复数据库
- `GET /api/data/quality-check/` - 数据质量检查

### 自动化
- `GET/POST /api/signals/` - 策略信号管理
- `GET/POST /api/webhooks/` - Webhook 配置
- `POST /api/webhook/<secret_key>/` - 外部 Webhook 接收

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| SECRET_KEY | Django 密钥 | 开发密钥 |
| DEBUG | 调试模式 | 1 |
| ALLOWED_HOSTS | 允许的主机 | localhost,127.0.0.1 |
| CELERY_BROKER_URL | Redis 地址 | redis://localhost:6379/0 |

## Docker 命令

```bash
# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止
docker-compose down

# 重建
docker-compose up -d --build

# 进入容器
docker-compose exec web bash
```

## 文档

- [量化模块使用指南](docs/量化模块使用指南.md)
- [CLAUDE.md](CLAUDE.md) - 开发指南

## License

MIT License
