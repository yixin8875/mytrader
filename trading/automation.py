"""
自动化任务模块
提供报表生成、风险检查、价格监控等自动化功能
"""
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F, Q
from django.db import transaction
from datetime import timedelta, date
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class ReportGenerator:
    """报表自动生成器"""

    def __init__(self, account=None):
        self.account = account
        # 延迟导入避免循环引用
        from .models import (
            Account, TradeLog, DailyReport, MonthlyReport,
            Position, RiskSnapshot
        )
        self.Account = Account
        self.TradeLog = TradeLog
        self.DailyReport = DailyReport
        self.MonthlyReport = MonthlyReport
        self.Position = Position
        self.RiskSnapshot = RiskSnapshot

    def generate_daily_report(self, report_date=None, account=None):
        """生成每日报表"""
        if report_date is None:
            report_date = timezone.now().date() - timedelta(days=1)  # 默认生成昨天的

        account = account or self.account
        if account is None:
            # 为所有活跃账户生成
            accounts = self.Account.objects.filter(status='active')
            results = []
            for acc in accounts:
                result = self._generate_daily_for_account(acc, report_date)
                if result:
                    results.append(result)
            return results
        else:
            return self._generate_daily_for_account(account, report_date)

    def _generate_daily_for_account(self, account, report_date):
        """为单个账户生成每日报表"""
        # 检查是否已存在
        existing = self.DailyReport.objects.filter(
            account=account,
            report_date=report_date
        ).first()
        if existing:
            logger.info(f"Daily report already exists for {account.name} on {report_date}")
            return existing

        # 获取当日交易
        day_start = timezone.make_aware(
            timezone.datetime.combine(report_date, timezone.datetime.min.time())
        )
        day_end = timezone.make_aware(
            timezone.datetime.combine(report_date, timezone.datetime.max.time())
        )

        trades = self.TradeLog.objects.filter(
            account=account,
            trade_time__range=(day_start, day_end),
            status='filled'
        )

        # 计算统计数据
        trade_count = trades.count()
        if trade_count == 0:
            logger.info(f"No trades for {account.name} on {report_date}")
            return None

        profit_loss = trades.aggregate(total=Sum('profit_loss'))['total'] or Decimal('0')
        commission = trades.aggregate(total=Sum('commission'))['total'] or Decimal('0')
        win_trades = trades.filter(profit_loss__gt=0)
        loss_trades = trades.filter(profit_loss__lt=0)
        win_count = win_trades.count()
        loss_count = loss_trades.count()

        # 获取前一天的报表以计算期初余额
        prev_report = self.DailyReport.objects.filter(
            account=account,
            report_date__lt=report_date
        ).order_by('-report_date').first()

        if prev_report:
            starting_balance = prev_report.ending_balance
        else:
            starting_balance = account.initial_balance

        # 计算净入金（当日入金-出金）
        from .models import AccountTransaction
        net_deposit = AccountTransaction.objects.filter(
            account=account,
            transaction_time__range=(day_start, day_end),
            transaction_type__in=['deposit', 'withdraw']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        ending_balance = starting_balance + profit_loss - commission + net_deposit

        # 胜率
        win_rate = Decimal(win_count / trade_count * 100) if trade_count > 0 else Decimal('0')

        # 盈亏比例
        profit_loss_ratio = Decimal('0')
        if starting_balance > 0:
            profit_loss_ratio = (profit_loss / starting_balance) * 100

        # 创建报表
        report = self.DailyReport.objects.create(
            account=account,
            report_date=report_date,
            starting_balance=starting_balance,
            ending_balance=ending_balance,
            net_deposit=net_deposit,
            profit_loss=profit_loss,
            profit_loss_ratio=profit_loss_ratio,
            trade_count=trade_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate=win_rate,
            commission=commission
        )

        logger.info(f"Generated daily report for {account.name} on {report_date}: PnL={profit_loss}")
        return report

    def generate_monthly_report(self, year=None, month=None, account=None):
        """生成月度报表"""
        now = timezone.now()
        if year is None or month is None:
            # 默认生成上个月的
            if now.month == 1:
                year = now.year - 1
                month = 12
            else:
                year = now.year
                month = now.month - 1

        account = account or self.account
        if account is None:
            accounts = self.Account.objects.filter(status='active')
            results = []
            for acc in accounts:
                result = self._generate_monthly_for_account(acc, year, month)
                if result:
                    results.append(result)
            return results
        else:
            return self._generate_monthly_for_account(account, year, month)

    def _generate_monthly_for_account(self, account, year, month):
        """为单个账户生成月度报表"""
        # 检查是否已存在
        existing = self.MonthlyReport.objects.filter(
            account=account,
            year=year,
            month=month
        ).first()
        if existing:
            logger.info(f"Monthly report already exists for {account.name} on {year}-{month}")
            return existing

        # 获取该月的每日报表
        daily_reports = self.DailyReport.objects.filter(
            account=account,
            report_date__year=year,
            report_date__month=month
        ).order_by('report_date')

        if not daily_reports.exists():
            logger.info(f"No daily reports for {account.name} on {year}-{month}")
            return None

        # 汇总数据
        first_report = daily_reports.first()
        last_report = daily_reports.last()

        starting_balance = first_report.starting_balance
        ending_balance = last_report.ending_balance

        aggregated = daily_reports.aggregate(
            total_pnl=Sum('profit_loss'),
            total_deposit=Sum('net_deposit'),
            max_dd=Avg('max_drawdown')  # 简化处理
        )

        profit_loss = aggregated['total_pnl'] or Decimal('0')
        net_deposit = aggregated['total_deposit'] or Decimal('0')

        # 直接从交易记录计算月度胜率（更准确）
        from datetime import date
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1)
        else:
            month_end = date(year, month + 1, 1)

        month_trades = self.TradeLog.objects.filter(
            account=account,
            status='filled',
            trade_time__date__gte=month_start,
            trade_time__date__lt=month_end
        )
        trade_count = month_trades.count()
        win_count = month_trades.filter(profit_loss__gt=0).count()

        # 胜率和盈亏比例
        win_rate = Decimal(win_count / trade_count * 100) if trade_count > 0 else Decimal('0')
        profit_loss_ratio = Decimal('0')
        if starting_balance > 0:
            profit_loss_ratio = (profit_loss / starting_balance) * 100

        # 创建月度报表
        report = self.MonthlyReport.objects.create(
            account=account,
            year=year,
            month=month,
            starting_balance=starting_balance,
            ending_balance=ending_balance,
            net_deposit=net_deposit,
            profit_loss=profit_loss,
            profit_loss_ratio=profit_loss_ratio,
            trade_count=trade_count,
            win_rate=win_rate,
            max_drawdown=aggregated['max_dd'] or Decimal('0')
        )

        logger.info(f"Generated monthly report for {account.name} on {year}-{month}: PnL={profit_loss}")
        return report


class RiskMonitor:
    """风险监控器"""

    def __init__(self):
        from .models import (
            Account, RiskRule, RiskAlert, RiskSnapshot,
            TradeLog, Position
        )
        from .notifications import NotificationService
        self.Account = Account
        self.RiskRule = RiskRule
        self.RiskAlert = RiskAlert
        self.RiskSnapshot = RiskSnapshot
        self.TradeLog = TradeLog
        self.Position = Position
        self.NotificationService = NotificationService

    def check_all_rules(self, account=None):
        """检查所有风险规则"""
        if account:
            accounts = [account]
        else:
            accounts = self.Account.objects.filter(status='active')

        alerts = []
        for acc in accounts:
            acc_alerts = self._check_account_rules(acc)
            alerts.extend(acc_alerts)

        return alerts

    def _check_account_rules(self, account):
        """检查单个账户的风险规则"""
        rules = self.RiskRule.objects.filter(account=account, is_active=True)
        alerts = []

        for rule in rules:
            alert = self._check_rule(rule, account)
            if alert:
                alerts.append(alert)
                # 发送通知
                try:
                    service = self.NotificationService(account.owner)
                    service.notify_risk_warning(alert)
                except Exception as e:
                    logger.error(f"Failed to send risk notification: {e}")

        return alerts

    def _check_rule(self, rule, account):
        """检查单条规则"""
        current_value = self._get_current_value(rule, account)
        threshold = self._get_threshold(rule, account)

        if current_value is None or threshold is None:
            return None

        # 判断是否触发
        triggered = False
        if rule.rule_type in ['daily_loss_limit', 'single_trade_loss', 'max_drawdown']:
            # 这些是负值越大越危险
            triggered = abs(current_value) >= abs(threshold)
        else:
            # 其他规则是正值越大越危险
            triggered = current_value >= threshold

        if not triggered:
            return None

        # 检查是否最近已经触发过（避免重复警告）
        recent_alert = self.RiskAlert.objects.filter(
            account=account,
            rule=rule,
            status='active',
            triggered_at__gte=timezone.now() - timedelta(hours=1)
        ).exists()

        if recent_alert:
            return None

        # 创建警告
        alert = self.RiskAlert.objects.create(
            account=account,
            rule=rule,
            alert_type=rule.rule_type,
            level=rule.level,
            title=f'{rule.get_rule_type_display()}警告',
            message=self._generate_alert_message(rule, current_value, threshold),
            current_value=current_value,
            threshold_value=threshold
        )

        logger.warning(f"Risk alert triggered: {alert.title} for {account.name}")
        return alert

    def _get_current_value(self, rule, account):
        """获取规则对应的当前值"""
        today = timezone.now().date()
        today_start = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        )

        if rule.rule_type == 'daily_loss_limit':
            # 今日亏损
            pnl = self.TradeLog.objects.filter(
                account=account,
                trade_time__gte=today_start,
                status='filled'
            ).aggregate(total=Sum('profit_loss'))['total'] or Decimal('0')
            return abs(pnl) if pnl < 0 else Decimal('0')

        elif rule.rule_type == 'single_trade_loss':
            # 最近一笔交易亏损
            last_trade = self.TradeLog.objects.filter(
                account=account,
                status='filled'
            ).order_by('-trade_time').first()
            if last_trade and last_trade.profit_loss < 0:
                return abs(last_trade.profit_loss)
            return Decimal('0')

        elif rule.rule_type == 'max_drawdown':
            # 当前回撤
            snapshot = self.RiskSnapshot.objects.filter(
                account=account
            ).order_by('-snapshot_date').first()
            if snapshot:
                return snapshot.current_drawdown
            return Decimal('0')

        elif rule.rule_type == 'max_position_ratio':
            # 当前仓位比例
            positions = self.Position.objects.filter(account=account)
            total_position = positions.aggregate(
                total=Sum('market_value')
            )['total'] or Decimal('0')
            if account.current_balance > 0:
                return (total_position / account.current_balance) * 100
            return Decimal('0')

        elif rule.rule_type == 'consecutive_losses':
            # 连续亏损次数
            snapshot = self.RiskSnapshot.objects.filter(
                account=account
            ).order_by('-snapshot_date').first()
            if snapshot:
                return Decimal(str(snapshot.consecutive_losses))
            return Decimal('0')

        elif rule.rule_type == 'daily_trade_limit':
            # 今日交易次数
            count = self.TradeLog.objects.filter(
                account=account,
                trade_time__gte=today_start
            ).count()
            return Decimal(str(count))

        return None

    def _get_threshold(self, rule, account):
        """获取规则阈值
        使用 initial_balance 作为计算基准，避免账户亏损时阈值变小
        """
        if rule.threshold_percent and rule.rule_type in ['daily_loss_limit', 'single_trade_loss', 'max_drawdown']:
            # 按百分比计算阈值，使用初始余额作为基准
            base_balance = account.initial_balance if account.initial_balance > 0 else account.current_balance
            return base_balance * rule.threshold_percent / 100
        return rule.threshold_value

    def _generate_alert_message(self, rule, current_value, threshold):
        """生成警告消息"""
        messages = {
            'daily_loss_limit': f'今日亏损 ¥{current_value:.2f} 已超过限额 ¥{threshold:.2f}',
            'single_trade_loss': f'单笔亏损 ¥{current_value:.2f} 已超过限额 ¥{threshold:.2f}',
            'max_drawdown': f'当前回撤 ¥{current_value:.2f} 已超过限额 ¥{threshold:.2f}',
            'max_position_ratio': f'当前仓位 {current_value:.1f}% 已超过限额 {threshold:.1f}%',
            'consecutive_losses': f'已连续亏损 {int(current_value)} 次，超过限额 {int(threshold)} 次',
            'daily_trade_limit': f'今日交易 {int(current_value)} 次，已超过限额 {int(threshold)} 次',
        }
        return messages.get(rule.rule_type, f'当前值 {current_value} 超过阈值 {threshold}')

    def update_risk_snapshot(self, account=None):
        """更新风险快照"""
        if account:
            accounts = [account]
        else:
            accounts = self.Account.objects.filter(status='active')

        snapshots = []
        for acc in accounts:
            snapshot = self._create_snapshot(acc)
            if snapshot:
                snapshots.append(snapshot)

        return snapshots

    def _create_snapshot(self, account):
        """为账户创建风险快照"""
        today = timezone.now().date()

        # 检查今天是否已有快照
        existing = self.RiskSnapshot.objects.filter(
            account=account,
            snapshot_date=today
        ).first()

        today_start = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        )

        # 获取今日交易统计
        today_trades = self.TradeLog.objects.filter(
            account=account,
            trade_time__gte=today_start,
            status='filled'
        )

        daily_pnl = today_trades.aggregate(total=Sum('profit_loss'))['total'] or Decimal('0')
        daily_trade_count = today_trades.count()
        daily_win_count = today_trades.filter(profit_loss__gt=0).count()
        daily_loss_count = today_trades.filter(profit_loss__lt=0).count()

        # 计算盈亏百分比
        daily_pnl_percent = Decimal('0')
        if account.current_balance > 0:
            daily_pnl_percent = (daily_pnl / account.current_balance) * 100

        # 获取历史最高余额
        prev_snapshot = self.RiskSnapshot.objects.filter(
            account=account
        ).order_by('-snapshot_date').first()

        if prev_snapshot:
            peak_balance = max(prev_snapshot.peak_balance, account.current_balance)
            # 连续统计
            if daily_pnl > 0:
                consecutive_wins = prev_snapshot.consecutive_wins + 1 if prev_snapshot.consecutive_wins >= 0 else 1
                consecutive_losses = 0
            elif daily_pnl < 0:
                consecutive_losses = prev_snapshot.consecutive_losses + 1 if prev_snapshot.consecutive_losses >= 0 else 1
                consecutive_wins = 0
            else:
                consecutive_wins = prev_snapshot.consecutive_wins
                consecutive_losses = prev_snapshot.consecutive_losses
            max_drawdown = prev_snapshot.max_drawdown
            max_drawdown_percent = prev_snapshot.max_drawdown_percent
        else:
            peak_balance = account.current_balance
            consecutive_wins = 1 if daily_pnl > 0 else 0
            consecutive_losses = 1 if daily_pnl < 0 else 0
            max_drawdown = Decimal('0')
            max_drawdown_percent = Decimal('0')

        # 计算当前回撤
        current_drawdown = peak_balance - account.current_balance
        current_drawdown_percent = Decimal('0')
        if peak_balance > 0:
            current_drawdown_percent = (current_drawdown / peak_balance) * 100

        # 更新最大回撤
        if current_drawdown > max_drawdown:
            max_drawdown = current_drawdown
            max_drawdown_percent = current_drawdown_percent

        # 计算持仓数据
        positions = self.Position.objects.filter(account=account)
        total_position_value = positions.aggregate(
            total=Sum('market_value')
        )['total'] or Decimal('0')

        position_ratio = Decimal('0')
        if account.current_balance > 0:
            position_ratio = (total_position_value / account.current_balance) * 100

        # 活跃警告数
        active_alerts_count = self.RiskAlert.objects.filter(
            account=account,
            status='active'
        ).count()

        # 创建或更新快照
        if existing:
            snapshot = existing
            snapshot.daily_pnl = daily_pnl
            snapshot.daily_pnl_percent = daily_pnl_percent
            snapshot.daily_trade_count = daily_trade_count
            snapshot.daily_win_count = daily_win_count
            snapshot.daily_loss_count = daily_loss_count
            snapshot.consecutive_wins = consecutive_wins
            snapshot.consecutive_losses = consecutive_losses
            snapshot.peak_balance = peak_balance
            snapshot.current_drawdown = current_drawdown
            snapshot.current_drawdown_percent = current_drawdown_percent
            snapshot.max_drawdown = max_drawdown
            snapshot.max_drawdown_percent = max_drawdown_percent
            snapshot.total_position_value = total_position_value
            snapshot.position_ratio = position_ratio
            snapshot.active_alerts_count = active_alerts_count
            snapshot.calculate_risk_score()
            snapshot.save()
        else:
            snapshot = self.RiskSnapshot.objects.create(
                account=account,
                snapshot_date=today,
                daily_pnl=daily_pnl,
                daily_pnl_percent=daily_pnl_percent,
                daily_trade_count=daily_trade_count,
                daily_win_count=daily_win_count,
                daily_loss_count=daily_loss_count,
                consecutive_wins=consecutive_wins,
                consecutive_losses=consecutive_losses,
                peak_balance=peak_balance,
                current_drawdown=current_drawdown,
                current_drawdown_percent=current_drawdown_percent,
                max_drawdown=max_drawdown,
                max_drawdown_percent=max_drawdown_percent,
                total_position_value=total_position_value,
                position_ratio=position_ratio,
                active_alerts_count=active_alerts_count
            )
            snapshot.calculate_risk_score()
            snapshot.save()

        logger.info(f"Updated risk snapshot for {account.name}: risk_score={snapshot.risk_score}")
        return snapshot


class PriceMonitor:
    """价格监控器"""

    def __init__(self):
        from .models import PriceAlert, Symbol
        self.PriceAlert = PriceAlert
        self.Symbol = Symbol

    def check_price_alerts(self, prices_data):
        """
        检查价格提醒
        prices_data: dict, {symbol_code: current_price}
        """
        active_alerts = self.PriceAlert.objects.filter(
            status='active'
        ).select_related('symbol', 'owner')

        triggered_alerts = []
        for alert in active_alerts:
            symbol_code = alert.symbol.code
            if symbol_code not in prices_data:
                continue

            current_price = Decimal(str(prices_data[symbol_code]))
            if alert.check_condition(current_price):
                alert.trigger()
                triggered_alerts.append(alert)
                logger.info(f"Price alert triggered: {alert.symbol.code} {alert.get_condition_display()} {alert.target_price}")

        return triggered_alerts

    def check_expired_alerts(self):
        """检查过期的价格提醒"""
        now = timezone.now()
        expired_alerts = self.PriceAlert.objects.filter(
            status='active',
            valid_until__lt=now
        )

        count = expired_alerts.update(status='expired')
        if count > 0:
            logger.info(f"Expired {count} price alerts")
        return count


class StrategyPerformanceUpdater:
    """策略绩效更新器"""

    def __init__(self):
        from .models import Strategy, PerformanceMetrics, TradeLog
        self.Strategy = Strategy
        self.PerformanceMetrics = PerformanceMetrics
        self.TradeLog = TradeLog

    def update_all_strategies(self):
        """更新所有策略的绩效指标"""
        strategies = self.Strategy.objects.filter(status__in=['active', 'paused'])
        results = []

        for strategy in strategies:
            result = self.update_strategy_metrics(strategy)
            if result:
                results.append(result)

        return results

    def update_strategy_metrics(self, strategy):
        """更新单个策略的绩效指标"""
        trades = self.TradeLog.objects.filter(
            strategy=strategy,
            status='filled'
        )

        if not trades.exists():
            return None

        # 获取或创建绩效指标记录
        metrics, created = self.PerformanceMetrics.objects.get_or_create(
            strategy=strategy
        )

        # 计算基本统计
        total_trades = trades.count()
        profitable_trades = trades.filter(profit_loss__gt=0).count()
        losing_trades = trades.filter(profit_loss__lt=0).count()

        total_profit = trades.filter(profit_loss__gt=0).aggregate(
            total=Sum('profit_loss')
        )['total'] or Decimal('0')

        total_loss = abs(trades.filter(profit_loss__lt=0).aggregate(
            total=Sum('profit_loss')
        )['total'] or Decimal('0'))

        # 计算平均值
        avg_profit = total_profit / profitable_trades if profitable_trades > 0 else Decimal('0')
        avg_loss = total_loss / losing_trades if losing_trades > 0 else Decimal('0')

        # 最大盈亏
        largest_profit = trades.filter(profit_loss__gt=0).order_by('-profit_loss').first()
        largest_loss = trades.filter(profit_loss__lt=0).order_by('profit_loss').first()

        # 胜率和盈亏比
        win_rate = Decimal(profitable_trades / total_trades * 100) if total_trades > 0 else Decimal('0')
        profit_factor = total_profit / total_loss if total_loss > 0 else None

        # 更新指标
        metrics.total_trades = total_trades
        metrics.profitable_trades = profitable_trades
        metrics.losing_trades = losing_trades
        metrics.win_rate = win_rate
        metrics.total_profit = total_profit
        metrics.total_loss = total_loss
        metrics.profit_factor = profit_factor
        metrics.average_profit = avg_profit
        metrics.average_loss = avg_loss
        metrics.largest_profit = largest_profit.profit_loss if largest_profit else Decimal('0')
        metrics.largest_loss = largest_loss.profit_loss if largest_loss else Decimal('0')
        metrics.total_return = total_profit - total_loss

        metrics.save()

        logger.info(f"Updated performance metrics for strategy: {strategy.name}")
        return metrics


class TradePlanChecker:
    """交易计划检查器"""

    def __init__(self):
        from .models import TradePlan
        from .notifications import NotificationService
        self.TradePlan = TradePlan
        self.NotificationService = NotificationService

    def check_expiring_plans(self):
        """检查即将到期的交易计划"""
        today = timezone.now().date()

        # 获取今天有效且待执行的计划
        expiring_plans = self.TradePlan.objects.filter(
            status='pending',
            plan_date=today
        ).select_related('symbol', 'account', 'account__owner')

        notified = []
        for plan in expiring_plans:
            try:
                service = self.NotificationService(plan.account.owner)
                service.notify_plan_reminder(plan)
                notified.append(plan)
                logger.info(f"Sent plan reminder for: {plan.symbol.code}")
            except Exception as e:
                logger.error(f"Failed to send plan reminder: {e}")

        return notified

    def expire_old_plans(self):
        """将过期的计划标记为已过期"""
        today = timezone.now().date()

        expired_count = self.TradePlan.objects.filter(
            status__in=['draft', 'pending'],
            valid_until__lt=today
        ).update(status='expired')

        # 对于没有设置valid_until的计划，如果plan_date已过，也标记为过期
        expired_count += self.TradePlan.objects.filter(
            status__in=['draft', 'pending'],
            valid_until__isnull=True,
            plan_date__lt=today
        ).update(status='expired')

        if expired_count > 0:
            logger.info(f"Expired {expired_count} trade plans")

        return expired_count


def run_daily_tasks():
    """运行每日自动化任务"""
    logger.info("Starting daily automation tasks...")
    results = {
        'daily_reports': [],
        'risk_snapshots': [],
        'risk_alerts': [],
        'expired_plans': 0,
        'expired_alerts': 0,
        'strategy_metrics': [],
    }

    try:
        # 1. 生成每日报表（昨天的）
        report_gen = ReportGenerator()
        results['daily_reports'] = report_gen.generate_daily_report()
        logger.info(f"Generated {len(results['daily_reports']) if results['daily_reports'] else 0} daily reports")

        # 2. 更新风险快照
        risk_monitor = RiskMonitor()
        results['risk_snapshots'] = risk_monitor.update_risk_snapshot()
        logger.info(f"Updated {len(results['risk_snapshots'])} risk snapshots")

        # 3. 检查风险规则
        results['risk_alerts'] = risk_monitor.check_all_rules()
        logger.info(f"Generated {len(results['risk_alerts'])} risk alerts")

        # 4. 过期交易计划
        plan_checker = TradePlanChecker()
        results['expired_plans'] = plan_checker.expire_old_plans()

        # 5. 过期价格提醒
        price_monitor = PriceMonitor()
        results['expired_alerts'] = price_monitor.check_expired_alerts()

        # 6. 更新策略绩效
        perf_updater = StrategyPerformanceUpdater()
        results['strategy_metrics'] = perf_updater.update_all_strategies()
        logger.info(f"Updated {len(results['strategy_metrics'])} strategy metrics")

    except Exception as e:
        logger.error(f"Error in daily tasks: {e}")
        raise

    logger.info("Daily automation tasks completed")
    return results


def run_monthly_tasks():
    """运行每月自动化任务"""
    logger.info("Starting monthly automation tasks...")
    results = {
        'monthly_reports': [],
    }

    try:
        # 生成月度报表（上个月的）
        report_gen = ReportGenerator()
        results['monthly_reports'] = report_gen.generate_monthly_report()
        logger.info(f"Generated {len(results['monthly_reports']) if results['monthly_reports'] else 0} monthly reports")

    except Exception as e:
        logger.error(f"Error in monthly tasks: {e}")
        raise

    logger.info("Monthly automation tasks completed")
    return results


def run_hourly_tasks():
    """运行每小时自动化任务"""
    logger.info("Starting hourly automation tasks...")
    results = {
        'plan_reminders': [],
        'risk_checks': [],
    }

    try:
        # 1. 检查交易计划提醒
        plan_checker = TradePlanChecker()
        results['plan_reminders'] = plan_checker.check_expiring_plans()

        # 2. 检查风险规则
        risk_monitor = RiskMonitor()
        results['risk_checks'] = risk_monitor.check_all_rules()

    except Exception as e:
        logger.error(f"Error in hourly tasks: {e}")
        raise

    logger.info("Hourly automation tasks completed")
    return results
