from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal
from datetime import date
from .models import TradeLog, AccountTransaction, DailyReport, RiskRule, RiskAlert, RiskSnapshot, Position
import logging

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=TradeLog)
def auto_calculate_trade_fields(sender, instance, **kwargs):
    """
    交易保存前自动计算:
    1. 自动计算手续费（基于Symbol配置）
    2. 设置成交价（如果未设置）
    """
    # 如果未设置成交价，使用下单价
    if not instance.executed_price and instance.price:
        instance.executed_price = instance.price

    # 自动计算手续费（如果未设置且状态为已成交）
    if instance.status == 'filled' and instance.commission == 0 and instance.symbol:
        try:
            instance.commission = instance.symbol.calculate_commission(
                instance.executed_price or instance.price,
                instance.quantity
            )
            logger.info(f"Auto-calculated commission for {instance.symbol.code}: {instance.commission}")
        except Exception as e:
            logger.warning(f"Failed to auto-calculate commission: {e}")


@receiver(post_save, sender=TradeLog)
def sync_position_on_trade(sender, instance, created, **kwargs):
    """
    交易保存后自动同步持仓
    """
    if instance.status != 'filled':
        return

    try:
        with transaction.atomic():
            # 获取或创建持仓
            position, pos_created = Position.objects.get_or_create(
                account=instance.account,
                symbol=instance.symbol,
                defaults={
                    'quantity': Decimal('0'),
                    'avg_price': Decimal('0'),
                    'current_price': instance.executed_price or instance.price,
                    'market_value': Decimal('0'),
                    'profit_loss': Decimal('0'),
                    'profit_loss_ratio': Decimal('0'),
                }
            )

            executed_price = instance.executed_price or instance.price
            qty = instance.quantity

            if instance.side == 'buy':
                # 买入：增加持仓
                if position.quantity > 0:
                    # 已有多头持仓，计算新均价
                    total_cost = position.avg_price * position.quantity + executed_price * qty
                    new_qty = position.quantity + qty
                    position.avg_price = total_cost / new_qty
                    position.quantity = new_qty
                elif position.quantity < 0:
                    # 有空头持仓，先平仓再开仓
                    if qty <= abs(position.quantity):
                        # 部分平空
                        position.quantity += qty
                    else:
                        # 平空后反手做多
                        remaining = qty - abs(position.quantity)
                        position.quantity = remaining
                        position.avg_price = executed_price
                else:
                    # 新开多仓
                    position.quantity = qty
                    position.avg_price = executed_price
            else:  # sell
                # 卖出：减少持仓
                if position.quantity > 0:
                    # 有多头持仓
                    if qty <= position.quantity:
                        # 部分平多
                        position.quantity -= qty
                    else:
                        # 平多后反手做空（期货）
                        if instance.symbol.symbol_type in ['futures', 'forex', 'crypto']:
                            remaining = qty - position.quantity
                            position.quantity = -remaining
                            position.avg_price = executed_price
                        else:
                            # 股票不能做空，设为0
                            position.quantity = Decimal('0')
                elif position.quantity < 0:
                    # 已有空头持仓，继续做空
                    total_cost = abs(position.avg_price * position.quantity) + executed_price * qty
                    new_qty = abs(position.quantity) + qty
                    position.avg_price = total_cost / new_qty
                    position.quantity = -new_qty
                else:
                    # 新开空仓（仅期货）
                    if instance.symbol.symbol_type in ['futures', 'forex', 'crypto']:
                        position.quantity = -qty
                        position.avg_price = executed_price

            # 更新当前价格
            position.current_price = executed_price

            # 更新市值和盈亏
            update_position_value(position)

            position.save()
            logger.info(f"Position synced: {instance.account.name} - {instance.symbol.code}, "
                       f"qty={position.quantity}, avg={position.avg_price}")

    except Exception as e:
        logger.error(f"Failed to sync position: {e}")


def update_position_value(position):
    """更新持仓市值和盈亏"""
    if position.quantity == 0:
        position.market_value = Decimal('0')
        position.profit_loss = Decimal('0')
        position.profit_loss_ratio = Decimal('0')
        return

    # 计算市值
    position.market_value = abs(position.quantity) * (position.current_price or position.avg_price)

    # 计算盈亏
    if position.avg_price > 0 and position.current_price:
        if position.quantity > 0:
            # 多头盈亏
            price_diff = position.current_price - position.avg_price
        else:
            # 空头盈亏
            price_diff = position.avg_price - position.current_price

        # 考虑合约乘数
        if position.symbol.symbol_type in ['futures', 'index']:
            position.profit_loss = price_diff * abs(position.quantity) * position.symbol.contract_size
        else:
            position.profit_loss = price_diff * abs(position.quantity)

        # 盈亏比例
        position.profit_loss_ratio = (price_diff / position.avg_price) * 100


@receiver(post_save, sender=TradeLog)
def process_trade_log(sender, instance, created, **kwargs):
    """
    交易日志保存后自动处理：
    1. 创建账户流水记录
    2. 更新账户余额
    3. 更新或创建每日报表
    4. 检查风险规则
    """
    # 只处理已成交的交易
    if instance.status != 'filled':
        return

    # 使用数据库事务确保数据一致性
    with transaction.atomic():
        # 1. 计算交易影响的金额
        trade_amount = calculate_trade_amount(instance)

        # 2. 创建账户流水记录
        create_account_transactions(instance, trade_amount)

        # 3. 更新账户余额
        update_account_balance(instance.account, trade_amount)

        # 4. 更新每日报表
        update_daily_report(instance)

        # 5. 检查风险规则并触发警告
        check_risk_rules(instance)


def calculate_trade_amount(trade_log):
    """
    计算交易对账户余额的影响
    返回: {
        'profit_loss': Decimal,  # 盈亏金额
        'commission': Decimal,   # 手续费
        'net_amount': Decimal    # 净金额变动
    }
    """
    profit_loss = trade_log.profit_loss or Decimal('0')
    commission = trade_log.commission or Decimal('0')

    # 买入：减少余额（支付金额 + 手续费）
    # 卖出：增加余额（收到金额 - 手续费）
    if trade_log.side == 'buy':
        # 买入时，支付交易金额和手续费
        trade_value = trade_log.quantity * (trade_log.executed_price or trade_log.price)
        net_amount = -(trade_value + commission)
    else:  # sell
        # 卖出时，收到交易金额，扣除手续费，加上盈亏
        trade_value = trade_log.quantity * (trade_log.executed_price or trade_log.price)
        net_amount = trade_value - commission + profit_loss

    return {
        'profit_loss': profit_loss,
        'commission': commission,
        'net_amount': net_amount
    }


def create_account_transactions(trade_log, trade_amount):
    """创建账户流水记录"""
    account = trade_log.account
    balance_before = account.current_balance

    # 创建盈亏流水（如果有盈亏）
    if trade_amount['profit_loss'] != 0:
        transaction_type = 'trade_profit' if trade_amount['profit_loss'] > 0 else 'trade_loss'
        AccountTransaction.objects.create(
            account=account,
            transaction_type=transaction_type,
            amount=trade_amount['profit_loss'],
            balance_before=balance_before,
            balance_after=balance_before + trade_amount['profit_loss'],
            trade_log=trade_log,
            description=f"{trade_log.symbol.code} {trade_log.get_side_display()}",
            transaction_time=trade_log.trade_time
        )
        balance_before += trade_amount['profit_loss']

    # 创建手续费流水（如果有手续费）
    if trade_amount['commission'] != 0:
        AccountTransaction.objects.create(
            account=account,
            transaction_type='commission',
            amount=-trade_amount['commission'],
            balance_before=balance_before,
            balance_after=balance_before - trade_amount['commission'],
            trade_log=trade_log,
            description=f"{trade_log.symbol.code} 手续费",
            transaction_time=trade_log.trade_time
        )


def update_account_balance(account, trade_amount):
    """更新账户余额"""
    account.current_balance += trade_amount['net_amount']
    account.available_balance = account.current_balance  # 简化处理，实际可能需要考虑持仓占用
    account.save(update_fields=['current_balance', 'available_balance', 'updated_at'])


def update_daily_report(trade_log):
    """更新或创建每日报表"""
    account = trade_log.account
    report_date = trade_log.trade_time.date()

    # 获取或创建当日报表
    report, created = DailyReport.objects.get_or_create(
        account=account,
        report_date=report_date,
        defaults={
            'starting_balance': get_starting_balance(account, report_date),
            'ending_balance': account.current_balance,
            'net_deposit': Decimal('0'),
            'profit_loss': Decimal('0'),
            'profit_loss_ratio': Decimal('0'),
            'trade_count': 0,
            'win_count': 0,
            'loss_count': 0,
            'win_rate': Decimal('0'),
            'max_drawdown': Decimal('0'),
            'commission': Decimal('0'),
        }
    )

    # 重新计算当日所有交易的统计数据
    recalculate_daily_report(report)


def get_starting_balance(account, report_date):
    """获取指定日期的期初余额"""
    # 查找前一天的报表
    previous_report = DailyReport.objects.filter(
        account=account,
        report_date__lt=report_date
    ).order_by('-report_date').first()

    if previous_report:
        return previous_report.ending_balance
    else:
        return account.initial_balance


def recalculate_daily_report(report):
    """重新计算每日报表的所有统计数据"""
    account = report.account
    report_date = report.report_date

    # 获取当日所有已成交的交易
    trades = TradeLog.objects.filter(
        account=account,
        trade_time__date=report_date,
        status='filled'
    )

    # 统计数据
    trade_count = trades.count()
    total_profit_loss = sum(t.profit_loss or Decimal('0') for t in trades)
    total_commission = sum(t.commission or Decimal('0') for t in trades)

    # 盈利和亏损次数
    win_count = trades.filter(profit_loss__gt=0).count()
    loss_count = trades.filter(profit_loss__lt=0).count()
    win_rate = (win_count / trade_count * 100) if trade_count > 0 else Decimal('0')

    # 更新报表
    report.ending_balance = account.current_balance
    report.profit_loss = total_profit_loss
    report.profit_loss_ratio = (
        (total_profit_loss / report.starting_balance * 100)
        if report.starting_balance > 0 else Decimal('0')
    )
    report.trade_count = trade_count
    report.win_count = win_count
    report.loss_count = loss_count
    report.win_rate = win_rate
    report.commission = total_commission

    report.save()


def check_risk_rules(trade_log):
    """检查风险规则并触发警告"""
    account = trade_log.account
    rules = RiskRule.objects.filter(account=account, is_active=True)

    for rule in rules:
        check_single_rule(rule, trade_log)

    # 更新风险快照
    update_risk_snapshot(account)


def check_single_rule(rule, trade_log):
    """检查单条风险规则"""
    account = rule.account
    today = trade_log.trade_time.date()
    triggered = False
    current_value = Decimal('0')
    message = ''

    if rule.rule_type == 'daily_loss_limit':
        # 检查每日亏损限额
        daily_pnl = get_daily_pnl(account, today)
        threshold = get_threshold_value(rule, account)
        if daily_pnl < 0 and abs(daily_pnl) >= threshold:
            triggered = True
            current_value = abs(daily_pnl)
            message = f"当日亏损 ¥{abs(daily_pnl):.2f} 已达到限额 ¥{threshold:.2f}"

    elif rule.rule_type == 'single_trade_loss':
        # 检查单笔亏损
        if trade_log.profit_loss and trade_log.profit_loss < 0:
            threshold = get_threshold_value(rule, account)
            loss = abs(trade_log.profit_loss)
            if loss >= threshold:
                triggered = True
                current_value = loss
                message = f"单笔交易亏损 ¥{loss:.2f} 超过限额 ¥{threshold:.2f}"

    elif rule.rule_type == 'consecutive_losses':
        # 检查连续亏损次数
        consecutive = get_consecutive_losses(account)
        threshold = int(rule.threshold_value)
        if consecutive >= threshold:
            triggered = True
            current_value = Decimal(str(consecutive))
            message = f"已连续亏损 {consecutive} 次，达到警戒线 {threshold} 次"

    elif rule.rule_type == 'daily_trade_limit':
        # 检查每日交易次数
        trade_count = get_daily_trade_count(account, today)
        threshold = int(rule.threshold_value)
        if trade_count >= threshold:
            triggered = True
            current_value = Decimal(str(trade_count))
            message = f"当日交易 {trade_count} 次，已达到限制 {threshold} 次"

    elif rule.rule_type == 'max_drawdown':
        # 检查最大回撤
        drawdown_percent = get_current_drawdown_percent(account)
        threshold = rule.threshold_percent or rule.threshold_value
        if drawdown_percent >= threshold:
            triggered = True
            current_value = drawdown_percent
            message = f"当前回撤 {drawdown_percent:.2f}% 已达到警戒线 {threshold:.2f}%"

    if triggered:
        create_risk_alert(rule, trade_log, current_value, message)


def get_threshold_value(rule, account):
    """获取阈值（支持百分比和固定值）"""
    if rule.threshold_percent:
        return account.current_balance * rule.threshold_percent / 100
    return rule.threshold_value


def get_daily_pnl(account, today):
    """获取当日盈亏"""
    from django.db.models import Sum
    result = TradeLog.objects.filter(
        account=account,
        trade_time__date=today,
        status='filled'
    ).aggregate(total=Sum('profit_loss'))
    return result['total'] or Decimal('0')


def get_daily_trade_count(account, today):
    """获取当日交易次数"""
    return TradeLog.objects.filter(
        account=account,
        trade_time__date=today,
        status='filled'
    ).count()


def get_consecutive_losses(account):
    """获取连续亏损次数"""
    trades = TradeLog.objects.filter(
        account=account,
        status='filled'
    ).order_by('-trade_time')[:20]  # 检查最近20笔

    consecutive = 0
    for trade in trades:
        if trade.profit_loss and trade.profit_loss < 0:
            consecutive += 1
        else:
            break
    return consecutive


def get_current_drawdown_percent(account):
    """获取当前回撤百分比"""
    # 获取历史最高余额
    from .models import RiskSnapshot
    snapshots = RiskSnapshot.objects.filter(account=account).order_by('-peak_balance')
    if snapshots.exists():
        peak = snapshots.first().peak_balance
    else:
        peak = account.initial_balance

    peak = max(peak, account.initial_balance)
    if peak <= 0:
        return Decimal('0')

    current = account.current_balance
    if current >= peak:
        return Decimal('0')

    drawdown_percent = (peak - current) / peak * 100
    return drawdown_percent


def create_risk_alert(rule, trade_log, current_value, message):
    """创建风险警告"""
    # 检查是否已有相同的活跃警告（避免重复）
    existing = RiskAlert.objects.filter(
        account=rule.account,
        rule=rule,
        status='active',
        triggered_at__date=trade_log.trade_time.date()
    ).exists()

    if existing:
        return

    RiskAlert.objects.create(
        account=rule.account,
        rule=rule,
        trade_log=trade_log,
        alert_type=rule.rule_type,
        level=rule.level,
        title=f"[{rule.get_level_display()}] {rule.name}",
        message=message,
        current_value=current_value,
        threshold_value=rule.threshold_value
    )


def update_risk_snapshot(account):
    """更新或创建风险快照"""
    today = date.today()

    # 获取或创建今日快照
    snapshot, created = RiskSnapshot.objects.get_or_create(
        account=account,
        snapshot_date=today,
        defaults={'peak_balance': account.current_balance}
    )

    # 获取当日数据
    today_trades = TradeLog.objects.filter(
        account=account,
        trade_time__date=today,
        status='filled'
    )

    from django.db.models import Sum
    daily_pnl = today_trades.aggregate(total=Sum('profit_loss'))['total'] or Decimal('0')

    # 更新快照数据
    snapshot.daily_pnl = daily_pnl
    if account.current_balance > 0:
        snapshot.daily_pnl_percent = daily_pnl / account.current_balance * 100
    snapshot.daily_trade_count = today_trades.count()
    snapshot.daily_win_count = today_trades.filter(profit_loss__gt=0).count()
    snapshot.daily_loss_count = today_trades.filter(profit_loss__lt=0).count()

    # 连续统计
    snapshot.consecutive_losses = get_consecutive_losses(account)
    if snapshot.consecutive_losses == 0:
        # 计算连续盈利
        trades = TradeLog.objects.filter(
            account=account,
            status='filled'
        ).order_by('-trade_time')[:20]
        consecutive_wins = 0
        for trade in trades:
            if trade.profit_loss and trade.profit_loss > 0:
                consecutive_wins += 1
            else:
                break
        snapshot.consecutive_wins = consecutive_wins
    else:
        snapshot.consecutive_wins = 0

    # 更新峰值
    if account.current_balance > snapshot.peak_balance:
        snapshot.peak_balance = account.current_balance

    # 计算回撤
    if snapshot.peak_balance > 0:
        snapshot.current_drawdown = snapshot.peak_balance - account.current_balance
        snapshot.current_drawdown_percent = snapshot.current_drawdown / snapshot.peak_balance * 100
        if snapshot.current_drawdown > snapshot.max_drawdown:
            snapshot.max_drawdown = snapshot.current_drawdown
            snapshot.max_drawdown_percent = snapshot.current_drawdown_percent

    # 活跃警告数
    snapshot.active_alerts_count = RiskAlert.objects.filter(
        account=account,
        status='active'
    ).count()

    # 计算风险评分
    snapshot.calculate_risk_score()

    snapshot.save()
