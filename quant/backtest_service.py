import backtrader as bt
import pandas as pd
import re
from decimal import Decimal
from datetime import datetime, date
from quant.models import StockData, QuantStrategy, BacktestResult


class BacktestValidationError(Exception):
    """回测数据验证错误"""
    pass


def validate_symbol(symbol):
    """验证股票代码格式"""
    if not symbol or not isinstance(symbol, str):
        raise BacktestValidationError('股票代码不能为空')
    # A股代码格式：6位数字
    if not re.match(r'^[0-9]{6}$', symbol):
        raise BacktestValidationError(f'无效的股票代码格式: {symbol}')
    return symbol


def validate_date_range(start_date, end_date):
    """验证日期范围"""
    if not start_date or not end_date:
        raise BacktestValidationError('开始日期和结束日期不能为空')
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    if start_date >= end_date:
        raise BacktestValidationError('开始日期必须早于结束日期')
    if end_date > date.today():
        raise BacktestValidationError('结束日期不能晚于今天')
    return start_date, end_date


def validate_initial_capital(capital):
    """验证初始资金"""
    if capital is None or capital <= 0:
        raise BacktestValidationError('初始资金必须大于0')
    if capital < 1000:
        raise BacktestValidationError('初始资金不能少于1000元')
    if capital > 1e12:  # 1万亿
        raise BacktestValidationError('初始资金超出合理范围')
    return capital


class PandasDataWithPrevClose(bt.feeds.PandasData):
    """自定义 Pandas 数据源（含前收盘价用于涨跌停判断）"""
    lines = ('prev_close',)
    params = (
        ('datetime', None),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('prev_close', 'prev_close'),
        ('openinterest', -1),
    )


class AStockCommission(bt.CommInfoBase):
    """A股佣金：万三，最低5元，印花税千一（卖出）"""
    params = (
        ('commission', 0.0003),  # 万三
        ('min_commission', 5.0),  # 最低5元
        ('stamp_tax', 0.001),  # 印花税千一
        ('stocklike', True),
        ('commtype', bt.CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec):
        value = abs(size) * price
        commission = value * self.p.commission
        commission = max(commission, self.p.min_commission)
        # 卖出加印花税
        if size < 0:
            commission += value * self.p.stamp_tax
        return commission


class LimitChecker:
    """涨跌停检查器"""

    @staticmethod
    def get_limit_rate(symbol):
        """根据股票代码获取涨跌停幅度"""
        if symbol.startswith('68') or symbol.startswith('30'):
            return 0.20  # 科创板/创业板 20%
        elif symbol.startswith('8') or symbol.startswith('4'):
            return 0.30  # 北交所 30%
        else:
            return 0.10  # 主板 10%

    @staticmethod
    def is_limit_up(price, prev_close, limit_rate=0.10):
        """判断是否涨停"""
        if prev_close <= 0:
            return False
        limit_price = round(prev_close * (1 + limit_rate), 2)
        return price >= limit_price

    @staticmethod
    def is_limit_down(price, prev_close, limit_rate=0.10):
        """判断是否跌停"""
        if prev_close <= 0:
            return False
        limit_price = round(prev_close * (1 - limit_rate), 2)
        return price <= limit_price


class EquityCurveAnalyzer(bt.Analyzer):
    """记录每日权益曲线"""

    def start(self):
        self.equity = []

    def next(self):
        self.equity.append({
            'date': self.data.datetime.date(0).isoformat(),
            'value': round(self.strategy.broker.getvalue(), 2)
        })

    def get_analysis(self):
        return self.equity


class TradeRecorder(bt.Analyzer):
    """记录交易明细"""

    def start(self):
        self.trades = []

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'symbol': trade.data._name,
                'entry_date': bt.num2date(trade.dtopen).date().isoformat(),
                'exit_date': bt.num2date(trade.dtclose).date().isoformat(),
                'size': trade.size,
                'entry_price': round(trade.price, 2),
                'exit_price': round(trade.price + trade.pnl / trade.size if trade.size else 0, 2),
                'pnl': round(trade.pnl, 2),
                'pnl_pct': round(trade.pnlcomm / (trade.price * abs(trade.size)) * 100 if trade.size else 0, 2),
                'commission': round(trade.commission, 2),
            })

    def get_analysis(self):
        return self.trades


class SimpleMACrossStrategy(bt.Strategy):
    """简单均线交叉策略（考虑 T+1 和涨跌停）"""
    params = (
        ('fast_period', 5),
        ('slow_period', 20),
        ('check_limit', True),  # 是否检查涨跌停
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)
        self.order = None
        self.buy_date = None  # T+1 控制
        self.limit_rate = LimitChecker.get_limit_rate(self.data._name or '000000')

    def next(self):
        if self.order:
            return

        current_date = self.data.datetime.date(0)
        current_price = self.data.close[0]

        # 涨跌停检查
        if self.p.check_limit and hasattr(self.data, 'prev_close'):
            prev_close = self.data.prev_close[0]
            if prev_close > 0:
                # 涨停时无法买入
                if LimitChecker.is_limit_up(current_price, prev_close, self.limit_rate):
                    return
                # 跌停时无法卖出
                if self.position and LimitChecker.is_limit_down(current_price, prev_close, self.limit_rate):
                    return

        if not self.position:
            if self.crossover > 0:
                self.order = self.buy()
                self.buy_date = current_date
        else:
            # T+1: 买入当天不能卖出
            if self.buy_date and current_date <= self.buy_date:
                return
            if self.crossover < 0:
                self.order = self.sell()

    def notify_order(self, order):
        if order.status in [order.Completed]:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None


class BacktestService:
    """回测服务类"""

    def __init__(self, strategy_id, initial_capital=100000):
        validate_initial_capital(initial_capital)
        self.strategy_obj = QuantStrategy.objects.get(id=strategy_id)
        self.initial_capital = Decimal(str(initial_capital))
        self.cerebro = bt.Cerebro()

    def load_data(self, symbol, start_date, end_date):
        """从 StockData 加载数据（含前收盘价用于涨跌停判断）"""
        # 验证输入
        symbol = validate_symbol(symbol)
        start_date, end_date = validate_date_range(start_date, end_date)

        qs = StockData.objects.filter(
            symbol=symbol,
            date__gte=start_date,
            date__lte=end_date
        ).order_by('date').values('date', 'open', 'high', 'low', 'close', 'volume')

        if not qs.exists():
            raise BacktestValidationError(f'{symbol} 在指定日期范围内无数据')

        data = []
        prev_close = None
        invalid_rows = []
        for row in qs:
            # 验证 OHLCV 数据有效性
            ohlcv = [row['open'], row['high'], row['low'], row['close'], row['volume']]
            if any(v is None or v <= 0 for v in ohlcv[:4]):  # OHLC 必须为正
                invalid_rows.append(row['date'])
                continue
            if row['high'] < row['low']:
                invalid_rows.append(row['date'])
                continue

            data.append({
                'datetime': datetime.combine(row['date'], datetime.min.time()),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']) if row['volume'] else 0,
                'prev_close': prev_close if prev_close else float(row['close']),
            })
            prev_close = float(row['close'])

        if invalid_rows:
            # 记录警告但不中断（跳过无效数据）
            import logging
            logging.warning(f'{symbol} 有 {len(invalid_rows)} 条无效数据被跳过')

        if len(data) < 20:  # 至少需要20个交易日数据
            raise BacktestValidationError(f'{symbol} 有效数据不足，至少需要20个交易日')

        df = pd.DataFrame(data)
        df.set_index('datetime', inplace=True)
        return df

    def add_data(self, symbol, start_date, end_date):
        """添加数据到回测引擎"""
        df = self.load_data(symbol, start_date, end_date)
        data = PandasDataWithPrevClose(dataname=df)
        self.cerebro.adddata(data, name=symbol)
        return df

    def run(self, symbol, start_date, end_date, strategy_class=None,
            slippage=0.001, check_limit=True, **strategy_params):
        """
        执行回测

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            strategy_class: 策略类
            slippage: 滑点比例，默认0.1%
            check_limit: 是否检查涨跌停，默认True
            **strategy_params: 策略参数
        """
        # 加载数据
        df = self.add_data(symbol, start_date, end_date)

        # 设置初始资金
        self.cerebro.broker.setcash(float(self.initial_capital))

        # 设置 A 股佣金
        self.cerebro.broker.addcommissioninfo(AStockCommission())

        # 设置滑点
        if slippage > 0:
            self.cerebro.broker.set_slippage_perc(slippage, slip_open=True, slip_match=True)

        # 添加策略
        if strategy_class is None:
            strategy_class = SimpleMACrossStrategy
        merged_params = {**self.strategy_obj.parameters, **strategy_params}
        merged_params['check_limit'] = check_limit
        self.cerebro.addstrategy(strategy_class, **merged_params)

        # 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.03)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(EquityCurveAnalyzer, _name='equity_curve')
        self.cerebro.addanalyzer(TradeRecorder, _name='trade_recorder')

        # 运行回测
        results = self.cerebro.run()
        strat = results[0]

        # 提取结果
        return self._extract_results(strat, symbol, start_date, end_date, merged_params)

    def _extract_results(self, strat, symbol, start_date, end_date, params):
        """提取回测结果并保存"""
        final_value = self.cerebro.broker.getvalue()

        # 分析器结果
        sharpe = strat.analyzers.sharpe.get_analysis()
        drawdown = strat.analyzers.drawdown.get_analysis()
        trades = strat.analyzers.trades.get_analysis()
        returns = strat.analyzers.returns.get_analysis()
        equity_curve = strat.analyzers.equity_curve.get_analysis()
        trades_data = strat.analyzers.trade_recorder.get_analysis()

        # 计算指标
        total_return = (final_value - float(self.initial_capital)) / float(self.initial_capital) * 100
        sharpe_ratio = sharpe.get('sharperatio') or 0
        max_drawdown = drawdown.get('max', {}).get('drawdown', 0) or 0
        max_drawdown_duration = drawdown.get('max', {}).get('len', 0) or 0

        # 交易统计
        total_trades = trades.get('total', {}).get('total', 0) or 0
        won = trades.get('won', {}).get('total', 0) or 0
        lost = trades.get('lost', {}).get('total', 0) or 0
        win_rate = (won / total_trades * 100) if total_trades > 0 else 0

        # 盈亏比
        avg_won = trades.get('won', {}).get('pnl', {}).get('average', 0) or 0
        avg_lost = abs(trades.get('lost', {}).get('pnl', {}).get('average', 0) or 1)
        profit_factor = avg_won / avg_lost if avg_lost > 0 else 0

        # 平均每笔收益
        avg_trade_return = trades.get('pnl', {}).get('net', {}).get('average', 0) or 0

        # 年化收益
        annual_return = returns.get('rnorm100') or 0

        # 确保权益曲线有数据
        if not equity_curve:
            equity_curve = [
                {'date': start_date.isoformat(), 'value': float(self.initial_capital)},
                {'date': end_date.isoformat(), 'value': final_value}
            ]

        # 保存到数据库
        result = BacktestResult.objects.create(
            strategy=self.strategy_obj,
            name=f'{symbol} 回测',
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=Decimal(str(round(final_value, 2))),
            total_return=Decimal(str(round(total_return, 4))),
            annual_return=Decimal(str(round(annual_return, 4))) if annual_return else None,
            sharpe_ratio=Decimal(str(round(sharpe_ratio, 4))) if sharpe_ratio else None,
            max_drawdown=Decimal(str(round(max_drawdown, 4))),
            max_drawdown_duration=max_drawdown_duration,
            win_rate=Decimal(str(round(win_rate, 2))) if win_rate else None,
            profit_factor=Decimal(str(round(profit_factor, 4))) if profit_factor else None,
            total_trades=total_trades,
            winning_trades=won,
            losing_trades=lost,
            avg_trade_return=Decimal(str(round(avg_trade_return, 4))) if avg_trade_return else None,
            equity_curve=equity_curve,
            trades_data=trades_data,
            parameters_used=params,
        )

        return result


def run_backtest(strategy_id, symbol, start_date, end_date, initial_capital=100000, **params):
    """便捷函数：执行回测"""
    service = BacktestService(strategy_id, initial_capital)
    return service.run(symbol, start_date, end_date, **params)
