from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from decimal import Decimal
from datetime import date
from .models import TradeLog, AccountTransaction, DailyReport


@receiver(post_save, sender=TradeLog)
def process_trade_log(sender, instance, created, **kwargs):
    """
    交易日志保存后自动处理：
    1. 创建账户流水记录
    2. 更新账户余额
    3. 更新或创建每日报表
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
