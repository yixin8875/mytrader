from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
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
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)
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

    def save(self, *args, **kwargs):
        # 自动设置变动前余额
        if not self.pk and not self.balance_before:
            self.balance_before = self.account.current_balance

        # 自动计算变动后余额
        if not self.pk and not self.balance_after:
            self.balance_after = self.balance_before + self.amount

        is_new = self.pk is None

        # 使用事务确保数据一致性
        with transaction.atomic():
            # 锁定账户记录防止并发问题
            if is_new:
                Account.objects.select_for_update().get(pk=self.account_id)

            super().save(*args, **kwargs)

            # 新建流水时自动更新账户余额
            if is_new:
                self.account.current_balance = self.balance_after
                self.account.save(update_fields=['current_balance'])


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
    def contract_value(self):
        """返回合约乘数"""
        return self.contract_size

    def get_contract_value(self, price=None):
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
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True)
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

    TRADE_TYPE_CHOICES = [
        ('open', '开仓'),
        ('close', '平仓'),
        ('add', '加仓'),
        ('reduce', '减仓'),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户', related_name='trade_logs')
    strategy = models.ForeignKey(Strategy, on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name='策略', related_name='trade_logs')
    symbol = models.ForeignKey(Symbol, on_delete=models.PROTECT, verbose_name='交易标的', related_name='trade_logs')
    side = models.CharField('方向', max_length=10, choices=SIDE_CHOICES)
    trade_type = models.CharField('交易类型', max_length=10, choices=TRADE_TYPE_CHOICES, default='open',
                                  help_text='开仓/平仓/加仓/减仓')
    opening_trade = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                      verbose_name='关联开仓', related_name='closing_trades',
                                      help_text='平仓时关联的开仓交易')
    quantity = models.DecimalField('数量', max_digits=15, decimal_places=4,
                                    validators=[MinValueValidator(Decimal('0.0001'))])
    price = models.DecimalField('价格', max_digits=15, decimal_places=4)
    executed_price = models.DecimalField('成交价', max_digits=15, decimal_places=4,
                                        null=True, blank=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    order_id = models.CharField('订单ID', max_length=100, unique=True)
    commission = models.DecimalField('手续费', max_digits=10, decimal_places=2, default=0)
    slippage = models.DecimalField('滑点', max_digits=10, decimal_places=4, default=0)
    profit_loss = models.DecimalField('盈亏', max_digits=15, decimal_places=2, default=0,
                                     help_text='已实现盈亏')
    trade_time = models.DateTimeField('交易时间', default=timezone.now)
    # 持仓时间分析字段
    open_time = models.DateTimeField('开仓时间', null=True, blank=True, help_text='建仓时间')
    close_time = models.DateTimeField('平仓时间', null=True, blank=True, help_text='平仓时间')
    holding_minutes = models.IntegerField('持仓分钟数', null=True, blank=True, help_text='自动计算')
    # 交易标签
    tags = models.ManyToManyField('TradeTag', verbose_name='交易标签', blank=True, related_name='trade_logs')
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
        """交易总金额（含合约乘数）"""
        if self.quantity is not None and self.price is not None:
            contract_size = self.symbol.contract_size if self.symbol else 1
            return self.quantity * self.price * contract_size
        return 0

    def calculate_profit_loss(self):
        """计算平仓盈亏（仅对平仓交易有效）

        做多：买入开仓 → 卖出平仓，盈亏 = (卖出价 - 买入价) * 数量
        做空：卖出开仓 → 买入平仓，盈亏 = (卖出价 - 买入价) * 数量
        """
        if self.trade_type not in ('close', 'reduce') or not self.opening_trade:
            return Decimal('0')

        entry_price = self.opening_trade.executed_price or self.opening_trade.price
        exit_price = self.executed_price or self.price
        contract_size = self.symbol.contract_size if self.symbol else 1

        # 根据开仓方向判断
        if self.opening_trade.side == 'buy':  # 平多仓（开仓是买入）
            pnl = (exit_price - entry_price) * self.quantity * contract_size
        else:  # 平空仓（开仓是卖出）
            pnl = (entry_price - exit_price) * self.quantity * contract_size

        return pnl - self.commission

    def save(self, *args, **kwargs):
        # 自动计算持仓时间
        if self.open_time and self.close_time:
            delta = self.close_time - self.open_time
            self.holding_minutes = int(delta.total_seconds() / 60)

        # 平仓时自动计算盈亏
        if self.trade_type in ('close', 'reduce') and self.opening_trade and self.profit_loss == 0:
            self.profit_loss = self.calculate_profit_loss()

        # 检查是否是新创建且状态为已成交
        is_new = self.pk is None
        old_status = None
        if not is_new:
            old_obj = TradeLog.objects.filter(pk=self.pk).first()
            old_status = old_obj.status if old_obj else None

        super().save(*args, **kwargs)

        # 状态变为已成交时，更新账户余额和持仓
        if self.status == 'filled' and (is_new or old_status != 'filled'):
            self._update_account_and_position()

    def _update_account_and_position(self):
        """更新账户余额和持仓

        支持做空：
        - 做多开仓(buy+open)：持仓增加（正数）
        - 做多平仓(sell+close)：持仓减少
        - 做空开仓(sell+open)：持仓减少（负数表示空头）
        - 做空平仓(buy+close)：持仓增加（向0靠近）
        """
        from decimal import Decimal, InvalidOperation
        import logging
        logger = logging.getLogger(__name__)

        # 持仓计算边界值
        MAX_POSITION_VALUE = Decimal('1e15')  # 1000万亿

        # 使用事务和行锁确保数据一致性
        with transaction.atomic():
            # 锁定账户记录
            account = Account.objects.select_for_update().get(pk=self.account_id)

            # 更新账户余额（已实现盈亏）
            if self.profit_loss != 0:
                account.current_balance += self.profit_loss
                account.save(update_fields=['current_balance'])

            # 获取或创建持仓（带锁）
            try:
                position = Position.objects.select_for_update().get(
                    account=self.account,
                    symbol=self.symbol
                )
            except Position.DoesNotExist:
                position = Position.objects.create(
                    account=self.account,
                    symbol=self.symbol,
                    quantity=Decimal('0'),
                    avg_price=Decimal('0')
                )

            exec_price = self.executed_price or self.price

            # 边界检查辅助函数
            def safe_calculate_cost(qty, price, add_qty, add_price):
                """安全计算加权平均成本，带边界检查"""
                try:
                    total_cost = Decimal(str(qty)) * Decimal(str(price)) + \
                                 Decimal(str(add_qty)) * Decimal(str(add_price))
                    if abs(total_cost) > MAX_POSITION_VALUE:
                        logger.error(f'持仓价值超出限制: {total_cost}')
                        raise ValueError('持仓价值超出最大允许范围')
                    return total_cost
                except (InvalidOperation, ValueError) as e:
                    logger.error(f'持仓计算错误: {e}')
                    raise

            # 根据交易类型和方向更新持仓
            if self.trade_type in ('open', 'add'):
                # 开仓/加仓
                if self.side == 'buy':
                    # 做多开仓：增加正数持仓
                    if position.quantity >= 0:
                        # 加权平均成本（带边界检查）
                        total_cost = safe_calculate_cost(position.quantity, position.avg_price, self.quantity, exec_price)
                        position.quantity += self.quantity
                        position.avg_price = total_cost / position.quantity if position.quantity > 0 else exec_price
                    else:
                        # 有空头持仓时买入，先平空再开多
                        position.quantity += self.quantity
                        if position.quantity > 0:
                            position.avg_price = exec_price
                else:
                    # 做空开仓：增加负数持仓
                    if position.quantity <= 0:
                        total_cost = safe_calculate_cost(abs(position.quantity), position.avg_price, self.quantity, exec_price)
                        position.quantity -= self.quantity
                        position.avg_price = total_cost / abs(position.quantity) if position.quantity != 0 else exec_price
                    else:
                        # 有多头持仓时卖出，先平多再开空
                        position.quantity -= self.quantity
                        if position.quantity < 0:
                            position.avg_price = exec_price
            else:
                # 平仓/减仓
                if self.side == 'sell':
                    # 卖出平仓（平多）
                    position.quantity -= self.quantity
                else:
                    # 买入平仓（平空）
                    position.quantity += self.quantity

            # 持仓为0时重置成本
            if position.quantity == 0:
                position.avg_price = Decimal('0')

            # 更新市值和浮动盈亏（支持空头）
            if position.current_price and position.quantity != 0:
                contract_size = self.symbol.contract_size if self.symbol else 1
                position.market_value = abs(position.quantity) * position.current_price * contract_size

                if position.quantity > 0:  # 多头
                    position.profit_loss = (position.current_price - position.avg_price) * position.quantity * contract_size
                else:  # 空头
                    position.profit_loss = (position.avg_price - position.current_price) * abs(position.quantity) * contract_size

                if position.avg_price > 0:
                    if position.quantity > 0:
                        position.profit_loss_ratio = (position.current_price - position.avg_price) / position.avg_price * 100
                    else:
                        position.profit_loss_ratio = (position.avg_price - position.current_price) / position.avg_price * 100
            else:
                position.market_value = Decimal('0')
                position.profit_loss = Decimal('0')
                position.profit_loss_ratio = Decimal('0')

            position.save()


class Position(models.Model):
    """持仓模型

    quantity > 0: 多头持仓
    quantity < 0: 空头持仓
    quantity = 0: 无持仓
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户', related_name='positions')
    symbol = models.ForeignKey(Symbol, on_delete=models.PROTECT, verbose_name='交易标的', related_name='positions')
    quantity = models.DecimalField('持仓数量', max_digits=15, decimal_places=4,
                                   help_text='正数为多头，负数为空头')
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
        direction = '多' if self.quantity > 0 else '空' if self.quantity < 0 else '无'
        return f"{self.account.name} - {self.symbol.code}: {direction} {abs(self.quantity)}"

    @property
    def direction(self):
        """持仓方向"""
        if self.quantity > 0:
            return 'long'
        elif self.quantity < 0:
            return 'short'
        return 'none'

    @property
    def direction_display(self):
        """持仓方向显示"""
        return {'long': '多头', 'short': '空头', 'none': '无持仓'}.get(self.direction, '未知')

    @property
    def abs_quantity(self):
        """持仓数量绝对值"""
        return abs(self.quantity)


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


class TradeReview(models.Model):
    """交易复盘模型"""
    # 情绪选项
    EMOTION_CHOICES = [
        ('calm', '冷静'),
        ('confident', '自信'),
        ('anxious', '焦虑'),
        ('fearful', '恐惧'),
        ('greedy', '贪婪'),
        ('fomo', 'FOMO'),
        ('revenge', '报复心态'),
        ('euphoric', '狂喜'),
        ('frustrated', '沮丧'),
        ('neutral', '平静'),
    ]

    # 复盘标签选项
    TAG_CHOICES = [
        ('planned', '计划内'),
        ('impulsive', '冲动交易'),
        ('overtrading', '过度交易'),
        ('early_exit', '过早离场'),
        ('late_exit', '过晚离场'),
        ('wrong_direction', '方向错误'),
        ('position_too_big', '仓位过重'),
        ('position_too_small', '仓位过轻'),
        ('missed_stop', '未执行止损'),
        ('moved_stop', '移动止损'),
        ('news_driven', '消息驱动'),
        ('technical', '技术分析'),
        ('fundamental', '基本面'),
        ('perfect', '完美执行'),
        ('lucky', '运气'),
    ]

    # 评分选项
    SCORE_CHOICES = [
        (1, '1分 - 严重失误'),
        (2, '2分 - 较差'),
        (3, '3分 - 一般'),
        (4, '4分 - 良好'),
        (5, '5分 - 优秀'),
    ]

    trade_log = models.OneToOneField(TradeLog, on_delete=models.CASCADE, verbose_name='交易记录',
                                      related_name='review')

    # 情绪记录
    emotion_before = models.CharField('交易前情绪', max_length=20, choices=EMOTION_CHOICES,
                                       blank=True, help_text='下单前的情绪状态')
    emotion_after = models.CharField('交易后情绪', max_length=20, choices=EMOTION_CHOICES,
                                      blank=True, help_text='平仓后的情绪状态')

    # 复盘标签（支持多选，用逗号分隔存储）
    tags = models.CharField('复盘标签', max_length=500, blank=True,
                           help_text='可选多个标签，用逗号分隔')

    # 评分
    execution_score = models.IntegerField('执行评分', choices=SCORE_CHOICES, null=True, blank=True,
                                          help_text='对本次交易执行的整体评分')

    # 复盘内容
    entry_reason = models.TextField('入场理由', blank=True, help_text='为什么在这个位置入场')
    exit_reason = models.TextField('出场理由', blank=True, help_text='为什么在这个位置出场')
    what_went_well = models.TextField('做得好的地方', blank=True)
    what_went_wrong = models.TextField('做得不好的地方', blank=True)
    lessons_learned = models.TextField('经验教训', blank=True, help_text='这笔交易学到了什么')
    improvement_plan = models.TextField('改进计划', blank=True, help_text='下次如何改进')

    # 市场分析
    market_condition = models.CharField('市场环境', max_length=100, blank=True,
                                        help_text='如：震荡、单边上涨、单边下跌')

    # 是否遵守交易计划
    followed_plan = models.BooleanField('是否遵守计划', null=True, blank=True,
                                        help_text='本次交易是否按照交易计划执行')

    # 时间戳
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '交易复盘'
        verbose_name_plural = '交易复盘'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.trade_log.symbol.code} 复盘 - {self.trade_log.trade_time.strftime('%Y-%m-%d')}"

    def get_tags_list(self):
        """获取标签列表"""
        if self.tags:
            return [t.strip() for t in self.tags.split(',') if t.strip()]
        return []

    def get_tags_display(self):
        """获取标签的中文显示"""
        tag_dict = dict(self.TAG_CHOICES)
        return [tag_dict.get(t, t) for t in self.get_tags_list()]

    def get_score_color(self):
        """根据评分返回颜色"""
        if not self.execution_score:
            return 'gray'
        if self.execution_score >= 4:
            return 'green'
        elif self.execution_score >= 3:
            return 'orange'
        else:
            return 'red'


class RiskRule(models.Model):
    """风险规则模型"""
    RULE_TYPE_CHOICES = [
        ('daily_loss_limit', '每日亏损限额'),
        ('single_trade_loss', '单笔亏损限额'),
        ('max_drawdown', '最大回撤'),
        ('max_position_ratio', '最大仓位比例'),
        ('consecutive_losses', '连续亏损次数'),
        ('daily_trade_limit', '每日交易次数'),
        ('max_leverage', '最大杠杆'),
    ]

    ACTION_CHOICES = [
        ('alert', '发送警告'),
        ('block', '阻止交易'),
        ('reduce', '强制减仓'),
    ]

    LEVEL_CHOICES = [
        ('warning', '警告'),
        ('danger', '危险'),
        ('critical', '严重'),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户',
                                related_name='risk_rules')
    name = models.CharField('规则名称', max_length=100)
    rule_type = models.CharField('规则类型', max_length=30, choices=RULE_TYPE_CHOICES)

    # 阈值设置
    threshold_value = models.DecimalField('阈值', max_digits=15, decimal_places=2,
                                          help_text='根据规则类型：金额、比例(%)或次数')
    threshold_percent = models.DecimalField('阈值比例', max_digits=5, decimal_places=2, null=True, blank=True,
                                            help_text='相对于账户资金的比例，如 2 表示 2%')

    # 触发后行为
    action = models.CharField('触发动作', max_length=20, choices=ACTION_CHOICES, default='alert')
    level = models.CharField('警告级别', max_length=20, choices=LEVEL_CHOICES, default='warning')

    # 状态
    is_active = models.BooleanField('是否启用', default=True)

    # 描述
    description = models.TextField('描述', blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '风险规则'
        verbose_name_plural = '风险规则'
        ordering = ['account', 'rule_type']
        unique_together = [['account', 'rule_type', 'level']]

    def __str__(self):
        return f"{self.account.name} - {self.get_rule_type_display()} ({self.get_level_display()})"

    def get_threshold_display(self):
        """获取阈值显示"""
        if self.rule_type in ['daily_loss_limit', 'single_trade_loss', 'max_drawdown']:
            if self.threshold_percent:
                return f"{self.threshold_percent}%"
            return f"¥{self.threshold_value:,.2f}"
        elif self.rule_type in ['max_position_ratio', 'max_leverage']:
            return f"{self.threshold_value}%"
        else:
            return f"{int(self.threshold_value)}次"


class RiskAlert(models.Model):
    """风险警告记录模型"""
    STATUS_CHOICES = [
        ('active', '活跃'),
        ('acknowledged', '已确认'),
        ('resolved', '已解决'),
        ('ignored', '已忽略'),
    ]

    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户',
                                related_name='risk_alerts')
    rule = models.ForeignKey(RiskRule, on_delete=models.SET_NULL, null=True, blank=True,
                            verbose_name='触发规则', related_name='alerts')
    trade_log = models.ForeignKey(TradeLog, on_delete=models.SET_NULL, null=True, blank=True,
                                  verbose_name='关联交易', related_name='risk_alerts')

    # 警告信息
    alert_type = models.CharField('警告类型', max_length=30, choices=RiskRule.RULE_TYPE_CHOICES)
    level = models.CharField('警告级别', max_length=20, choices=RiskRule.LEVEL_CHOICES)
    title = models.CharField('警告标题', max_length=200)
    message = models.TextField('警告详情')

    # 触发时的数值
    current_value = models.DecimalField('当前值', max_digits=15, decimal_places=2)
    threshold_value = models.DecimalField('阈值', max_digits=15, decimal_places=2)

    # 状态
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active')
    acknowledged_at = models.DateTimeField('确认时间', null=True, blank=True)
    resolved_at = models.DateTimeField('解决时间', null=True, blank=True)

    # 时间戳
    triggered_at = models.DateTimeField('触发时间', auto_now_add=True)

    class Meta:
        verbose_name = '风险警告'
        verbose_name_plural = '风险警告'
        ordering = ['-triggered_at']
        indexes = [
            models.Index(fields=['account', '-triggered_at']),
            models.Index(fields=['status', '-triggered_at']),
        ]

    def __str__(self):
        return f"[{self.get_level_display()}] {self.title}"

    def get_level_color(self):
        """获取级别颜色"""
        colors = {
            'warning': 'orange',
            'danger': 'red',
            'critical': 'darkred',
        }
        return colors.get(self.level, 'gray')

    def get_status_color(self):
        """获取状态颜色"""
        colors = {
            'active': 'red',
            'acknowledged': 'orange',
            'resolved': 'green',
            'ignored': 'gray',
        }
        return colors.get(self.status, 'gray')


class RiskSnapshot(models.Model):
    """风险快照模型 - 记录每日风险状态"""
    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户',
                                related_name='risk_snapshots')
    snapshot_date = models.DateField('快照日期', db_index=True)

    # 当日数据
    daily_pnl = models.DecimalField('当日盈亏', max_digits=15, decimal_places=2, default=0)
    daily_pnl_percent = models.DecimalField('当日盈亏比例', max_digits=10, decimal_places=2, default=0)
    daily_trade_count = models.IntegerField('当日交易次数', default=0)
    daily_win_count = models.IntegerField('当日盈利次数', default=0)
    daily_loss_count = models.IntegerField('当日亏损次数', default=0)

    # 连续统计
    consecutive_wins = models.IntegerField('连续盈利次数', default=0)
    consecutive_losses = models.IntegerField('连续亏损次数', default=0)

    # 回撤数据
    peak_balance = models.DecimalField('历史最高余额', max_digits=15, decimal_places=2, default=0)
    current_drawdown = models.DecimalField('当前回撤', max_digits=15, decimal_places=2, default=0)
    current_drawdown_percent = models.DecimalField('当前回撤比例', max_digits=10, decimal_places=2, default=0)
    max_drawdown = models.DecimalField('最大回撤', max_digits=15, decimal_places=2, default=0)
    max_drawdown_percent = models.DecimalField('最大回撤比例', max_digits=10, decimal_places=2, default=0)

    # 仓位数据
    total_position_value = models.DecimalField('持仓总值', max_digits=15, decimal_places=2, default=0)
    position_ratio = models.DecimalField('仓位比例', max_digits=10, decimal_places=2, default=0)

    # 风险评分
    risk_score = models.IntegerField('风险评分', default=0, help_text='0-100，越高风险越大')

    # 警告统计
    active_alerts_count = models.IntegerField('活跃警告数', default=0)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '风险快照'
        verbose_name_plural = '风险快照'
        unique_together = [['account', 'snapshot_date']]
        ordering = ['-snapshot_date']

    def __str__(self):
        return f"{self.account.name} - {self.snapshot_date} 风险快照"

    def get_risk_level(self):
        """获取风险等级"""
        if self.risk_score >= 80:
            return 'critical', '严重'
        elif self.risk_score >= 60:
            return 'danger', '危险'
        elif self.risk_score >= 40:
            return 'warning', '警告'
        else:
            return 'safe', '安全'

    def calculate_risk_score(self):
        """计算风险评分"""
        score = 0

        # 回撤评分 (最高40分)
        if self.current_drawdown_percent >= 20:
            score += 40
        elif self.current_drawdown_percent >= 10:
            score += 30
        elif self.current_drawdown_percent >= 5:
            score += 20
        elif self.current_drawdown_percent >= 2:
            score += 10

        # 连续亏损评分 (最高30分)
        if self.consecutive_losses >= 5:
            score += 30
        elif self.consecutive_losses >= 3:
            score += 20
        elif self.consecutive_losses >= 2:
            score += 10

        # 当日亏损评分 (最高20分)
        if self.daily_pnl_percent <= -5:
            score += 20
        elif self.daily_pnl_percent <= -3:
            score += 15
        elif self.daily_pnl_percent <= -1:
            score += 10

        # 仓位评分 (最高10分)
        if self.position_ratio >= 90:
            score += 10
        elif self.position_ratio >= 70:
            score += 5

        self.risk_score = min(score, 100)
        return self.risk_score


class WatchlistGroup(models.Model):
    """观察列表分组模型"""
    name = models.CharField('分组名称', max_length=50)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='所有者',
                              related_name='watchlist_groups')
    description = models.TextField('描述', blank=True)
    color = models.CharField('颜色标记', max_length=20, default='#3B82F6',
                            help_text='十六进制颜色代码，如 #3B82F6')
    sort_order = models.IntegerField('排序', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '观察分组'
        verbose_name_plural = '观察分组'
        ordering = ['sort_order', 'name']
        unique_together = [['owner', 'name']]

    def __str__(self):
        return self.name

    def items_count(self):
        return self.items.count()


class WatchlistItem(models.Model):
    """观察列表项目模型"""
    PRIORITY_CHOICES = [
        (1, '低'),
        (2, '中'),
        (3, '高'),
        (4, '紧急'),
    ]

    group = models.ForeignKey(WatchlistGroup, on_delete=models.CASCADE, verbose_name='分组',
                              related_name='items')
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE, verbose_name='标的',
                               related_name='watchlist_items')

    # 价格监控
    target_price = models.DecimalField('目标价格', max_digits=15, decimal_places=4, null=True, blank=True)
    alert_price_above = models.DecimalField('价格上破提醒', max_digits=15, decimal_places=4, null=True, blank=True)
    alert_price_below = models.DecimalField('价格下破提醒', max_digits=15, decimal_places=4, null=True, blank=True)

    # 备注
    priority = models.IntegerField('优先级', choices=PRIORITY_CHOICES, default=2)
    notes = models.TextField('备注', blank=True)
    tags = models.CharField('标签', max_length=200, blank=True, help_text='用逗号分隔多个标签')

    # 状态
    is_active = models.BooleanField('是否活跃', default=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '观察项目'
        verbose_name_plural = '观察项目'
        ordering = ['-priority', '-updated_at']
        unique_together = [['group', 'symbol']]

    def __str__(self):
        return f"{self.group.name} - {self.symbol.code}"

    def get_tags_list(self):
        if self.tags:
            return [t.strip() for t in self.tags.split(',') if t.strip()]
        return []


class TradePlan(models.Model):
    """交易计划模型"""
    PLAN_TYPE_CHOICES = [
        ('daily', '日计划'),
        ('weekly', '周计划'),
        ('swing', '波段计划'),
        ('position', '持仓计划'),
    ]

    DIRECTION_CHOICES = [
        ('long', '做多'),
        ('short', '做空'),
        ('both', '双向'),
    ]

    STATUS_CHOICES = [
        ('draft', '草稿'),
        ('pending', '待执行'),
        ('partial', '部分执行'),
        ('executed', '已执行'),
        ('cancelled', '已取消'),
        ('expired', '已过期'),
    ]

    # 基本信息
    account = models.ForeignKey(Account, on_delete=models.CASCADE, verbose_name='账户',
                                related_name='trade_plans')
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE, verbose_name='标的',
                               related_name='trade_plans')
    strategy = models.ForeignKey(Strategy, on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name='策略', related_name='trade_plans')

    # 计划类型
    plan_type = models.CharField('计划类型', max_length=20, choices=PLAN_TYPE_CHOICES, default='daily')
    direction = models.CharField('方向', max_length=10, choices=DIRECTION_CHOICES, default='long')

    # 计划时间
    plan_date = models.DateField('计划日期', db_index=True)
    valid_until = models.DateField('有效期至', null=True, blank=True,
                                   help_text='留空表示仅当日有效')

    # 入场计划
    entry_price_min = models.DecimalField('入场价下限', max_digits=15, decimal_places=4)
    entry_price_max = models.DecimalField('入场价上限', max_digits=15, decimal_places=4)
    entry_condition = models.TextField('入场条件', blank=True,
                                       help_text='描述满足什么条件时入场')

    # 出场计划
    stop_loss = models.DecimalField('止损价', max_digits=15, decimal_places=4)
    take_profit_1 = models.DecimalField('止盈1', max_digits=15, decimal_places=4, null=True, blank=True)
    take_profit_2 = models.DecimalField('止盈2', max_digits=15, decimal_places=4, null=True, blank=True)
    take_profit_3 = models.DecimalField('止盈3', max_digits=15, decimal_places=4, null=True, blank=True)
    exit_condition = models.TextField('出场条件', blank=True,
                                      help_text='描述满足什么条件时出场')

    # 仓位管理
    planned_quantity = models.DecimalField('计划数量', max_digits=15, decimal_places=4)
    max_risk_amount = models.DecimalField('最大风险金额', max_digits=15, decimal_places=2,
                                          help_text='本计划允许的最大亏损')
    position_size_percent = models.DecimalField('仓位比例', max_digits=5, decimal_places=2, null=True, blank=True,
                                                help_text='占账户资金的百分比')

    # 分析理由
    analysis = models.TextField('分析理由', blank=True, help_text='技术面/基本面分析')
    key_levels = models.CharField('关键价位', max_length=200, blank=True,
                                  help_text='支撑位/阻力位，用逗号分隔')

    # 状态
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='draft')

    # 执行记录
    executed_trade = models.ForeignKey(TradeLog, on_delete=models.SET_NULL, null=True, blank=True,
                                       verbose_name='执行交易', related_name='from_plan')
    executed_at = models.DateTimeField('执行时间', null=True, blank=True)
    execution_notes = models.TextField('执行备注', blank=True)

    # 时间戳
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '交易计划'
        verbose_name_plural = '交易计划'
        ordering = ['-plan_date', '-created_at']
        indexes = [
            models.Index(fields=['account', '-plan_date']),
            models.Index(fields=['status', '-plan_date']),
        ]

    def __str__(self):
        return f"{self.plan_date} {self.symbol.code} {self.get_direction_display()}"

    @property
    def risk_reward_ratio(self):
        """计算盈亏比"""
        entry_mid = (self.entry_price_min + self.entry_price_max) / 2
        risk = abs(entry_mid - self.stop_loss)
        if risk == 0:
            return None
        if self.take_profit_1:
            reward = abs(self.take_profit_1 - entry_mid)
            return round(reward / risk, 2)
        return None

    @property
    def is_valid(self):
        """检查计划是否仍然有效"""
        from django.utils import timezone
        today = timezone.now().date()
        if self.status in ['executed', 'cancelled', 'expired']:
            return False
        if self.valid_until:
            return today <= self.valid_until
        return today == self.plan_date

    def get_key_levels_list(self):
        """获取关键价位列表"""
        if self.key_levels:
            return [l.strip() for l in self.key_levels.split(',') if l.strip()]
        return []

    def calculate_position_size(self):
        """根据风险金额计算仓位"""
        entry_mid = (self.entry_price_min + self.entry_price_max) / 2
        risk_per_unit = abs(entry_mid - self.stop_loss)
        if risk_per_unit > 0 and self.max_risk_amount:
            # 考虑合约乘数
            if self.symbol.symbol_type in ['futures', 'index']:
                risk_per_unit *= self.symbol.contract_size
            return self.max_risk_amount / risk_per_unit
        return 0

    def mark_executed(self, trade_log):
        """标记为已执行"""
        from django.utils import timezone
        self.status = 'executed'
        self.executed_trade = trade_log
        self.executed_at = timezone.now()
        self.save()


class DailyNote(models.Model):
    """每日交易笔记模型"""
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户',
                              related_name='daily_notes')
    note_date = models.DateField('日期', db_index=True)

    # 盘前计划
    pre_market_plan = models.TextField('盘前计划', blank=True,
                                       help_text='今日交易计划、关注标的、重要事件')
    market_outlook = models.CharField('市场展望', max_length=20, blank=True,
                                      choices=[('bullish', '看多'), ('bearish', '看空'),
                                              ('neutral', '中性'), ('uncertain', '不确定')])
    focus_sectors = models.CharField('关注板块', max_length=200, blank=True)
    key_events = models.TextField('重要事件', blank=True, help_text='财报、经济数据、政策等')

    # 盘后总结
    post_market_summary = models.TextField('盘后总结', blank=True)
    lessons_learned = models.TextField('经验教训', blank=True)
    mood = models.CharField('今日心情', max_length=20, blank=True,
                           choices=[('great', '很好'), ('good', '不错'),
                                   ('normal', '一般'), ('bad', '不好'), ('terrible', '很差')])

    # 统计（可选，也可从其他表聚合）
    planned_trades = models.IntegerField('计划交易数', default=0)
    executed_trades = models.IntegerField('执行交易数', default=0)
    followed_plan_count = models.IntegerField('遵守计划数', default=0)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '每日笔记'
        verbose_name_plural = '每日笔记'
        unique_together = [['owner', 'note_date']]
        ordering = ['-note_date']

    def __str__(self):
        return f"{self.note_date} 交易笔记"

    @property
    def plan_execution_rate(self):
        """计划执行率"""
        if self.planned_trades > 0:
            return round(self.executed_trades / self.planned_trades * 100, 1)
        return 0


class Notification(models.Model):
    """通知消息模型"""
    NOTIFICATION_TYPE_CHOICES = [
        ('price_alert', '价格提醒'),
        ('plan_reminder', '计划提醒'),
        ('risk_warning', '风险警告'),
        ('daily_summary', '每日总结'),
        ('trade_executed', '交易执行'),
        ('system', '系统通知'),
    ]

    PRIORITY_CHOICES = [
        ('low', '低'),
        ('normal', '普通'),
        ('high', '高'),
        ('urgent', '紧急'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户',
                              related_name='notifications')
    notification_type = models.CharField('通知类型', max_length=20, choices=NOTIFICATION_TYPE_CHOICES)
    priority = models.CharField('优先级', max_length=20, choices=PRIORITY_CHOICES, default='normal')

    title = models.CharField('标题', max_length=200)
    message = models.TextField('内容')

    # 关联对象（可选）
    related_symbol = models.ForeignKey('Symbol', on_delete=models.SET_NULL, null=True, blank=True,
                                       verbose_name='相关标的', related_name='notifications')
    related_trade = models.ForeignKey('TradeLog', on_delete=models.SET_NULL, null=True, blank=True,
                                      verbose_name='相关交易', related_name='notifications')
    related_plan = models.ForeignKey('TradePlan', on_delete=models.SET_NULL, null=True, blank=True,
                                     verbose_name='相关计划', related_name='notifications')
    related_alert = models.ForeignKey('RiskAlert', on_delete=models.SET_NULL, null=True, blank=True,
                                      verbose_name='相关警告', related_name='notifications')

    # 额外数据（JSON格式存储）
    extra_data = models.JSONField('额外数据', default=dict, blank=True)

    # 状态
    is_read = models.BooleanField('是否已读', default=False)
    read_at = models.DateTimeField('阅读时间', null=True, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '通知消息'
        verbose_name_plural = '通知消息'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner', '-created_at']),
            models.Index(fields=['owner', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.get_notification_type_display()}] {self.title}"

    def mark_as_read(self):
        """标记为已读"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def get_icon(self):
        """获取通知图标类"""
        icons = {
            'price_alert': 'fa-bell',
            'plan_reminder': 'fa-clipboard-list',
            'risk_warning': 'fa-exclamation-triangle',
            'daily_summary': 'fa-calendar-check',
            'trade_executed': 'fa-exchange-alt',
            'system': 'fa-info-circle',
        }
        return icons.get(self.notification_type, 'fa-bell')

    def get_color(self):
        """获取通知颜色"""
        colors = {
            'price_alert': 'blue',
            'plan_reminder': 'purple',
            'risk_warning': 'red',
            'daily_summary': 'green',
            'trade_executed': 'emerald',
            'system': 'gray',
        }
        return colors.get(self.notification_type, 'gray')


class PriceAlert(models.Model):
    """价格提醒模型"""
    CONDITION_CHOICES = [
        ('above', '高于'),
        ('below', '低于'),
        ('cross_up', '向上穿越'),
        ('cross_down', '向下穿越'),
    ]

    STATUS_CHOICES = [
        ('active', '监控中'),
        ('triggered', '已触发'),
        ('cancelled', '已取消'),
        ('expired', '已过期'),
    ]

    ALERT_TYPE_CHOICES = [
        ('price', '价格提醒'),
        ('stop_loss', '止损提醒'),
        ('take_profit', '止盈提醒'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户',
                              related_name='price_alerts')
    symbol = models.ForeignKey('Symbol', on_delete=models.CASCADE, verbose_name='标的',
                               related_name='price_alerts')
    position = models.ForeignKey('Position', on_delete=models.SET_NULL, verbose_name='关联持仓',
                                 related_name='alerts', null=True, blank=True)
    alert_type = models.CharField('提醒类型', max_length=20, choices=ALERT_TYPE_CHOICES, default='price')

    condition = models.CharField('条件', max_length=20, choices=CONDITION_CHOICES)
    target_price = models.DecimalField('目标价格', max_digits=15, decimal_places=4)

    # 可选：设置有效期
    valid_until = models.DateTimeField('有效期至', null=True, blank=True)

    # 触发设置
    trigger_once = models.BooleanField('仅触发一次', default=True,
                                       help_text='触发后自动取消，否则会重复提醒')

    notes = models.CharField('备注', max_length=200, blank=True)

    # 状态
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active')
    last_price = models.DecimalField('最后检查价格', max_digits=15, decimal_places=4,
                                     null=True, blank=True)
    triggered_at = models.DateTimeField('触发时间', null=True, blank=True)
    trigger_count = models.IntegerField('触发次数', default=0)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '价格提醒'
        verbose_name_plural = '价格提醒'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.symbol.code} {self.get_condition_display()} {self.target_price}"

    def check_condition(self, current_price):
        """检查是否满足触发条件"""
        if self.status != 'active':
            return False

        # 检查有效期
        if self.valid_until and timezone.now() > self.valid_until:
            self.status = 'expired'
            self.save(update_fields=['status'])
            return False

        triggered = False

        if self.condition == 'above':
            triggered = current_price >= self.target_price
        elif self.condition == 'below':
            triggered = current_price <= self.target_price
        elif self.condition == 'cross_up':
            # 向上穿越：之前低于目标价，现在高于
            if self.last_price and self.last_price < self.target_price <= current_price:
                triggered = True
        elif self.condition == 'cross_down':
            # 向下穿越：之前高于目标价，现在低于
            if self.last_price and self.last_price > self.target_price >= current_price:
                triggered = True

        # 更新最后价格
        self.last_price = current_price
        self.save(update_fields=['last_price'])

        return triggered

    def trigger(self):
        """触发提醒"""
        self.triggered_at = timezone.now()
        self.trigger_count += 1

        if self.trigger_once:
            self.status = 'triggered'

        self.save(update_fields=['triggered_at', 'trigger_count', 'status'])

        # 创建通知
        Notification.objects.create(
            owner=self.owner,
            notification_type='price_alert',
            priority='high',
            title=f'价格提醒: {self.symbol.code}',
            message=f'{self.symbol.name} 当前价格 {self.last_price} {self.get_condition_display()} {self.target_price}',
            related_symbol=self.symbol,
            extra_data={
                'target_price': str(self.target_price),
                'current_price': str(self.last_price),
                'condition': self.condition,
            }
        )


class TradeTag(models.Model):
    """交易标签模型"""
    TAG_CATEGORY_CHOICES = [
        ('entry', '入场类型'),
        ('exit', '出场类型'),
        ('market', '市场环境'),
        ('pattern', '形态'),
        ('custom', '自定义'),
    ]

    name = models.CharField('标签名称', max_length=50)
    category = models.CharField('标签分类', max_length=20, choices=TAG_CATEGORY_CHOICES, default='custom')
    color = models.CharField('颜色', max_length=20, default='#3B82F6', help_text='十六进制颜色代码')
    description = models.CharField('描述', max_length=200, blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='所有者',
                              related_name='trade_tags')
    is_system = models.BooleanField('系统标签', default=False, help_text='系统预设标签')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '交易标签'
        verbose_name_plural = '交易标签'
        unique_together = [['owner', 'name']]
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class NotificationSetting(models.Model):
    """通知设置模型"""
    owner = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name='用户',
                                  related_name='notification_setting')

    # 通知开关
    enable_price_alert = models.BooleanField('价格提醒', default=True)
    enable_plan_reminder = models.BooleanField('计划提醒', default=True)
    enable_risk_warning = models.BooleanField('风险警告', default=True)
    enable_daily_summary = models.BooleanField('每日总结', default=True)
    enable_trade_notification = models.BooleanField('交易通知', default=True)

    # 提醒时间
    daily_summary_time = models.TimeField('每日总结提醒时间', default='20:00')
    plan_reminder_minutes = models.IntegerField('计划提前提醒(分钟)', default=30)

    # 静默时段
    quiet_hours_start = models.TimeField('静默开始时间', null=True, blank=True)
    quiet_hours_end = models.TimeField('静默结束时间', null=True, blank=True)

    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '通知设置'
        verbose_name_plural = '通知设置'

    def __str__(self):
        return f"{self.owner.username} 的通知设置"

    def is_quiet_hours(self):
        """检查当前是否在静默时段"""
        if not self.quiet_hours_start or not self.quiet_hours_end:
            return False

        now = timezone.now().time()

        if self.quiet_hours_start <= self.quiet_hours_end:
            # 同一天内的静默时段
            return self.quiet_hours_start <= now <= self.quiet_hours_end
        else:
            # 跨天的静默时段（如 22:00 - 08:00）
            return now >= self.quiet_hours_start or now <= self.quiet_hours_end


class Webhook(models.Model):
    """Webhook配置模型"""
    WEBHOOK_TYPE_CHOICES = [
        ('inbound', '接收信号'),
        ('outbound', '发送通知'),
    ]

    STATUS_CHOICES = [
        ('active', '启用'),
        ('inactive', '停用'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户',
                              related_name='webhooks')
    name = models.CharField('名称', max_length=100)
    webhook_type = models.CharField('类型', max_length=20, choices=WEBHOOK_TYPE_CHOICES)
    url = models.URLField('URL地址', blank=True, help_text='outbound类型需要填写')
    secret_key = models.CharField('密钥', max_length=64, unique=True)
    status = models.CharField('状态', max_length=20, choices=STATUS_CHOICES, default='active')
    description = models.TextField('描述', blank=True)
    last_triggered = models.DateTimeField('最后触发时间', null=True, blank=True)
    trigger_count = models.IntegerField('触发次数', default=0)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = 'Webhook'
        verbose_name_plural = 'Webhook'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_webhook_type_display()})"

    def save(self, *args, **kwargs):
        if not self.secret_key:
            import secrets
            self.secret_key = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)


class WebhookLog(models.Model):
    """Webhook日志"""
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, verbose_name='Webhook',
                                related_name='logs')
    direction = models.CharField('方向', max_length=10)  # in/out
    payload = models.JSONField('数据', default=dict)
    response_code = models.IntegerField('响应码', null=True, blank=True)
    success = models.BooleanField('成功', default=False)
    error_message = models.TextField('错误信息', blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = 'Webhook日志'
        verbose_name_plural = 'Webhook日志'
        ordering = ['-created_at']


class ScheduledReport(models.Model):
    """定时报告配置"""
    FREQUENCY_CHOICES = [
        ('daily', '每日'),
        ('weekly', '每周'),
        ('monthly', '每月'),
    ]

    REPORT_TYPE_CHOICES = [
        ('trade_summary', '交易总结'),
        ('performance', '绩效报告'),
        ('risk_report', '风险报告'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户',
                              related_name='scheduled_reports')
    name = models.CharField('报告名称', max_length=100)
    report_type = models.CharField('报告类型', max_length=20, choices=REPORT_TYPE_CHOICES)
    frequency = models.CharField('频率', max_length=20, choices=FREQUENCY_CHOICES)
    send_time = models.TimeField('发送时间', default='08:00')
    send_day = models.IntegerField('发送日', default=1, help_text='每周几(1-7)或每月几号(1-31)')
    email = models.EmailField('接收邮箱')
    is_active = models.BooleanField('启用', default=True)
    last_sent = models.DateTimeField('最后发送时间', null=True, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '定时报告'
        verbose_name_plural = '定时报告'

    def __str__(self):
        return f"{self.name} ({self.get_frequency_display()})"


class StrategySignal(models.Model):
    """策略信号记录"""
    SIGNAL_TYPE_CHOICES = [
        ('buy', '买入信号'),
        ('sell', '卖出信号'),
        ('hold', '持有'),
    ]

    SOURCE_CHOICES = [
        ('backtest', '回测'),
        ('live', '实盘'),
        ('webhook', 'Webhook'),
    ]

    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name='用户',
                              related_name='strategy_signals')
    strategy_name = models.CharField('策略名称', max_length=100)
    symbol = models.CharField('标的代码', max_length=20)
    signal_type = models.CharField('信号类型', max_length=10, choices=SIGNAL_TYPE_CHOICES)
    source = models.CharField('来源', max_length=20, choices=SOURCE_CHOICES)
    price = models.DecimalField('信号价格', max_digits=12, decimal_places=4, null=True, blank=True)
    quantity = models.IntegerField('建议数量', null=True, blank=True)
    reason = models.TextField('信号原因', blank=True)
    extra_data = models.JSONField('附加数据', default=dict)
    is_notified = models.BooleanField('已通知', default=False)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)

    class Meta:
        verbose_name = '策略信号'
        verbose_name_plural = '策略信号'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.strategy_name} - {self.symbol} {self.get_signal_type_display()}"


class UserPreference(models.Model):
    """用户偏好设置"""
    THEME_CHOICES = [
        ('light', '浅色'),
        ('dark', '深色'),
        ('auto', '跟随系统'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name='用户',
                                related_name='preference')
    theme = models.CharField('主题', max_length=10, choices=THEME_CHOICES, default='light')
    dashboard_layout = models.JSONField('仪表盘布局', default=dict,
                                        help_text='存储用户自定义的仪表盘模块配置')
    shortcuts_enabled = models.BooleanField('启用快捷键', default=True)
    sidebar_collapsed = models.BooleanField('侧边栏收起', default=False)
    notification_sound = models.BooleanField('通知声音', default=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '用户偏好'
        verbose_name_plural = '用户偏好'

    def __str__(self):
        return f"{self.user.username} 的偏好设置"

    @classmethod
    def get_default_layout(cls):
        """默认仪表盘布局"""
        return {
            'modules': [
                {'id': 'overview', 'name': '数据概览', 'enabled': True, 'order': 1},
                {'id': 'pnl_chart', 'name': '盈亏趋势', 'enabled': True, 'order': 2},
                {'id': 'monthly_chart', 'name': '月度盈亏', 'enabled': True, 'order': 3},
                {'id': 'distribution', 'name': '账户分布', 'enabled': True, 'order': 4},
                {'id': 'recent_trades', 'name': '最近交易', 'enabled': True, 'order': 5},
                {'id': 'positions', 'name': '当前持仓', 'enabled': False, 'order': 6},
                {'id': 'alerts', 'name': '价格提醒', 'enabled': False, 'order': 7},
                {'id': 'signals', 'name': '策略信号', 'enabled': False, 'order': 8},
            ]
        }