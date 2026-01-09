"""
数据导入导出模块
提供交易数据的导入和导出功能
"""
import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.utils import timezone
from django.db import transaction


class DataExporter:
    """数据导出服务类"""

    def __init__(self, user):
        self.user = user
        # 延迟导入避免循环引用
        from .models import TradeLog, Account, Position, Symbol, Strategy

        self.TradeLog = TradeLog
        self.Account = Account
        self.Position = Position
        self.Symbol = Symbol
        self.Strategy = Strategy

    def export_trades_csv(self, account=None, start_date=None, end_date=None):
        """
        导出交易记录为CSV格式
        Returns:
            StringIO对象，包含CSV数据
        """
        qs = self.TradeLog.objects.filter(
            account__owner=self.user
        ).select_related('account', 'symbol', 'strategy')

        if account:
            qs = qs.filter(account=account)
        if start_date:
            qs = qs.filter(trade_time__date__gte=start_date)
        if end_date:
            qs = qs.filter(trade_time__date__lte=end_date)

        qs = qs.order_by('trade_time')

        output = io.StringIO()
        writer = csv.writer(output)

        # 写入表头
        headers = [
            '交易时间', '账户', '标的代码', '标的名称', '方向', '数量',
            '委托价', '成交价', '手续费', '滑点', '盈亏', '状态',
            '订单ID', '策略', '备注'
        ]
        writer.writerow(headers)

        # 写入数据
        for trade in qs:
            row = [
                trade.trade_time.strftime('%Y-%m-%d %H:%M:%S'),
                trade.account.name,
                trade.symbol.code,
                trade.symbol.name,
                trade.get_side_display(),
                str(trade.quantity),
                str(trade.price),
                str(trade.executed_price) if trade.executed_price else '',
                str(trade.commission),
                str(trade.slippage),
                str(trade.profit_loss),
                trade.get_status_display(),
                trade.order_id,
                trade.strategy.name if trade.strategy else '',
                trade.notes,
            ]
            writer.writerow(row)

        output.seek(0)
        return output

    def export_accounts_csv(self):
        """导出账户数据为CSV格式"""
        qs = self.Account.objects.filter(owner=self.user)

        output = io.StringIO()
        writer = csv.writer(output)

        headers = [
            '账户名称', '账户类型', '券商', '账户ID', '初始资金',
            '当前余额', '可用余额', '总盈亏', '盈亏比例', '状态', '创建时间', '备注'
        ]
        writer.writerow(headers)

        for account in qs:
            row = [
                account.name,
                account.get_account_type_display(),
                account.broker,
                account.account_id,
                str(account.initial_balance),
                str(account.current_balance),
                str(account.available_balance),
                str(account.total_profit_loss),
                f'{account.profit_loss_ratio:.2f}%',
                account.get_status_display(),
                account.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                account.notes,
            ]
            writer.writerow(row)

        output.seek(0)
        return output

    def export_positions_csv(self, account=None):
        """导出持仓数据为CSV格式"""
        qs = self.Position.objects.filter(
            account__owner=self.user
        ).select_related('account', 'symbol')

        if account:
            qs = qs.filter(account=account)

        output = io.StringIO()
        writer = csv.writer(output)

        headers = [
            '账户', '标的代码', '标的名称', '持仓数量', '平均成本',
            '当前价格', '市值', '盈亏', '盈亏比例', '更新时间'
        ]
        writer.writerow(headers)

        for pos in qs:
            row = [
                pos.account.name,
                pos.symbol.code,
                pos.symbol.name,
                str(pos.quantity),
                str(pos.avg_price),
                str(pos.current_price) if pos.current_price else '',
                str(pos.market_value),
                str(pos.profit_loss),
                f'{pos.profit_loss_ratio:.2f}%',
                pos.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            ]
            writer.writerow(row)

        output.seek(0)
        return output

    def export_symbols_csv(self):
        """导出交易标的为CSV格式"""
        qs = self.Symbol.objects.all()

        output = io.StringIO()
        writer = csv.writer(output)

        headers = [
            '标的代码', '标的名称', '类型', '交易所', '计价货币',
            '合约乘数', '最小变动', '保证金率', '手续费率', '每手手续费',
            '是否活跃', '描述'
        ]
        writer.writerow(headers)

        for symbol in qs:
            row = [
                symbol.code,
                symbol.name,
                symbol.get_symbol_type_display(),
                symbol.exchange,
                symbol.currency,
                str(symbol.contract_size),
                str(symbol.minimum_tick),
                str(symbol.margin_rate) if symbol.margin_rate else '',
                str(symbol.commission_rate) if symbol.commission_rate else '',
                str(symbol.commission_per_contract),
                '是' if symbol.is_active else '否',
                symbol.description,
            ]
            writer.writerow(row)

        output.seek(0)
        return output

    def export_analysis_csv(self, account=None, start_date=None, end_date=None):
        """导出分析报告为CSV格式"""
        from .analytics import TradeAnalytics

        analyzer = TradeAnalytics(
            user=self.user,
            account=account,
            start_date=start_date,
            end_date=end_date
        )

        report = analyzer.get_full_report()
        output = io.StringIO()
        writer = csv.writer(output)

        # 摘要部分
        writer.writerow(['=== 交易分析报告 ==='])
        writer.writerow(['生成时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        writer.writerow([])

        # 基础统计
        writer.writerow(['=== 基础统计 ==='])
        if report.get('summary') and report['summary'].get('basic'):
            basic = report['summary']['basic']
            writer.writerow(['总交易次数', basic.get('total_trades', 0)])
            writer.writerow(['盈利次数', basic.get('win_trades', 0)])
            writer.writerow(['亏损次数', basic.get('loss_trades', 0)])
            writer.writerow(['胜率', f"{basic.get('win_rate', 0)}%"])
            writer.writerow(['总盈亏', basic.get('total_pnl', 0)])
            writer.writerow(['净盈亏', basic.get('net_pnl', 0)])
            writer.writerow(['单笔最大盈利', basic.get('max_profit', 0)])
            writer.writerow(['单笔最大亏损', basic.get('max_loss', 0)])

        writer.writerow([])

        # 盈亏比率
        writer.writerow(['=== 盈亏比率 ==='])
        if report.get('summary') and report['summary'].get('ratios'):
            ratios = report['summary']['ratios']
            writer.writerow(['平均盈利', ratios.get('avg_win', 0)])
            writer.writerow(['平均亏损', ratios.get('avg_loss', 0)])
            writer.writerow(['盈亏比', ratios.get('profit_factor', 0)])
            writer.writerow(['期望值', ratios.get('expectancy', 0)])

        writer.writerow([])

        # 按品种统计
        writer.writerow(['=== 品种统计 ==='])
        writer.writerow(['代码', '名称', '交易数', '胜率', '总盈亏', '净盈亏'])
        for item in report.get('by_symbol', []):
            writer.writerow([
                item.get('symbol_code', ''),
                item.get('symbol_name', ''),
                item.get('total_trades', 0),
                f"{item.get('win_rate', 0)}%",
                item.get('total_pnl', 0),
                item.get('net_pnl', 0),
            ])

        writer.writerow([])

        # 按月统计
        writer.writerow(['=== 月度统计 ==='])
        writer.writerow(['月份', '交易数', '胜率', '总盈亏', '净盈亏'])
        for item in report.get('by_month', []):
            writer.writerow([
                item.get('month', ''),
                item.get('total_trades', 0),
                f"{item.get('win_rate', 0)}%",
                item.get('total_pnl', 0),
                item.get('net_pnl', 0),
            ])

        writer.writerow([])

        # 按策略统计
        writer.writerow(['=== 策略统计 ==='])
        writer.writerow(['策略', '交易数', '胜率', '盈亏比', '总盈亏'])
        for item in report.get('by_strategy', []):
            writer.writerow([
                item.get('strategy_name', ''),
                item.get('total_trades', 0),
                f"{item.get('win_rate', 0)}%",
                item.get('profit_factor', 0),
                item.get('total_pnl', 0),
            ])

        output.seek(0)
        return output


class DataImporter:
    """数据导入服务类"""

    def __init__(self, user):
        self.user = user
        self.errors = []
        self.success_count = 0
        self.skip_count = 0

        # 延迟导入
        from .models import TradeLog, Account, Symbol, Strategy
        self.TradeLog = TradeLog
        self.Account = Account
        self.Symbol = Symbol
        self.Strategy = Strategy

    def parse_csv(self, file_content):
        """解析CSV文件内容"""
        if isinstance(file_content, bytes):
            # 尝试不同编码
            for encoding in ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']:
                try:
                    content = file_content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError('无法解析文件编码，请使用UTF-8编码')
        else:
            content = file_content

        reader = csv.DictReader(io.StringIO(content))
        return list(reader)

    def import_trades(self, file_content, account_id, default_strategy_id=None):
        """
        导入交易记录
        CSV格式要求列：交易时间, 标的代码, 方向, 数量, 价格, 成交价, 手续费, 盈亏, 订单ID, 备注
        """
        self.errors = []
        self.success_count = 0
        self.skip_count = 0

        try:
            rows = self.parse_csv(file_content)
        except Exception as e:
            self.errors.append(f'CSV解析错误: {str(e)}')
            return False

        # 验证账户
        try:
            account = self.Account.objects.get(id=account_id, owner=self.user)
        except self.Account.DoesNotExist:
            self.errors.append('账户不存在或无权限')
            return False

        # 获取默认策略
        strategy = None
        if default_strategy_id:
            try:
                strategy = self.Strategy.objects.get(id=default_strategy_id, owner=self.user)
            except self.Strategy.DoesNotExist:
                pass

        # 预加载标的映射
        symbols = {s.code: s for s in self.Symbol.objects.all()}

        # 列名映射
        column_map = {
            '交易时间': 'trade_time',
            '标的代码': 'symbol_code',
            '方向': 'side',
            '数量': 'quantity',
            '价格': 'price',
            '委托价': 'price',
            '成交价': 'executed_price',
            '手续费': 'commission',
            '盈亏': 'profit_loss',
            '订单ID': 'order_id',
            '备注': 'notes',
            '滑点': 'slippage',
        }

        # 方向映射
        side_map = {
            '买入': 'buy', '买': 'buy', 'buy': 'buy', 'B': 'buy', 'b': 'buy',
            '卖出': 'sell', '卖': 'sell', 'sell': 'sell', 'S': 'sell', 's': 'sell',
        }

        with transaction.atomic():
            for i, row in enumerate(rows, start=2):  # 从第2行开始（第1行是表头）
                try:
                    # 标准化列名
                    data = {}
                    for key, value in row.items():
                        if key in column_map:
                            data[column_map[key]] = value.strip() if value else ''
                        else:
                            # 尝试去掉空格匹配
                            clean_key = key.strip()
                            if clean_key in column_map:
                                data[column_map[clean_key]] = value.strip() if value else ''

                    # 验证必填字段
                    if not data.get('symbol_code'):
                        self.errors.append(f'第{i}行: 缺少标的代码')
                        continue

                    if not data.get('side'):
                        self.errors.append(f'第{i}行: 缺少交易方向')
                        continue

                    if not data.get('quantity'):
                        self.errors.append(f'第{i}行: 缺少数量')
                        continue

                    if not data.get('price'):
                        self.errors.append(f'第{i}行: 缺少价格')
                        continue

                    # 查找标的
                    symbol = symbols.get(data['symbol_code'])
                    if not symbol:
                        self.errors.append(f"第{i}行: 标的代码 '{data['symbol_code']}' 不存在")
                        continue

                    # 解析方向
                    side = side_map.get(data['side'])
                    if not side:
                        self.errors.append(f"第{i}行: 无效的交易方向 '{data['side']}'")
                        continue

                    # 解析数量
                    try:
                        quantity = Decimal(data['quantity'].replace(',', ''))
                    except (InvalidOperation, ValueError):
                        self.errors.append(f"第{i}行: 无效的数量 '{data['quantity']}'")
                        continue

                    # 解析价格
                    try:
                        price = Decimal(data['price'].replace(',', ''))
                    except (InvalidOperation, ValueError):
                        self.errors.append(f"第{i}行: 无效的价格 '{data['price']}'")
                        continue

                    # 解析可选字段
                    executed_price = None
                    if data.get('executed_price'):
                        try:
                            executed_price = Decimal(data['executed_price'].replace(',', ''))
                        except (InvalidOperation, ValueError):
                            pass

                    commission = Decimal('0')
                    if data.get('commission'):
                        try:
                            commission = Decimal(data['commission'].replace(',', ''))
                        except (InvalidOperation, ValueError):
                            pass

                    profit_loss = Decimal('0')
                    if data.get('profit_loss'):
                        try:
                            profit_loss = Decimal(data['profit_loss'].replace(',', ''))
                        except (InvalidOperation, ValueError):
                            pass

                    slippage = Decimal('0')
                    if data.get('slippage'):
                        try:
                            slippage = Decimal(data['slippage'].replace(',', ''))
                        except (InvalidOperation, ValueError):
                            pass

                    # 解析交易时间
                    trade_time = timezone.now()
                    if data.get('trade_time'):
                        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y/%m/%d %H:%M:%S', '%Y/%m/%d']:
                            try:
                                trade_time = datetime.strptime(data['trade_time'], fmt)
                                trade_time = timezone.make_aware(trade_time)
                                break
                            except ValueError:
                                continue

                    # 生成订单ID
                    order_id = data.get('order_id') or f"IMP{timezone.now().strftime('%Y%m%d%H%M%S')}{i:04d}"

                    # 检查订单ID是否已存在
                    if self.TradeLog.objects.filter(order_id=order_id).exists():
                        self.skip_count += 1
                        continue

                    # 创建交易记录
                    self.TradeLog.objects.create(
                        account=account,
                        symbol=symbol,
                        strategy=strategy,
                        side=side,
                        quantity=quantity,
                        price=price,
                        executed_price=executed_price or price,
                        commission=commission,
                        slippage=slippage,
                        profit_loss=profit_loss,
                        status='filled',
                        order_id=order_id,
                        trade_time=trade_time,
                        notes=data.get('notes', ''),
                    )
                    self.success_count += 1

                except Exception as e:
                    self.errors.append(f'第{i}行: 处理错误 - {str(e)}')
                    continue

        return len(self.errors) == 0

    def import_symbols(self, file_content):
        """
        导入交易标的
        CSV格式要求列：标的代码, 标的名称, 类型, 交易所, 计价货币, 合约乘数
        """
        self.errors = []
        self.success_count = 0
        self.skip_count = 0

        try:
            rows = self.parse_csv(file_content)
        except Exception as e:
            self.errors.append(f'CSV解析错误: {str(e)}')
            return False

        # 类型映射
        type_map = {
            '股票': 'stock', 'stock': 'stock',
            '期货': 'futures', 'futures': 'futures',
            '外汇': 'forex', 'forex': 'forex',
            '加密货币': 'crypto', 'crypto': 'crypto',
            '指数': 'index', 'index': 'index',
            '商品': 'commodity', 'commodity': 'commodity',
            '债券': 'bond', 'bond': 'bond',
            'ETF': 'etf', 'etf': 'etf',
        }

        # 列名映射
        column_map = {
            '标的代码': 'code',
            '标的名称': 'name',
            '类型': 'symbol_type',
            '交易所': 'exchange',
            '计价货币': 'currency',
            '合约乘数': 'contract_size',
            '最小变动': 'minimum_tick',
            '保证金率': 'margin_rate',
            '手续费率': 'commission_rate',
            '每手手续费': 'commission_per_contract',
            '描述': 'description',
        }

        with transaction.atomic():
            for i, row in enumerate(rows, start=2):
                try:
                    # 标准化列名
                    data = {}
                    for key, value in row.items():
                        clean_key = key.strip()
                        if clean_key in column_map:
                            data[column_map[clean_key]] = value.strip() if value else ''

                    # 验证必填字段
                    if not data.get('code'):
                        self.errors.append(f'第{i}行: 缺少标的代码')
                        continue

                    if not data.get('name'):
                        self.errors.append(f'第{i}行: 缺少标的名称')
                        continue

                    # 检查是否已存在
                    if self.Symbol.objects.filter(code=data['code']).exists():
                        self.skip_count += 1
                        continue

                    # 解析类型
                    symbol_type = type_map.get(data.get('symbol_type', ''), 'stock')

                    # 解析数值字段
                    contract_size = Decimal('1')
                    if data.get('contract_size'):
                        try:
                            contract_size = Decimal(data['contract_size'])
                        except (InvalidOperation, ValueError):
                            pass

                    minimum_tick = Decimal('0.01')
                    if data.get('minimum_tick'):
                        try:
                            minimum_tick = Decimal(data['minimum_tick'])
                        except (InvalidOperation, ValueError):
                            pass

                    margin_rate = None
                    if data.get('margin_rate'):
                        try:
                            margin_rate = Decimal(data['margin_rate'])
                        except (InvalidOperation, ValueError):
                            pass

                    commission_rate = None
                    if data.get('commission_rate'):
                        try:
                            commission_rate = Decimal(data['commission_rate'])
                        except (InvalidOperation, ValueError):
                            pass

                    commission_per_contract = Decimal('0')
                    if data.get('commission_per_contract'):
                        try:
                            commission_per_contract = Decimal(data['commission_per_contract'])
                        except (InvalidOperation, ValueError):
                            pass

                    # 创建标的
                    self.Symbol.objects.create(
                        code=data['code'],
                        name=data['name'],
                        symbol_type=symbol_type,
                        exchange=data.get('exchange', ''),
                        currency=data.get('currency', 'CNY') or 'CNY',
                        contract_size=contract_size,
                        minimum_tick=minimum_tick,
                        margin_rate=margin_rate,
                        commission_rate=commission_rate,
                        commission_per_contract=commission_per_contract,
                        description=data.get('description', ''),
                    )
                    self.success_count += 1

                except Exception as e:
                    self.errors.append(f'第{i}行: 处理错误 - {str(e)}')
                    continue

        return len(self.errors) == 0

    def get_import_result(self):
        """获取导入结果"""
        return {
            'success': len(self.errors) == 0,
            'success_count': self.success_count,
            'skip_count': self.skip_count,
            'error_count': len(self.errors),
            'errors': self.errors[:50],  # 只返回前50个错误
        }


def get_trade_import_template():
    """获取交易导入模板"""
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        '交易时间', '标的代码', '方向', '数量', '价格', '成交价',
        '手续费', '滑点', '盈亏', '订单ID', '备注'
    ]
    writer.writerow(headers)

    # 示例数据
    writer.writerow([
        '2025-01-01 09:30:00', 'AAPL', '买入', '100', '150.00', '150.05',
        '5.00', '0.05', '0', 'ORDER001', '示例交易'
    ])

    output.seek(0)
    return output


def get_symbol_import_template():
    """获取标的导入模板"""
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        '标的代码', '标的名称', '类型', '交易所', '计价货币',
        '合约乘数', '最小变动', '保证金率', '手续费率', '每手手续费', '描述'
    ]
    writer.writerow(headers)

    # 示例数据
    writer.writerow([
        'AAPL', '苹果公司', '股票', 'NASDAQ', 'USD',
        '1', '0.01', '', '0.0001', '0', '苹果公司股票'
    ])
    writer.writerow([
        'IF2401', '沪深300指数期货2401', '期货', '中金所', 'CNY',
        '300', '0.2', '0.12', '0.000023', '0', '股指期货'
    ])

    output.seek(0)
    return output
