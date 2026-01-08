from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import decimal


class Account(models.Model):
    """交易账户模型"""
    ACCOUNT_TYPE_CHOICES = [
        ('stock', '股票'),
        ('futures', '期货'),
        ('forex', '外汇'),
        ('crypto', '加密货币'),
        ('options', '期权'),
    ]

    STATUS_CHOICES = [
        ('active', '活跃'),
        ('inactive', '未激活'),
        ('frozen', '冻结'),
        ('closed', '已关闭'),
    ]

    name = models.CharField('账户名称', max_length=100, unique=True)
    account_type = models.CharField('账户类型', max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    broker = models.CharField('券商/交易所', max_length=100, blank=True)
    account_id = models.CharField('账户ID', max_length=100, blank=True)
    initial_balance = models.DecimalField('初始资金', max_digits=15, decimal_places=2, default=0)
    current_balance = models.DecimalField('当前余额', max_digits=15, decimal_places=2, default=0)
    available_balance = models.DecimalField('可用余额', max_digits=15, decimal_places=2, default=0)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='所有者', related_name='trading_accounts')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    notes = models.TextField('备注', blank=True)

    class Meta:
        verbose_name = '交易账户'
        verbose_name_plural = '交易账户'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_account_type_display()})"

    @property
    def total_profit_loss(self):
        """总盈亏"""
        return self.current_balance - self.initial_balance

    @property
    def profit_loss_ratio(self):
        """盈亏比例"""
        if self.initial_balance > 0:
            return (self.total_profit_loss / self.initial_balance) * 100
        return 0


class AccountTransaction(models.Model):
    """账户流水明细模型"""
    TRANSACTION_TYPE_CHOICES = [
        ('deposit', '入金'),
        ('withdraw', '出金'),
        ('trade_profit', '交易盈利'),
        ('trade_loss', '交易亏损'),
        ('commission', '手续费'),
        ('dividend', '分红'),
        ('interest', '利息'),
        ('adjustment', '调整'),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户',
                               related_name='transactions')
    transaction_type = models.CharField('交易类型', max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField('金额', max_digits=15, decimal_places=2,
                                 help_text='正数表示增加，负数表示减少')
    balance_before = models.DecimalField('变动前余额', max_digits=15, decimal_places=2)
    balance_after = models.DecimalField('变动后余额', max_digits=15, decimal_places=2)
    trade_log = models.ForeignKey('TradeLog', on_delete=models.SET_NULL, null=True, blank=True,
                                  verbose_name='关联交易', related_name='transactions')
    description = models.CharField('描述', max_length=200, blank=True)
    transaction_time = models.DateTimeField('交易时间', default=timezone.now)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '账户流水'
        verbose_name_plural = '账户流水'
        ordering = ['-transaction_time']
        indexes = [
            models.Index(fields=['account', '-transaction_time']),
        ]

    def __str__(self):
        return f"{self.account.name} - {self.get_transaction_type_display()}: {self.amount}"


class Symbol(models.Model):
    """交易标的模型"""
    SYMBOL_TYPE_CHOICES = [
        ('stock', '股票'),
        ('futures', '期货'),
        ('forex', '外汇'),
        ('crypto', '加密货币'),
        ('index', '指数'),
        ('commodity', '商品'),
        ('bond', '债券'),
        ('etf', 'ETF'),
    ]

    name = models.CharField('标的名称', max_length=100, help_text='例如：苹果公司、沪深300指数期货')
    code = models.CharField('标的代码', max_length=50, unique=True, help_text='例如：AAPL、IF2401')
    symbol_type = models.CharField('标的类型', max_length=20, choices=SYMBOL_TYPE_CHOICES)
    exchange = models.CharField('交易所', max_length=100, blank=True, help_text='例如：上期所、CME、NYSE')
    currency = models.CharField('计价货币', max_length=10, default='CNY', help_text='例如：CNY、USD、EUR')
    contract_size = models.DecimalField('合约乘数', max_digits=15, decimal_places=4, default=1,
                                       help_text='每点代表的价值，例如：股指期货300，黄金期货1000')
    minimum_tick = models.DecimalField('最小变动价位', max_digits=10, decimal_places=4, default=0.01,
                                      help_text='价格波动的最小单位')
    margin_rate = models.DecimalField('保证金比例', max_digits=10, decimal_places=4, null=True, blank=True,
                                     help_text='期货保证金比例，例如：0.15表示15%')
    commission_rate = models.DecimalField('手续费率', max_digits=10, decimal_places=6, null=True, blank=True,
                                        help_text='手续费比例，例如：0.0001表示万分之一')
    commission_per_contract = models.DecimalField('每手手续费', max_digits=10, decimal_places=2, default=0,
                                                 help_text='固定手续费，每手多少元')
    is_active = models.BooleanField('是否活跃', default=True, help_text='是否可交易')
    description = models.TextField('描述', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '交易标的'
        verbose_name_plural = '交易标的'
        ordering = ['symbol_type', 'code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def contract_value(self, price=None):
        """计算合约价值
        Args:
            price: 价格，如果为None则返回乘数
        Returns:
            合约价值
        """
        if price is None:
            return self.contract_size
        return self.contract_size * price

    def calculate_profit_loss(self, entry_price, exit_price, quantity):
        """计算盈亏
        Args:
            entry_price: 开仓价
            exit_price: 平仓价
            quantity: 数量
        Returns:
            盈亏金额
        """
        if self.symbol_type in ['futures', 'index']:
            # 期货/指数：(平仓价 - 开仓价) * 合约乘数 * 数量
            return (exit_price - entry_price) * self.contract_size * quantity
        else:
            # 股票/其他：(平仓价 - 开仓价) * 数量
            return (exit_price - entry_price) * quantity

    def calculate_commission(self, price, quantity):
        """计算手续费
        Args:
            price: 成交价格
            quantity: 数量
        Returns:
            手续费金额
        """
        commission = 0
        # 按比例计算
        if self.commission_rate is not None:
            if self.symbol_type in ['futures', 'index']:
                # 期货按合约价值计算
                contract_value = price * self.contract_size * quantity
                commission += contract_value * self.commission_rate
            else:
                # 股票按成交金额计算
                commission += price * quantity * self.commission_rate

        # 固定手续费
        if self.commission_per_contract > 0:
            if self.symbol_type in ['futures', 'index']:
                commission += self.commission_per_contract * quantity
            else:
                commission += self.commission_per_contract

        return commission


class Strategy(models.Model):
    """交易策略模型"""
    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('active', '运行中'),
        ('paused', '暂停'),
        ('stopped', '已停止'),
        ('archived', '已归档'),
    ]

    name = models.CharField('策略名称', max_length=100, unique=True)
    description = models.TextField('策略描述', blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='draft')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='创建者', related_name='strategies')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '交易策略'
        verbose_name_plural = '交易策略'
        ordering = ['-created_at']

    def __str__(self):
        return self.name


class TradeImage(models.Model):
    """交易截图模型"""
    trade_log = models.ForeignKey('TradeLog', on_delete=models.CASCADE, verbose_name='交易日志',
                                  related_name='images')
    image = models.ImageField('截图', upload_to='trade_images/%Y/%m/%d/')
    description = models.CharField('描述', max_length=200, blank=True)
    uploaded_at = models.DateTimeField('上传时间', auto_now_add=True)

    class Meta:
        verbose_name = '交易截图'
        verbose_name_plural = '交易截图'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.trade_log.order_id} - {self.image.name}"


class TradeLog(models.Model):
    """交易日志模型"""
    SIDE_CHOICES = [
        ('buy', '买入'),
        ('sell', '卖出'),
    ]

    STATUS_CHOICES = [
        ('pending', '待成交'),
        ('filled', '已成交'),
        ('partially_filled', '部分成交'),
        ('cancelled', '已取消'),
        ('rejected', '已拒绝'),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户', related_name='trade_logs')
    strategy = models.ForeignKey(Strategy, on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name='策略', related_name='trade_logs')
    symbol = models.ForeignKey(Symbol, on_delete=models.PROTECT, verbose_name='交易标的', related_name='trade_logs')
    side = models.CharField('方向', max_length=10, choices=SIDE_CHOICES)
    quantity = models.DecimalField('数量', max_digits=15, decimal_places=4)
    price = models.DecimalField('价格', max_digits=15, decimal_places=4)
    executed_price = models.DecimalField('成交价', max_digits=15, decimal_places=4,
                                        null=True, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending')
    order_id = models.CharField('订单ID', max_length=100, unique=True)
    commission = models.DecimalField('手续费', max_digits=10, decimal_places=2, default=0)
    slippage = models.DecimalField('滑点', max_digits=10, decimal_places=4, default=0)
    profit_loss = models.DecimalField('盈亏', max_digits=15, decimal_places=2, default=0,
                                     help_text='已实现盈亏')
    trade_time = models.DateTimeField('交易时间', default=timezone.now)
    notes = models.TextField('备注', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '交易日志'
        verbose_name_plural = '交易日志'
        ordering = ['-trade_time']
        indexes = [
            models.Index(fields=['-trade_time']),
            models.Index(fields=['account', '-trade_time']),
        ]

    def __str__(self):
        return f"{self.get_side_display()} {self.symbol.code} {self.quantity}@{self.price}"

    @property
    def total_amount(self):
        """交易总金额"""
        if self.quantity is not None and self.price is not None:
            return self.quantity * self.price
        return 0


class Position(models.Model):
    """持仓模型"""
    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户', related_name='positions')
    symbol = models.ForeignKey(Symbol, on_delete=models.PROTECT, verbose_name='交易标的', related_name='positions')
    quantity = models.DecimalField('持仓数量', max_digits=15, decimal_places=4)
    avg_price = models.DecimalField('平均成本', max_digits=15, decimal_places=4)
    current_price = models.DecimalField('当前价格', max_digits=15, decimal_places=4, null=True, blank=True)
    market_value = models.DecimalField('市值', max_digits=15, decimal_places=2, default=0)
    profit_loss = models.DecimalField('盈亏', max_digits=15, decimal_places=2, default=0)
    profit_loss_ratio = models.DecimalField('盈亏比例', max_digits=10, decimal_places=2, default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '持仓'
        verbose_name_plural = '持仓'
        unique_together = [['account', 'symbol']]
        ordering = ['-market_value']

    def __str__(self):
        return f"{self.account.name} - {self.symbol.code}: {self.quantity}"


class DailyReport(models.Model):
    """每日报表模型"""
    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户',
                               related_name='daily_reports')
    report_date = models.DateField('报表日期', db_index=True)
    starting_balance = models.DecimalField('期初余额', max_digits=15, decimal_places=2)
    ending_balance = models.DecimalField('期末余额', max_digits=15, decimal_places=2)
    net_deposit = models.DecimalField('净入金', max_digits=15, decimal_places=2, default=0)
    profit_loss = models.DecimalField('当日盈亏', max_digits=15, decimal_places=2)
    profit_loss_ratio = models.DecimalField('当日盈亏比例', max_digits=10, decimal_places=2)
    trade_count = models.IntegerField('交易次数', default=0)
    win_count = models.IntegerField('盈利次数', default=0)
    loss_count = models.IntegerField('亏损次数', default=0)
    win_rate = models.DecimalField('胜率', max_digits=5, decimal_places=2, default=0)
    max_drawdown = models.DecimalField('最大回撤', max_digits=10, decimal_places=2, default=0)
    commission = models.DecimalField('手续费', max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '每日报表'
        verbose_name_plural = '每日报表'
        unique_together = [['account', 'report_date']]
        ordering = ['-report_date']

    def __str__(self):
        return f"{self.account.name} - {self.report_date}: {self.profit_loss}"


class MonthlyReport(models.Model):
    """月度报表模型"""
    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户',
                               related_name='monthly_reports')
    year = models.IntegerField('年份')
    month = models.IntegerField('月份')
    starting_balance = models.DecimalField('期初余额', max_digits=15, decimal_places=2)
    ending_balance = models.DecimalField('期末余额', max_digits=15, decimal_places=2)
    net_deposit = models.DecimalField('净入金', max_digits=15, decimal_places=2, default=0)
    profit_loss = models.DecimalField('月度盈亏', max_digits=15, decimal_places=2)
    profit_loss_ratio = models.DecimalField('月度盈亏比例', max_digits=10, decimal_places=2)
    trade_count = models.IntegerField('交易次数', default=0)
    win_rate = models.DecimalField('胜率', max_digits=5, decimal_places=2, default=0)
    max_drawdown = models.DecimalField('最大回撤', max_digits=10, decimal_places=2, default=0)
    sharpe_ratio = models.DecimalField('夏普比率', max_digits=10, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '月度报表'
        verbose_name_plural = '月度报表'
        unique_together = [['account', 'year', 'month']]
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.account.name} - {self.year}/{self.month}: {self.profit_loss}"


class PerformanceMetrics(models.Model):
    """策略绩效指标模型"""
    strategy = models.OneToOneField(Strategy, on_delete=models.CASCADE, verbose_name='策略',
                                   related_name='performance_metrics')
    total_trades = models.IntegerField('总交易次数', default=0)
    profitable_trades = models.IntegerField('盈利次数', default=0)
    losing_trades = models.IntegerField('亏损次数', default=0)
    win_rate = models.DecimalField('胜率', max_digits=5, decimal_places=2, default=0)
    total_profit = models.DecimalField('总盈利', max_digits=15, decimal_places=2, default=0)
    total_loss = models.DecimalField('总亏损', max_digits=15, decimal_places=2, default=0)
    profit_factor = models.DecimalField('盈亏比', max_digits=10, decimal_places=4, null=True, blank=True)
    average_profit = models.DecimalField('平均盈利', max_digits=15, decimal_places=2, default=0)
    average_loss = models.DecimalField('平均亏损', max_digits=15, decimal_places=2, default=0)
    largest_profit = models.DecimalField('最大盈利', max_digits=15, decimal_places=2, default=0)
    largest_loss = models.DecimalField('最大亏损', max_digits=15, decimal_places=2, default=0)
    max_drawdown = models.DecimalField('最大回撤', max_digits=10, decimal_places=2, default=0)
    max_drawdown_ratio = models.DecimalField('最大回撤比例', max_digits=10, decimal_places=2, default=0)
    sharpe_ratio = models.DecimalField('夏普比率', max_digits=10, decimal_places=4, null=True, blank=True)
    sortino_ratio = models.DecimalField('索提诺比率', max_digits=10, decimal_places=4, null=True, blank=True)
    calmar_ratio = models.DecimalField('卡玛比率', max_digits=10, decimal_places=4, null=True, blank=True)
    total_return = models.DecimalField('总收益率', max_digits=10, decimal_places=2, default=0)
    annualized_return = models.DecimalField('年化收益率', max_digits=10, decimal_places=4, null=True, blank=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '绩效指标'
        verbose_name_plural = '绩效指标'

    def __str__(self):
        return f"{self.strategy.name} - 绩效指标"