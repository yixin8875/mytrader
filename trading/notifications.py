"""
通知服务模块
提供通知的创建、发送和管理功能
"""
from django.utils import timezone
from datetime import timedelta


class NotificationService:
    """通知服务类"""

    def __init__(self, user):
        self.user = user
        # 延迟导入避免循环引用
        from .models import Notification, NotificationSetting, PriceAlert
        self.Notification = Notification
        self.NotificationSetting = NotificationSetting
        self.PriceAlert = PriceAlert

    def get_settings(self):
        """获取用户通知设置"""
        setting, created = self.NotificationSetting.objects.get_or_create(owner=self.user)
        return setting

    def can_send_notification(self, notification_type):
        """检查是否可以发送特定类型的通知"""
        settings = self.get_settings()

        # 检查静默时段
        if settings.is_quiet_hours():
            return False

        # 检查通知类型开关
        type_settings = {
            'price_alert': settings.enable_price_alert,
            'plan_reminder': settings.enable_plan_reminder,
            'risk_warning': settings.enable_risk_warning,
            'daily_summary': settings.enable_daily_summary,
            'trade_executed': settings.enable_trade_notification,
            'system': True,  # 系统通知始终发送
        }

        return type_settings.get(notification_type, True)

    def create_notification(self, notification_type, title, message, priority='normal', **kwargs):
        """创建通知"""
        if not self.can_send_notification(notification_type):
            return None

        notification = self.Notification.objects.create(
            owner=self.user,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            related_symbol=kwargs.get('related_symbol'),
            related_trade=kwargs.get('related_trade'),
            related_plan=kwargs.get('related_plan'),
            related_alert=kwargs.get('related_alert'),
            extra_data=kwargs.get('extra_data', {}),
        )

        return notification

    def get_unread_count(self):
        """获取未读通知数量"""
        return self.Notification.objects.filter(
            owner=self.user,
            is_read=False
        ).count()

    def get_notifications(self, limit=50, include_read=True, notification_type=None):
        """获取通知列表"""
        qs = self.Notification.objects.filter(owner=self.user)

        if not include_read:
            qs = qs.filter(is_read=False)

        if notification_type:
            qs = qs.filter(notification_type=notification_type)

        return qs[:limit]

    def mark_as_read(self, notification_id):
        """标记单个通知为已读"""
        try:
            notification = self.Notification.objects.get(id=notification_id, owner=self.user)
            notification.mark_as_read()
            return True
        except self.Notification.DoesNotExist:
            return False

    def mark_all_as_read(self):
        """标记所有通知为已读"""
        count = self.Notification.objects.filter(
            owner=self.user,
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        return count

    def delete_notification(self, notification_id):
        """删除通知"""
        try:
            notification = self.Notification.objects.get(id=notification_id, owner=self.user)
            notification.delete()
            return True
        except self.Notification.DoesNotExist:
            return False

    def clear_old_notifications(self, days=30):
        """清理旧通知"""
        cutoff_date = timezone.now() - timedelta(days=days)
        count, _ = self.Notification.objects.filter(
            owner=self.user,
            created_at__lt=cutoff_date,
            is_read=True
        ).delete()
        return count

    # ==================== 特定类型通知创建 ====================

    def notify_risk_warning(self, risk_alert):
        """发送风险警告通知"""
        return self.create_notification(
            notification_type='risk_warning',
            title=f'风险警告: {risk_alert.title}',
            message=risk_alert.message,
            priority='urgent' if risk_alert.level == 'critical' else 'high',
            related_alert=risk_alert,
            extra_data={
                'alert_type': risk_alert.alert_type,
                'level': risk_alert.level,
                'current_value': str(risk_alert.current_value),
                'threshold_value': str(risk_alert.threshold_value),
            }
        )

    def notify_trade_executed(self, trade_log):
        """发送交易执行通知"""
        profit_loss = trade_log.profit_loss
        pnl_text = f'盈利 {profit_loss}' if profit_loss >= 0 else f'亏损 {abs(profit_loss)}'

        return self.create_notification(
            notification_type='trade_executed',
            title=f'交易执行: {trade_log.symbol.code}',
            message=f'{trade_log.get_side_display()} {trade_log.symbol.name} {trade_log.quantity}股 @ {trade_log.executed_price or trade_log.price}，{pnl_text}',
            priority='normal',
            related_trade=trade_log,
            related_symbol=trade_log.symbol,
            extra_data={
                'side': trade_log.side,
                'quantity': str(trade_log.quantity),
                'price': str(trade_log.executed_price or trade_log.price),
                'profit_loss': str(profit_loss),
            }
        )

    def notify_plan_reminder(self, trade_plan):
        """发送交易计划提醒"""
        return self.create_notification(
            notification_type='plan_reminder',
            title=f'交易计划提醒: {trade_plan.symbol.code}',
            message=f'{trade_plan.symbol.name} {trade_plan.get_direction_display()} 计划，入场区间: {trade_plan.entry_price_min}-{trade_plan.entry_price_max}',
            priority='high',
            related_plan=trade_plan,
            related_symbol=trade_plan.symbol,
            extra_data={
                'direction': trade_plan.direction,
                'entry_min': str(trade_plan.entry_price_min),
                'entry_max': str(trade_plan.entry_price_max),
                'stop_loss': str(trade_plan.stop_loss),
            }
        )

    def notify_daily_summary(self, summary_data):
        """发送每日总结提醒"""
        return self.create_notification(
            notification_type='daily_summary',
            title='每日交易总结',
            message=f"今日交易 {summary_data.get('trade_count', 0)} 笔，"
                    f"盈亏 {summary_data.get('total_pnl', 0)}，"
                    f"胜率 {summary_data.get('win_rate', 0)}%",
            priority='normal',
            extra_data=summary_data
        )

    # ==================== 价格提醒管理 ====================

    def create_price_alert(self, symbol, condition, target_price, **kwargs):
        """创建价格提醒"""
        alert = self.PriceAlert.objects.create(
            owner=self.user,
            symbol=symbol,
            condition=condition,
            target_price=target_price,
            valid_until=kwargs.get('valid_until'),
            trigger_once=kwargs.get('trigger_once', True),
            notes=kwargs.get('notes', ''),
        )
        return alert

    def get_active_price_alerts(self, symbol=None):
        """获取活跃的价格提醒"""
        qs = self.PriceAlert.objects.filter(owner=self.user, status='active')
        if symbol:
            qs = qs.filter(symbol=symbol)
        return qs

    def cancel_price_alert(self, alert_id):
        """取消价格提醒"""
        try:
            alert = self.PriceAlert.objects.get(id=alert_id, owner=self.user)
            alert.status = 'cancelled'
            alert.save(update_fields=['status'])
            return True
        except self.PriceAlert.DoesNotExist:
            return False


def check_pending_plans():
    """检查待执行的交易计划并发送提醒"""
    from .models import TradePlan, NotificationSetting
    from django.contrib.auth.models import User

    now = timezone.now()
    today = now.date()

    # 获取今天的待执行计划
    pending_plans = TradePlan.objects.filter(
        status='pending',
        plan_date=today
    ).select_related('symbol', 'account', 'account__owner')

    for plan in pending_plans:
        user = plan.account.owner

        # 获取用户设置
        try:
            settings = NotificationSetting.objects.get(owner=user)
            if not settings.enable_plan_reminder:
                continue
        except NotificationSetting.DoesNotExist:
            pass

        # 发送提醒
        service = NotificationService(user)
        service.notify_plan_reminder(plan)


def check_daily_summary_reminders():
    """检查并发送每日总结提醒"""
    from .models import NotificationSetting, DailyNote
    from django.contrib.auth.models import User

    now = timezone.now()
    current_time = now.time()
    today = now.date()

    # 获取需要发送提醒的用户
    settings_list = NotificationSetting.objects.filter(
        enable_daily_summary=True
    ).select_related('owner')

    for settings in settings_list:
        # 检查时间是否匹配（允许5分钟误差）
        reminder_time = settings.daily_summary_time
        time_diff = abs(
            (current_time.hour * 60 + current_time.minute) -
            (reminder_time.hour * 60 + reminder_time.minute)
        )

        if time_diff > 5:
            continue

        # 检查今天是否已经发送过
        from .models import Notification
        already_sent = Notification.objects.filter(
            owner=settings.owner,
            notification_type='daily_summary',
            created_at__date=today
        ).exists()

        if already_sent:
            continue

        # 检查今天是否已经写了总结
        has_note = DailyNote.objects.filter(
            owner=settings.owner,
            note_date=today,
            post_market_summary__isnull=False
        ).exclude(post_market_summary='').exists()

        if has_note:
            continue

        # 发送提醒
        service = NotificationService(settings.owner)
        service.create_notification(
            notification_type='daily_summary',
            title='每日交易总结提醒',
            message='别忘了写今天的交易总结哦！回顾今天的交易，总结经验教训。',
            priority='normal'
        )
