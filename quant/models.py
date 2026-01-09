from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal


class StockData(models.Model):
    """股票历史日线数据"""
    symbol = models.CharField('股票代码', max_length=20, db_index=True)
    date = models.DateField('日期', db_index=True)
    open = models.DecimalField('开盘价', max_digits=12, decimal_places=4)
    high = models.DecimalField('最高价', max_digits=12, decimal_places=4)
    low = models.DecimalField('最低价', max_digits=12, decimal_places=4)
    close = models.DecimalField('收盘价', max_digits=12, decimal_places=4)
    volume = models.BigIntegerField('成交量')
    amount = models.DecimalField('成交额', max_digits=20, decimal_places=2, null=True, blank=True)
    adj_close = models.DecimalField('复权收盘价', max_digits=12, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '股票日线数据'
        verbose_name_plural = verbose_name
        unique_together = ['symbol', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['symbol', 'date']),
        ]

    def __str__(self):
        return f"{self.symbol} {self.date}"


class Strategy(models.Model):
    """量化策略配置"""
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('active', '运行中'),
        ('paused', '已暂停'),
        ('stopped', '已停止'),
    ]

    STRATEGY_TYPE_CHOICES = [
        ('ma_cross', '均线交叉'),
        ('momentum', '动量策略'),
        ('mean_reversion', '均值回归'),
        ('breakout', '突破策略'),
        ('pair_trading', '配对交易'),
        ('grid', '网格交易'),
        ('custom', '自定义'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='所有者')
    name = models.CharField('策略名称', max_length=100)
    strategy_type = models.CharField('策略类型', max_length=20, choices=STRATEGY_TYPE_CHOICES, default='custom')
    description = models.TextField('策略描述', blank=True)
    parameters = models.JSONField('策略参数', default=dict, help_text='JSON格式的策略参数')
    symbols = models.JSONField('交易标的', default=list, help_text='策略关注的股票代码列表')
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='draft')
    initial_capital = models.DecimalField('初始资金', max_digits=15, decimal_places=2, default=Decimal('100000'))
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '量化策略'
        verbose_name_plural = verbose_name
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.name} ({self.get_strategy_type_display()})"


class BacktestResult(models.Model):
    """回测结果报告"""
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, verbose_name='策略', related_name='backtest_results')
    name = models.CharField('回测名称', max_length=100, blank=True)
    start_date = models.DateField('开始日期')
    end_date = models.DateField('结束日期')
    initial_capital = models.DecimalField('初始资金', max_digits=15, decimal_places=2)
    final_capital = models.DecimalField('最终资金', max_digits=15, decimal_places=2)
    total_return = models.DecimalField('总收益率', max_digits=10, decimal_places=4, help_text='百分比')
    annual_return = models.DecimalField('年化收益率', max_digits=10, decimal_places=4, null=True, blank=True)
    sharpe_ratio = models.DecimalField('夏普比率', max_digits=8, decimal_places=4, null=True, blank=True)
    sortino_ratio = models.DecimalField('索提诺比率', max_digits=8, decimal_places=4, null=True, blank=True)
    max_drawdown = models.DecimalField('最大回撤', max_digits=10, decimal_places=4, help_text='百分比')
    max_drawdown_duration = models.IntegerField('最大回撤持续天数', null=True, blank=True)
    win_rate = models.DecimalField('胜率', max_digits=6, decimal_places=2, null=True, blank=True)
    profit_factor = models.DecimalField('盈亏比', max_digits=8, decimal_places=4, null=True, blank=True)
    total_trades = models.IntegerField('总交易次数', default=0)
    winning_trades = models.IntegerField('盈利次数', default=0)
    losing_trades = models.IntegerField('亏损次数', default=0)
    avg_trade_return = models.DecimalField('平均每笔收益', max_digits=10, decimal_places=4, null=True, blank=True)
    trades_data = models.JSONField('交易明细', default=list, help_text='交易对列表')
    equity_curve = models.JSONField('权益曲线', default=list, help_text='每日净值数据')
    parameters_used = models.JSONField('使用的参数', default=dict)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '回测结果'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.strategy.name} 回测 ({self.start_date} ~ {self.end_date})"

    @property
    def net_profit(self):
        """净利润"""
        return self.final_capital - self.initial_capital


class TradeOrder(models.Model):
    """委托单"""
    ORDER_TYPE_CHOICES = [
        ('market', '市价单'),
        ('limit', '限价单'),
        ('stop', '止损单'),
        ('stop_limit', '止损限价单'),
    ]

    SIDE_CHOICES = [
        ('buy', '买入'),
        ('sell', '卖出'),
    ]

    STATUS_CHOICES = [
        ('pending', '待提交'),
        ('submitted', '已提交'),
        ('partial', '部分成交'),
        ('filled', '已成交'),
        ('cancelled', '已取消'),
        ('rejected', '已拒绝'),
    ]

    MODE_CHOICES = [
        ('backtest', '回测'),
        ('paper', '模拟'),
        ('live', '实盘'),
    ]

    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, verbose_name='策略', related_name='orders', null=True, blank=True)
    backtest = models.ForeignKey(BacktestResult, on_delete=models.CASCADE, verbose_name='回测', related_name='orders', null=True, blank=True)
    mode = models.CharField('交易模式', max_length=20, choices=MODE_CHOICES, default='backtest')
    symbol = models.CharField('股票代码', max_length=20, db_index=True)
    order_type = models.CharField('订单类型', max_length=20, choices=ORDER_TYPE_CHOICES, default='market')
    side = models.CharField('方向', max_length=10, choices=SIDE_CHOICES)
    quantity = models.IntegerField('委托数量')
    price = models.DecimalField('委托价格', max_digits=12, decimal_places=4, null=True, blank=True)
    filled_quantity = models.IntegerField('成交数量', default=0)
    filled_price = models.DecimalField('成交均价', max_digits=12, decimal_places=4, null=True, blank=True)
    commission = models.DecimalField('手续费', max_digits=10, decimal_places=2, default=Decimal('0'))
    slippage = models.DecimalField('滑点', max_digits=10, decimal_places=4, default=Decimal('0'))
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    signal_time = models.DateTimeField('信号时间', null=True, blank=True)
    order_time = models.DateTimeField('委托时间', null=True, blank=True)
    filled_time = models.DateTimeField('成交时间', null=True, blank=True)
    reason = models.CharField('交易原因', max_length=200, blank=True)
    notes = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '委托单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['symbol', 'status']),
            models.Index(fields=['strategy', 'created_at']),
        ]

    def __str__(self):
        return f"{self.symbol} {self.get_side_display()} {self.quantity}股 @ {self.price or '市价'}"

    @property
    def filled_amount(self):
        """成交金额"""
        if self.filled_quantity and self.filled_price:
            return self.filled_quantity * self.filled_price
        return Decimal('0')
