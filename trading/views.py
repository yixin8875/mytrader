from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Avg
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from datetime import timedelta, datetime
import json
import logging
from .models import Account, TradeLog, DailyReport, Position, Strategy, Notification, PriceAlert, Symbol
from .analytics import TradeAnalytics
from .notifications import NotificationService

logger = logging.getLogger(__name__)


def home(request):
    """主页视图"""
    context = {}
    if request.user.is_authenticated:
        accounts = Account.objects.filter(owner=request.user)
        context['total_balance'] = accounts.aggregate(total=Sum('current_balance'))['total'] or 0
        context['total_profit'] = accounts.aggregate(total=Sum('current_balance'))['total'] or 0
        initial = accounts.aggregate(total=Sum('initial_balance'))['total'] or 0
        context['total_profit'] = context['total_balance'] - initial
        context['account_count'] = accounts.count()
        context['recent_trades'] = TradeLog.objects.filter(
            account__owner=request.user
        ).select_related('symbol', 'account')[:5]
    return render(request, 'trading/home.html', context)


def api_dashboard_data(request):
    """仪表盘数据API"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    accounts = Account.objects.filter(owner=request.user)

    # 账户汇总
    total_balance = float(accounts.aggregate(total=Sum('current_balance'))['total'] or 0)
    initial_balance = float(accounts.aggregate(total=Sum('initial_balance'))['total'] or 0)
    total_profit = total_balance - initial_balance
    profit_ratio = (total_profit / initial_balance * 100) if initial_balance > 0 else 0

    # 最近30天盈亏趋势
    thirty_days_ago = timezone.now().date() - timedelta(days=30)
    daily_reports = DailyReport.objects.filter(
        account__owner=request.user,
        report_date__gte=thirty_days_ago
    ).values('report_date').annotate(
        daily_pnl=Sum('profit_loss')
    ).order_by('report_date')

    pnl_dates = [r['report_date'].strftime('%m-%d') for r in daily_reports]
    pnl_values = [float(r['daily_pnl']) for r in daily_reports]

    # 月度盈亏
    monthly_trades = TradeLog.objects.filter(
        account__owner=request.user
    ).annotate(
        month=TruncMonth('trade_time')
    ).values('month').annotate(
        total_pnl=Sum('profit_loss'),
        count=Count('id')
    ).order_by('-month')[:6]

    monthly_labels = [m['month'].strftime('%Y-%m') for m in monthly_trades][::-1]
    monthly_values = [float(m['total_pnl']) for m in monthly_trades][::-1]

    # 账户类型分布
    account_types = accounts.values('account_type').annotate(
        total=Sum('current_balance')
    )
    type_labels = [Account.ACCOUNT_TYPE_CHOICES[next(i for i, c in enumerate(Account.ACCOUNT_TYPE_CHOICES) if c[0] == a['account_type'])][1] for a in account_types]
    type_values = [float(a['total']) for a in account_types]

    # 交易统计
    trades = TradeLog.objects.filter(account__owner=request.user)
    total_trades = trades.count()
    win_trades = trades.filter(profit_loss__gt=0).count()
    win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0

    return JsonResponse({
        'summary': {
            'total_balance': total_balance,
            'total_profit': total_profit,
            'profit_ratio': round(profit_ratio, 2),
            'account_count': accounts.count(),
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
        },
        'pnl_trend': {
            'labels': pnl_dates,
            'values': pnl_values,
        },
        'monthly_pnl': {
            'labels': monthly_labels,
            'values': monthly_values,
        },
        'account_distribution': {
            'labels': type_labels,
            'values': type_values,
        }
    })


def analytics_page(request):
    """深度分析页面"""
    if not request.user.is_authenticated:
        from django.shortcuts import redirect
        return redirect('admin:login')

    accounts = Account.objects.filter(owner=request.user)
    return render(request, 'trading/analytics.html', {
        'accounts': accounts,
    })


def api_analytics_data(request):
    """深度分析数据API"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    # 获取筛选参数
    account_id = request.GET.get('account')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    analysis_type = request.GET.get('type', 'summary')

    # 解析日期
    start = None
    end = None
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
        except ValueError:
            pass

    # 获取账户
    account = None
    if account_id:
        try:
            account = Account.objects.get(id=account_id, owner=request.user)
        except Account.DoesNotExist:
            pass

    # 创建分析器
    analyzer = TradeAnalytics(
        user=request.user,
        account=account,
        start_date=start,
        end_date=end
    )

    # 根据类型返回数据
    if analysis_type == 'full':
        data = analyzer.get_full_report()
    elif analysis_type == 'summary':
        data = analyzer.get_summary()
    elif analysis_type == 'hour':
        data = analyzer.analyze_by_hour()
    elif analysis_type == 'weekday':
        data = analyzer.analyze_by_weekday()
    elif analysis_type == 'symbol':
        data = analyzer.analyze_by_symbol()
    elif analysis_type == 'symbol_type':
        data = analyzer.analyze_by_symbol_type()
    elif analysis_type == 'strategy':
        data = analyzer.analyze_by_strategy()
    elif analysis_type == 'side':
        data = analyzer.analyze_by_side()
    elif analysis_type == 'month':
        data = analyzer.analyze_by_month()
    elif analysis_type == 'streaks':
        data = analyzer.analyze_streaks()
    elif analysis_type == 'distribution':
        data = analyzer.analyze_pnl_distribution()
    else:
        data = analyzer.get_summary()

    return JsonResponse(data, safe=False)


# ==================== 数据导入导出 ====================

def import_export_page(request):
    """数据导入导出页面"""
    if not request.user.is_authenticated:
        from django.shortcuts import redirect
        return redirect('admin:login')

    accounts = Account.objects.filter(owner=request.user)
    strategies = Strategy.objects.filter(owner=request.user)

    # 统计信息
    trade_count = TradeLog.objects.filter(account__owner=request.user).count()
    position_count = Position.objects.filter(account__owner=request.user).count()

    return render(request, 'trading/import_export.html', {
        'accounts': accounts,
        'strategies': strategies,
        'trade_count': trade_count,
        'position_count': position_count,
    })


def export_trades(request):
    """导出交易记录"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .import_export import DataExporter

    account_id = request.GET.get('account')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # 解析日期
    start = None
    end = None
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
        except ValueError:
            pass

    # 获取账户
    account = None
    if account_id:
        try:
            account = Account.objects.get(id=account_id, owner=request.user)
        except Account.DoesNotExist:
            pass

    exporter = DataExporter(request.user)
    csv_content = exporter.export_trades_csv(account=account, start_date=start, end_date=end)

    response = HttpResponse(csv_content.getvalue(), content_type='text/csv; charset=utf-8-sig')
    filename = f'trades_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_accounts(request):
    """导出账户数据"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .import_export import DataExporter

    exporter = DataExporter(request.user)
    csv_content = exporter.export_accounts_csv()

    response = HttpResponse(csv_content.getvalue(), content_type='text/csv; charset=utf-8-sig')
    filename = f'accounts_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_positions(request):
    """导出持仓数据"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .import_export import DataExporter

    account_id = request.GET.get('account')
    account = None
    if account_id:
        try:
            account = Account.objects.get(id=account_id, owner=request.user)
        except Account.DoesNotExist:
            pass

    exporter = DataExporter(request.user)
    csv_content = exporter.export_positions_csv(account=account)

    response = HttpResponse(csv_content.getvalue(), content_type='text/csv; charset=utf-8-sig')
    filename = f'positions_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_symbols(request):
    """导出交易标的"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .import_export import DataExporter

    exporter = DataExporter(request.user)
    csv_content = exporter.export_symbols_csv()

    response = HttpResponse(csv_content.getvalue(), content_type='text/csv; charset=utf-8-sig')
    filename = f'symbols_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_analysis(request):
    """导出分析报告"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .import_export import DataExporter

    account_id = request.GET.get('account')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    # 解析日期
    start = None
    end = None
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
        except ValueError:
            pass
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
        except ValueError:
            pass

    # 获取账户
    account = None
    if account_id:
        try:
            account = Account.objects.get(id=account_id, owner=request.user)
        except Account.DoesNotExist:
            pass

    exporter = DataExporter(request.user)
    csv_content = exporter.export_analysis_csv(account=account, start_date=start, end_date=end)

    response = HttpResponse(csv_content.getvalue(), content_type='text/csv; charset=utf-8-sig')
    filename = f'analysis_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def download_template(request):
    """下载导入模板"""
    template_type = request.GET.get('type', 'trade')

    from .import_export import get_trade_import_template, get_symbol_import_template

    if template_type == 'symbol':
        csv_content = get_symbol_import_template()
        filename = 'symbol_import_template.csv'
    else:
        csv_content = get_trade_import_template()
        filename = 'trade_import_template.csv'

    response = HttpResponse(csv_content.getvalue(), content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@require_http_methods(["POST"])
def import_trades(request):
    """导入交易记录"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .import_export import DataImporter

    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'error': '请选择文件'}, status=400)

    account_id = request.POST.get('account')
    if not account_id:
        return JsonResponse({'error': '请选择账户'}, status=400)

    strategy_id = request.POST.get('strategy')

    try:
        file_content = file.read()
        importer = DataImporter(request.user)
        importer.import_trades(file_content, account_id, strategy_id)
        result = importer.get_import_result()
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
def import_symbols(request):
    """导入交易标的"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .import_export import DataImporter

    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'error': '请选择文件'}, status=400)

    try:
        file_content = file.read()
        importer = DataImporter(request.user)
        importer.import_symbols(file_content)
        result = importer.get_import_result()
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ==================== 通知管理 ====================

def notifications_page(request):
    """通知中心页面"""
    if not request.user.is_authenticated:
        return redirect('admin:login')

    service = NotificationService(request.user)
    notifications = service.get_notifications(limit=100)
    unread_count = service.get_unread_count()

    # 获取价格提醒
    price_alerts = PriceAlert.objects.filter(
        owner=request.user
    ).select_related('symbol').order_by('-created_at')[:20]

    # 获取用户设置
    settings = service.get_settings()

    return render(request, 'trading/notifications.html', {
        'notifications': notifications,
        'unread_count': unread_count,
        'price_alerts': price_alerts,
        'notification_settings': settings,
    })


def api_notifications(request):
    """获取通知列表API"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    service = NotificationService(request.user)
    limit = int(request.GET.get('limit', 50))
    include_read = request.GET.get('include_read', 'true').lower() == 'true'
    notification_type = request.GET.get('type')

    notifications = service.get_notifications(
        limit=limit,
        include_read=include_read,
        notification_type=notification_type
    )

    data = [{
        'id': n.id,
        'type': n.notification_type,
        'type_display': n.get_notification_type_display(),
        'priority': n.priority,
        'priority_display': n.get_priority_display(),
        'title': n.title,
        'message': n.message,
        'icon': n.get_icon(),
        'color': n.get_color(),
        'is_read': n.is_read,
        'created_at': n.created_at.strftime('%Y-%m-%d %H:%M'),
        'related_symbol': n.related_symbol.code if n.related_symbol else None,
    } for n in notifications]

    return JsonResponse({
        'notifications': data,
        'unread_count': service.get_unread_count(),
    })


def api_notification_unread_count(request):
    """获取未读通知数量"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    service = NotificationService(request.user)
    return JsonResponse({
        'unread_count': service.get_unread_count()
    })


@require_http_methods(["POST"])
def api_notification_mark_read(request, notification_id):
    """标记通知为已读"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    service = NotificationService(request.user)
    success = service.mark_as_read(notification_id)

    return JsonResponse({
        'success': success,
        'unread_count': service.get_unread_count()
    })


@require_http_methods(["POST"])
def api_notification_mark_all_read(request):
    """标记所有通知为已读"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    service = NotificationService(request.user)
    count = service.mark_all_as_read()

    return JsonResponse({
        'success': True,
        'marked_count': count,
        'unread_count': 0
    })


@require_http_methods(["POST"])
def api_notification_delete(request, notification_id):
    """删除通知"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    service = NotificationService(request.user)
    success = service.delete_notification(notification_id)

    return JsonResponse({
        'success': success,
        'unread_count': service.get_unread_count()
    })


@require_http_methods(["POST"])
def api_notification_clear_old(request):
    """清理旧通知"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    days = int(request.POST.get('days', 30))
    service = NotificationService(request.user)
    count = service.clear_old_notifications(days=days)

    return JsonResponse({
        'success': True,
        'cleared_count': count
    })


# ==================== 价格提醒 ====================

def api_price_alerts(request):
    """获取价格提醒列表"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    status = request.GET.get('status', 'active')
    alerts = PriceAlert.objects.filter(owner=request.user)

    if status:
        alerts = alerts.filter(status=status)

    alerts = alerts.select_related('symbol').order_by('-created_at')[:50]

    data = [{
        'id': a.id,
        'symbol': a.symbol.code,
        'symbol_name': a.symbol.name,
        'condition': a.condition,
        'condition_display': a.get_condition_display(),
        'target_price': str(a.target_price),
        'last_price': str(a.last_price) if a.last_price else None,
        'status': a.status,
        'status_display': a.get_status_display(),
        'trigger_once': a.trigger_once,
        'trigger_count': a.trigger_count,
        'notes': a.notes,
        'created_at': a.created_at.strftime('%Y-%m-%d %H:%M'),
    } for a in alerts]

    return JsonResponse({'alerts': data})


@login_required
@require_http_methods(["POST"])
def api_price_alert_create(request):
    """创建价格提醒"""

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    symbol_id = data.get('symbol_id')
    condition = data.get('condition')
    target_price = data.get('target_price')
    trigger_once = data.get('trigger_once', True)
    notes = data.get('notes', '')

    if not all([symbol_id, condition, target_price]):
        return JsonResponse({'error': '缺少必要参数'}, status=400)

    try:
        symbol = Symbol.objects.get(id=symbol_id)
    except Symbol.DoesNotExist:
        return JsonResponse({'error': '标的不存在'}, status=404)

    service = NotificationService(request.user)
    alert = service.create_price_alert(
        symbol=symbol,
        condition=condition,
        target_price=target_price,
        trigger_once=trigger_once if isinstance(trigger_once, bool) else trigger_once == 'true',
        notes=notes
    )

    return JsonResponse({
        'success': True,
        'alert_id': alert.id,
        'message': f'价格提醒已创建：{symbol.code} {alert.get_condition_display()} {target_price}'
    })


@require_http_methods(["POST"])
def api_price_alert_cancel(request, alert_id):
    """取消价格提醒"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    service = NotificationService(request.user)
    success = service.cancel_price_alert(alert_id)

    return JsonResponse({
        'success': success,
        'message': '已取消' if success else '取消失败'
    })


@login_required
@require_http_methods(["POST"])
def api_notification_settings_update(request):
    """更新通知设置"""

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    service = NotificationService(request.user)
    settings = service.get_settings()

    # 更新设置
    if 'enable_price_alert' in data:
        settings.enable_price_alert = data['enable_price_alert']
    if 'enable_plan_reminder' in data:
        settings.enable_plan_reminder = data['enable_plan_reminder']
    if 'enable_risk_warning' in data:
        settings.enable_risk_warning = data['enable_risk_warning']
    if 'enable_daily_summary' in data:
        settings.enable_daily_summary = data['enable_daily_summary']
    if 'enable_trade_notification' in data:
        settings.enable_trade_notification = data['enable_trade_notification']
    if 'daily_summary_time' in data:
        settings.daily_summary_time = data['daily_summary_time']
    if 'plan_reminder_minutes' in data:
        settings.plan_reminder_minutes = int(data['plan_reminder_minutes'])
    if 'quiet_hours_start' in data:
        settings.quiet_hours_start = data['quiet_hours_start'] or None
    if 'quiet_hours_end' in data:
        settings.quiet_hours_end = data['quiet_hours_end'] or None

    settings.save()

    return JsonResponse({
        'success': True,
        'message': '设置已更新'
    })


# ==================== 自动化任务 ====================

def automation_page(request):
    """自动化任务管理页面"""
    if not request.user.is_authenticated:
        return redirect('admin:login')

    accounts = Account.objects.filter(owner=request.user, status='active')

    # 获取最近的报表统计
    from .models import DailyReport, MonthlyReport, RiskSnapshot, RiskAlert

    recent_daily = DailyReport.objects.filter(
        account__owner=request.user
    ).order_by('-report_date').first()

    recent_monthly = MonthlyReport.objects.filter(
        account__owner=request.user
    ).order_by('-year', '-month').first()

    recent_snapshot = RiskSnapshot.objects.filter(
        account__owner=request.user
    ).order_by('-snapshot_date').first()

    active_alerts = RiskAlert.objects.filter(
        account__owner=request.user,
        status='active'
    ).count()

    return render(request, 'trading/automation.html', {
        'accounts': accounts,
        'recent_daily': recent_daily,
        'recent_monthly': recent_monthly,
        'recent_snapshot': recent_snapshot,
        'active_alerts': active_alerts,
    })


@require_http_methods(["POST"])
def api_run_automation_task(request):
    """手动执行自动化任务"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        data = request.POST

    task_type = data.get('task_type')
    account_id = data.get('account_id')

    if not task_type:
        return JsonResponse({'error': '请指定任务类型'}, status=400)

    try:
        from .automation import (
            ReportGenerator, RiskMonitor, PriceMonitor,
            StrategyPerformanceUpdater, TradePlanChecker
        )

        account = None
        if account_id:
            try:
                account = Account.objects.get(id=account_id, owner=request.user)
            except Account.DoesNotExist:
                return JsonResponse({'error': '账户不存在'}, status=404)

        result = {'success': True, 'task': task_type, 'details': {}}

        if task_type == 'daily_report':
            generator = ReportGenerator(account)
            reports = generator.generate_daily_report()
            if reports:
                report_count = len(reports) if isinstance(reports, list) else 1
                result['details']['report_count'] = report_count
                result['message'] = f'已生成 {report_count} 份日报'
            else:
                result['message'] = '无需生成日报（无交易或已存在）'

        elif task_type == 'monthly_report':
            generator = ReportGenerator(account)
            reports = generator.generate_monthly_report()
            if reports:
                report_count = len(reports) if isinstance(reports, list) else 1
                result['details']['report_count'] = report_count
                result['message'] = f'已生成 {report_count} 份月报'
            else:
                result['message'] = '无需生成月报（无数据或已存在）'

        elif task_type == 'risk_snapshot':
            monitor = RiskMonitor()
            snapshots = monitor.update_risk_snapshot(account)
            result['details']['snapshot_count'] = len(snapshots)
            result['message'] = f'已更新 {len(snapshots)} 个风险快照'

        elif task_type == 'risk_check':
            monitor = RiskMonitor()
            alerts = monitor.check_all_rules(account)
            result['details']['alert_count'] = len(alerts)
            if alerts:
                result['message'] = f'触发了 {len(alerts)} 个风险警告'
            else:
                result['message'] = '风险检查通过，无异常'

        elif task_type == 'sync_positions':
            from .signals import sync_positions_for_account
            # 手动同步持仓
            from .models import TradeLog, Position
            from decimal import Decimal

            if not account:
                return JsonResponse({'error': '同步持仓需要指定账户'}, status=400)

            # 简化版同步（完整版在management command中）
            trades = TradeLog.objects.filter(
                account=account,
                status='filled'
            ).count()
            positions = Position.objects.filter(account=account).count()

            result['details']['trade_count'] = trades
            result['details']['position_count'] = positions
            result['message'] = f'账户共有 {trades} 条交易，{positions} 个持仓'

        elif task_type == 'strategy_performance':
            updater = StrategyPerformanceUpdater()
            metrics = updater.update_all_strategies()
            result['details']['metric_count'] = len(metrics)
            result['message'] = f'已更新 {len(metrics)} 个策略绩效'

        elif task_type == 'expire_plans':
            checker = TradePlanChecker()
            expired = checker.expire_old_plans()
            result['details']['expired_count'] = expired
            result['message'] = f'已过期 {expired} 个交易计划'

        elif task_type == 'expire_alerts':
            monitor = PriceMonitor()
            expired = monitor.check_expired_alerts()
            result['details']['expired_count'] = expired
            result['message'] = f'已过期 {expired} 个价格提醒'

        else:
            return JsonResponse({'error': f'未知任务类型: {task_type}'}, status=400)

        return JsonResponse(result)

    except Exception as e:
        logger.exception('自动化任务执行失败')
        return JsonResponse({
            'success': False,
            'error': '服务器内部错误'
        }, status=500)


def api_automation_status(request):
    """获取自动化状态"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    from .models import DailyReport, MonthlyReport, RiskSnapshot, RiskAlert

    # 获取统计数据
    today = timezone.now().date()

    daily_reports_today = DailyReport.objects.filter(
        account__owner=request.user,
        report_date=today
    ).count()

    recent_snapshots = RiskSnapshot.objects.filter(
        account__owner=request.user,
        snapshot_date=today
    ).count()

    active_alerts = RiskAlert.objects.filter(
        account__owner=request.user,
        status='active'
    ).count()

    positions = Position.objects.filter(
        account__owner=request.user
    ).count()

    trades_today = TradeLog.objects.filter(
        account__owner=request.user,
        trade_time__date=today,
        status='filled'
    ).count()

    return JsonResponse({
        'today': today.strftime('%Y-%m-%d'),
        'daily_reports_today': daily_reports_today,
        'recent_snapshots': recent_snapshots,
        'active_alerts': active_alerts,
        'positions': positions,
        'trades_today': trades_today,
    })


def health_check(request):
    """健康检查端点"""
    return JsonResponse({'status': 'ok'})
