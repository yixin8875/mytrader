from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, Avg, Min, Max
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from datetime import timedelta, datetime
import json
import logging
from .models import Account, TradeLog, DailyReport, Position, Strategy, Notification, PriceAlert, Symbol, TradeTag, UserPreference, RiskRule, RiskSnapshot
from .analytics import TradeAnalytics
from .notifications import NotificationService
from .utils import api_login_required, parse_date, parse_date_range, check_webhook_rate_limit, verify_webhook_signature, rate_limit

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


@rate_limit(max_requests=10, window_seconds=60)
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


@rate_limit(max_requests=10, window_seconds=60)
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


@rate_limit(max_requests=10, window_seconds=60)
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


@rate_limit(max_requests=10, window_seconds=60)
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


@rate_limit(max_requests=10, window_seconds=60)
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
    limit = min(int(request.GET.get('limit', 50)), 100)  # 最大100条
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


def heatmap_api(request):
    """盈亏热力图数据 API"""
    if not request.user.is_authenticated:
        return JsonResponse({'error': '未登录'}, status=401)

    account_id = request.GET.get('account_id')
    year = request.GET.get('year', str(timezone.now().year))

    try:
        year = int(year)
    except ValueError:
        return JsonResponse({'error': '无效的年份'}, status=400)

    # 获取日报数据
    queryset = DailyReport.objects.filter(
        account__owner=request.user,
        report_date__year=year
    )

    if account_id:
        queryset = queryset.filter(account_id=account_id)

    # 按日期聚合盈亏
    daily_pnl = queryset.values('report_date').annotate(
        pnl=Sum('profit_loss')
    ).order_by('report_date')

    # 转换为热力图格式 [[日期, 盈亏值], ...]
    data = []
    for item in daily_pnl:
        data.append([
            item['report_date'].strftime('%Y-%m-%d'),
            float(item['pnl'] or 0)
        ])

    # 获取用户账户列表
    accounts = list(Account.objects.filter(owner=request.user).values('id', 'name'))

    return JsonResponse({
        'year': year,
        'data': data,
        'accounts': accounts,
    })


# ============ 交易分析深化 API ============

def trade_analysis_page(request):
    """交易分析页面"""
    if not request.user.is_authenticated:
        return redirect('/admin/login/')

    # 获取用户的标签
    tags = TradeTag.objects.filter(owner=request.user).order_by('category', 'name')
    accounts = Account.objects.filter(owner=request.user)

    return render(request, 'trading/trade_analysis.html', {
        'tags': tags,
        'accounts': accounts,
    })


@login_required
def api_tag_analysis(request):
    """标签胜率分析 API"""
    account_id = request.GET.get('account_id')

    # 基础查询
    trades = TradeLog.objects.filter(
        account__owner=request.user,
        status='filled'
    )
    if account_id:
        trades = trades.filter(account_id=account_id)

    # 获取用户所有标签的统计
    tags = TradeTag.objects.filter(owner=request.user)
    result = []

    for tag in tags:
        tag_trades = trades.filter(tags=tag)
        total = tag_trades.count()
        if total == 0:
            continue

        wins = tag_trades.filter(profit_loss__gt=0).count()
        losses = tag_trades.filter(profit_loss__lt=0).count()
        total_pnl = tag_trades.aggregate(pnl=Sum('profit_loss'))['pnl'] or 0
        avg_pnl = tag_trades.aggregate(avg=Avg('profit_loss'))['avg'] or 0

        # 计算平均盈利和平均亏损
        avg_win = tag_trades.filter(profit_loss__gt=0).aggregate(avg=Avg('profit_loss'))['avg'] or 0
        avg_loss = tag_trades.filter(profit_loss__lt=0).aggregate(avg=Avg('profit_loss'))['avg'] or 0

        result.append({
            'id': tag.id,
            'name': tag.name,
            'category': tag.get_category_display(),
            'color': tag.color,
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / total * 100, 1) if total > 0 else 0,
            'total_pnl': float(total_pnl),
            'avg_pnl': float(avg_pnl),
            'avg_win': float(avg_win),
            'avg_loss': float(avg_loss),
            'profit_factor': round(abs(avg_win / avg_loss), 2) if avg_loss != 0 else None,
        })

    # 按胜率排序
    result.sort(key=lambda x: x['win_rate'], reverse=True)

    # 限制返回数量（最多50个标签）
    return JsonResponse({'tags': result[:50]})


@login_required
def api_holding_analysis(request):
    """持仓时间分析 API"""
    account_id = request.GET.get('account_id')

    trades = TradeLog.objects.filter(
        account__owner=request.user,
        status='filled',
        holding_minutes__isnull=False
    )
    if account_id:
        trades = trades.filter(account_id=account_id)

    if not trades.exists():
        return JsonResponse({'periods': [], 'distribution': []})

    # 按持仓时间分组统计
    periods = [
        ('< 5分钟', 0, 5),
        ('5-15分钟', 5, 15),
        ('15-30分钟', 15, 30),
        ('30-60分钟', 30, 60),
        ('1-4小时', 60, 240),
        ('4-8小时', 240, 480),
        ('1天', 480, 1440),
        ('1-3天', 1440, 4320),
        ('3天以上', 4320, 999999),
    ]

    result = []
    for label, min_mins, max_mins in periods:
        period_trades = trades.filter(
            holding_minutes__gte=min_mins,
            holding_minutes__lt=max_mins
        )
        total = period_trades.count()
        if total == 0:
            continue

        wins = period_trades.filter(profit_loss__gt=0).count()
        total_pnl = period_trades.aggregate(pnl=Sum('profit_loss'))['pnl'] or 0
        avg_pnl = period_trades.aggregate(avg=Avg('profit_loss'))['avg'] or 0

        result.append({
            'period': label,
            'total_trades': total,
            'wins': wins,
            'win_rate': round(wins / total * 100, 1),
            'total_pnl': float(total_pnl),
            'avg_pnl': float(avg_pnl),
        })

    # 持仓时间分布（用于图表）
    distribution = []
    for trade in trades.values('holding_minutes', 'profit_loss')[:500]:
        distribution.append({
            'minutes': trade['holding_minutes'],
            'pnl': float(trade['profit_loss']),
        })

    return JsonResponse({
        'periods': result,
        'distribution': distribution,
        'best_period': max(result, key=lambda x: x['win_rate'])['period'] if result else None,
    })


@login_required
def api_drawdown_analysis(request):
    """回撤分析 API"""
    account_id = request.GET.get('account_id')

    # 获取日报数据计算回撤
    reports = DailyReport.objects.filter(account__owner=request.user).order_by('report_date')
    if account_id:
        reports = reports.filter(account_id=account_id)

    if not reports.exists():
        return JsonResponse({'drawdowns': [], 'max_drawdown': None, 'problem_trades': []})

    # 计算回撤序列
    peak = 0
    drawdowns = []
    max_dd = 0
    max_dd_start = None
    max_dd_end = None
    dd_start = None

    for report in reports:
        balance = float(report.ending_balance)
        if balance > peak:
            peak = balance
            dd_start = report.report_date

        if peak > 0:
            dd = (peak - balance) / peak * 100
            drawdowns.append({
                'date': report.report_date.strftime('%Y-%m-%d'),
                'drawdown': round(dd, 2),
                'balance': balance,
                'peak': peak,
            })

            if dd > max_dd:
                max_dd = dd
                max_dd_start = dd_start
                max_dd_end = report.report_date

    # 获取最大回撤期间的交易
    problem_trades = []
    if max_dd_start and max_dd_end:
        trades = TradeLog.objects.filter(
            account__owner=request.user,
            status='filled',
            trade_time__date__gte=max_dd_start,
            trade_time__date__lte=max_dd_end,
            profit_loss__lt=0
        ).select_related('symbol').prefetch_related('tags').order_by('profit_loss')[:10]

        if account_id:
            trades = trades.filter(account_id=account_id)

        for t in trades:
            problem_trades.append({
                'id': t.id,
                'date': t.trade_time.strftime('%Y-%m-%d %H:%M'),
                'symbol': t.symbol.code,
                'side': t.get_side_display(),
                'profit_loss': float(t.profit_loss),
                'tags': [tag.name for tag in t.tags.all()],
            })

    return JsonResponse({
        'drawdowns': drawdowns[-90:],  # 最近90天
        'max_drawdown': {
            'value': round(max_dd, 2),
            'start_date': max_dd_start.strftime('%Y-%m-%d') if max_dd_start else None,
            'end_date': max_dd_end.strftime('%Y-%m-%d') if max_dd_end else None,
        } if max_dd > 0 else None,
        'problem_trades': problem_trades,
    })


@login_required
def api_correlation_analysis(request):
    """持仓相关性分析 API"""
    account_id = request.GET.get('account_id')

    # 获取当前持仓（使用 select_related 避免 N+1 查询）
    positions = Position.objects.filter(
        account__owner=request.user, quantity__gt=0
    ).select_related('symbol')
    if account_id:
        positions = positions.filter(account_id=account_id)

    if positions.count() < 2:
        return JsonResponse({'correlation_matrix': [], 'concentration': None})

    # 按标的类型分组统计
    type_stats = {}
    total_value = 0

    for pos in positions:
        symbol_type = pos.symbol.get_symbol_type_display()
        value = float(pos.market_value) if pos.market_value else 0
        total_value += value

        if symbol_type not in type_stats:
            type_stats[symbol_type] = {'value': 0, 'count': 0, 'symbols': []}
        type_stats[symbol_type]['value'] += value
        type_stats[symbol_type]['count'] += 1
        type_stats[symbol_type]['symbols'].append(pos.symbol.code)

    # 计算集中度
    concentration = []
    for type_name, stats in type_stats.items():
        ratio = stats['value'] / total_value * 100 if total_value > 0 else 0
        concentration.append({
            'type': type_name,
            'value': stats['value'],
            'ratio': round(ratio, 1),
            'count': stats['count'],
            'symbols': stats['symbols'][:5],  # 最多显示5个
        })

    concentration.sort(key=lambda x: x['ratio'], reverse=True)

    # 计算单一标的集中度
    symbol_concentration = []
    for pos in positions:
        value = float(pos.market_value) if pos.market_value else 0
        ratio = value / total_value * 100 if total_value > 0 else 0
        symbol_concentration.append({
            'symbol': pos.symbol.code,
            'name': pos.symbol.name,
            'value': value,
            'ratio': round(ratio, 1),
        })

    symbol_concentration.sort(key=lambda x: x['ratio'], reverse=True)

    # 风险提示
    warnings = []
    # 单一标的超过30%
    for item in symbol_concentration:
        if item['ratio'] > 30:
            warnings.append(f"{item['symbol']} 占比 {item['ratio']}%，建议分散投资")
    # 单一类型超过50%
    for item in concentration:
        if item['ratio'] > 50:
            warnings.append(f"{item['type']} 类资产占比 {item['ratio']}%，建议分散配置")

    return JsonResponse({
        'type_concentration': concentration,
        'symbol_concentration': symbol_concentration[:10],
        'total_value': total_value,
        'warnings': warnings,
    })


# ============ 风控增强 API ============

def risk_dashboard_page(request):
    """风控仪表盘页面"""
    if not request.user.is_authenticated:
        return redirect('/admin/login/')

    accounts = Account.objects.filter(owner=request.user)
    symbols = Symbol.objects.filter(is_active=True)

    return render(request, 'trading/risk_dashboard.html', {
        'accounts': accounts,
        'symbols': symbols,
    })


@login_required
def api_position_calculator(request):
    """仓位计算器 API"""
    try:
        account_balance = float(request.GET.get('balance', 0))
        risk_percent = float(request.GET.get('risk_percent', 2))  # 默认2%风险
        entry_price = float(request.GET.get('entry_price', 0))
        stop_loss = float(request.GET.get('stop_loss', 0))
        symbol_id = request.GET.get('symbol_id')

        if not all([account_balance, entry_price, stop_loss]):
            return JsonResponse({'error': '请填写完整参数'}, status=400)

        # 计算每股风险
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share == 0:
            return JsonResponse({'error': '止损价不能等于入场价'}, status=400)

        # 最大风险金额
        max_risk_amount = account_balance * (risk_percent / 100)

        # 合约乘数
        contract_size = 1
        if symbol_id:
            try:
                symbol = Symbol.objects.get(id=symbol_id)
                if symbol.symbol_type in ['futures', 'index']:
                    contract_size = float(symbol.contract_size)
            except Symbol.DoesNotExist:
                pass

        # 计算建仓数量
        risk_per_unit = risk_per_share * contract_size
        position_size = int(max_risk_amount / risk_per_unit)

        # 计算相关数据
        total_cost = position_size * entry_price * contract_size
        actual_risk = position_size * risk_per_unit
        position_ratio = (total_cost / account_balance * 100) if account_balance > 0 else 0

        return JsonResponse({
            'position_size': position_size,
            'max_risk_amount': round(max_risk_amount, 2),
            'actual_risk': round(actual_risk, 2),
            'total_cost': round(total_cost, 2),
            'position_ratio': round(position_ratio, 2),
            'risk_per_unit': round(risk_per_unit, 2),
            'contract_size': contract_size,
        })

    except (ValueError, TypeError) as e:
        return JsonResponse({'error': '参数格式错误'}, status=400)


@login_required
def api_risk_exposure(request):
    """风险敞口 API"""
    account_id = request.GET.get('account_id')

    # 获取持仓
    positions = Position.objects.filter(
        account__owner=request.user,
        quantity__gt=0
    ).select_related('symbol', 'account')

    if account_id:
        positions = positions.filter(account_id=account_id)

    # 获取账户总资产
    accounts = Account.objects.filter(owner=request.user)
    if account_id:
        accounts = accounts.filter(id=account_id)
    total_balance = float(accounts.aggregate(total=Sum('current_balance'))['total'] or 0)

    # 计算风险敞口
    exposure_data = []
    total_exposure = 0
    total_unrealized_pnl = 0

    for pos in positions:
        market_value = float(pos.market_value) if pos.market_value else 0
        unrealized_pnl = float(pos.profit_loss) if pos.profit_loss else 0
        exposure_ratio = (market_value / total_balance * 100) if total_balance > 0 else 0

        total_exposure += market_value
        total_unrealized_pnl += unrealized_pnl

        exposure_data.append({
            'account': pos.account.name,
            'symbol': pos.symbol.code,
            'symbol_name': pos.symbol.name,
            'quantity': float(pos.quantity),
            'avg_price': float(pos.avg_price),
            'current_price': float(pos.current_price) if pos.current_price else None,
            'market_value': market_value,
            'unrealized_pnl': unrealized_pnl,
            'pnl_ratio': float(pos.profit_loss_ratio) if pos.profit_loss_ratio else 0,
            'exposure_ratio': round(exposure_ratio, 2),
        })

    # 风险指标
    exposure_ratio = (total_exposure / total_balance * 100) if total_balance > 0 else 0

    # 获取最新风险快照
    latest_snapshot = RiskSnapshot.objects.filter(
        account__owner=request.user
    ).order_by('-snapshot_date').first()

    risk_metrics = {
        'total_balance': total_balance,
        'total_exposure': total_exposure,
        'exposure_ratio': round(exposure_ratio, 2),
        'unrealized_pnl': total_unrealized_pnl,
        'cash_available': total_balance - total_exposure,
        'position_count': len(exposure_data),
    }

    if latest_snapshot:
        risk_metrics.update({
            'current_drawdown': float(latest_snapshot.current_drawdown_percent),
            'max_drawdown': float(latest_snapshot.max_drawdown_percent),
            'consecutive_losses': latest_snapshot.consecutive_losses,
            'risk_score': latest_snapshot.risk_score,
        })

    return JsonResponse({
        'positions': exposure_data,
        'metrics': risk_metrics,
    })


@login_required
def api_stop_loss_alerts(request):
    """止损止盈提醒列表 API"""
    # 获取用户的价格提醒
    alerts = PriceAlert.objects.filter(
        owner=request.user,
        status='active'
    ).select_related('symbol', 'position').order_by('-created_at')

    result = []
    for alert in alerts:
        result.append({
            'id': alert.id,
            'symbol': alert.symbol.code,
            'symbol_name': alert.symbol.name,
            'alert_type': alert.alert_type,
            'alert_type_display': alert.get_alert_type_display(),
            'condition': alert.get_condition_display(),
            'target_price': float(alert.target_price),
            'last_price': float(alert.last_price) if alert.last_price else None,
            'position_id': alert.position_id,
            'notes': alert.notes,
            'created_at': alert.created_at.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({'alerts': result})


@login_required
@require_http_methods(['POST'])
def api_create_stop_alert(request):
    """创建止损止盈提醒 API"""
    try:
        data = json.loads(request.body)
        symbol_id = data.get('symbol_id')
        position_id = data.get('position_id')
        alert_type = data.get('alert_type', 'price')  # price, stop_loss, take_profit
        condition = data.get('condition')  # above, below
        target_price = data.get('target_price')
        notes = data.get('notes', '')

        if not all([symbol_id, condition, target_price]):
            return JsonResponse({'error': '请填写完整参数'}, status=400)

        symbol = Symbol.objects.get(id=symbol_id)
        position = None
        if position_id:
            position = Position.objects.get(id=position_id, account__owner=request.user)

        alert = PriceAlert.objects.create(
            owner=request.user,
            symbol=symbol,
            position=position,
            alert_type=alert_type,
            condition=condition,
            target_price=target_price,
            notes=notes,
            trigger_once=True,
        )

        type_display = dict(PriceAlert.ALERT_TYPE_CHOICES).get(alert_type, '价格提醒')
        return JsonResponse({
            'status': 'success',
            'alert_id': alert.id,
            'message': f'已创建 {symbol.code} {type_display}'
        })

    except Symbol.DoesNotExist:
        return JsonResponse({'error': '标的不存在'}, status=404)
    except Position.DoesNotExist:
        return JsonResponse({'error': '持仓不存在'}, status=404)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '参数格式错误'}, status=400)


@login_required
def api_risk_rules_status(request):
    """风险规则状态 API"""
    account_id = request.GET.get('account_id')

    rules = RiskRule.objects.filter(
        account__owner=request.user,
        is_active=True
    ).select_related('account')

    if account_id:
        rules = rules.filter(account_id=account_id)

    # 预先批量查询所有账户的数据，避免 N+1 查询
    today = timezone.now().date()
    account_ids = list(rules.values_list('account_id', flat=True).distinct())

    # 批量查询今日盈亏
    daily_pnl_map = {}
    daily_pnl_qs = TradeLog.objects.filter(
        account_id__in=account_ids,
        trade_time__date=today,
        status='filled'
    ).values('account_id').annotate(pnl=Sum('profit_loss'))
    for item in daily_pnl_qs:
        daily_pnl_map[item['account_id']] = item['pnl'] or 0

    # 批量查询持仓市值
    position_map = {}
    position_qs = Position.objects.filter(
        account_id__in=account_ids,
        quantity__gt=0
    ).values('account_id').annotate(total=Sum('market_value'))
    for item in position_qs:
        position_map[item['account_id']] = item['total'] or 0

    # 批量查询今日交易次数
    trade_count_map = {}
    trade_count_qs = TradeLog.objects.filter(
        account_id__in=account_ids,
        trade_time__date=today
    ).values('account_id').annotate(count=Count('id'))
    for item in trade_count_qs:
        trade_count_map[item['account_id']] = item['count']

    result = []
    for rule in rules:
        # 使用预查询的数据
        current_value = 0
        if rule.rule_type == 'daily_loss_limit':
            today_pnl = daily_pnl_map.get(rule.account_id, 0)
            current_value = abs(float(today_pnl)) if today_pnl < 0 else 0
        elif rule.rule_type == 'max_position_ratio':
            total_position = position_map.get(rule.account_id, 0)
            if rule.account.current_balance > 0:
                current_value = float(total_position) / float(rule.account.current_balance) * 100
        elif rule.rule_type == 'daily_trade_limit':
            current_value = trade_count_map.get(rule.account_id, 0)

        threshold = float(rule.threshold_value)
        usage_ratio = (current_value / threshold * 100) if threshold > 0 else 0

        result.append({
            'id': rule.id,
            'account': rule.account.name,
            'name': rule.name,
            'rule_type': rule.get_rule_type_display(),
            'level': rule.get_level_display(),
            'threshold': rule.get_threshold_display(),
            'current_value': round(current_value, 2),
            'usage_ratio': round(usage_ratio, 1),
            'is_triggered': usage_ratio >= 100,
        })

    return JsonResponse({'rules': result})


# ==================== 数据管理 ====================

@login_required
def data_management_page(request):
    """数据管理页面"""
    from quant.models import StockData

    # 统计信息
    stock_count = StockData.objects.values('symbol').distinct().count()
    record_count = StockData.objects.count()
    date_range = StockData.objects.aggregate(
        min_date=Min('date'),
        max_date=Max('date')
    )

    context = {
        'stock_count': stock_count,
        'record_count': record_count,
        'date_range': date_range,
    }
    return render(request, 'trading/data_management.html', context)


@login_required
@require_http_methods(['POST'])
def api_backup_database(request):
    """数据库备份 API"""
    import os
    from io import StringIO
    from django.conf import settings
    from django.core.management import call_command

    try:
        data = json.loads(request.body)
        backup_type = data.get('type', 'full')

        # 白名单验证备份类型
        allowed_types = {'full': ['trading', 'quant'], 'trading': ['trading'], 'quant': ['quant']}
        if backup_type not in allowed_types:
            return JsonResponse({'error': '无效的备份类型'}, status=400)

        apps = allowed_types[backup_type]

        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)

        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f'backup_{backup_type}_{timestamp}.json'
        filepath = os.path.join(backup_dir, filename)

        # 使用 Django call_command 代替 subprocess（更安全）
        output = StringIO()
        call_command('dumpdata', *apps, indent=2, output=filepath, stdout=output)

        file_size = os.path.getsize(filepath)
        return JsonResponse({
            'status': 'success',
            'filename': filename,
            'size': file_size,
            'path': filepath,
            'message': f'备份成功，文件大小: {file_size / 1024:.1f} KB'
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(['POST'])
def api_restore_database(request):
    """数据库恢复 API"""
    import os
    import re
    import uuid
    from io import StringIO
    from django.conf import settings
    from django.core.management import call_command

    try:
        if 'file' not in request.FILES:
            return JsonResponse({'error': '请上传备份文件'}, status=400)

        uploaded_file = request.FILES['file']
        if not uploaded_file.name.endswith('.json'):
            return JsonResponse({'error': '仅支持JSON格式的备份文件'}, status=400)

        # 使用安全的文件名（UUID）避免路径遍历攻击
        backup_dir = os.path.join(settings.BASE_DIR, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        safe_filename = f'restore_{uuid.uuid4().hex}.json'
        filepath = os.path.join(backup_dir, safe_filename)

        with open(filepath, 'wb+') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        try:
            # 使用 Django call_command 代替 subprocess（更安全）
            output = StringIO()
            call_command('loaddata', filepath, stdout=output)
        finally:
            # 确保清理临时文件
            if os.path.exists(filepath):
                os.remove(filepath)

        return JsonResponse({
            'status': 'success',
            'message': '数据恢复成功'
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_list_backups(request):
    """列出备份文件 API"""
    import os
    from django.conf import settings

    backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    if not os.path.exists(backup_dir):
        return JsonResponse({'backups': []})

    backups = []
    for filename in os.listdir(backup_dir):
        if filename.endswith('.json') and filename.startswith('backup_'):
            filepath = os.path.join(backup_dir, filename)
            stat = os.stat(filepath)
            backups.append({
                'filename': filename,
                'size': stat.st_size,
                'created_at': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            })

    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return JsonResponse({'backups': backups})


@login_required
def api_download_backup(request, filename):
    """下载备份文件 API"""
    import os
    from django.conf import settings

    # 安全检查：防止路径遍历攻击
    safe_filename = os.path.basename(filename)
    if not safe_filename.startswith('backup_') or not safe_filename.endswith('.json'):
        return JsonResponse({'error': '无效的文件名'}, status=400)

    backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    filepath = os.path.join(backup_dir, safe_filename)

    # 确保文件路径在备份目录内
    if not os.path.realpath(filepath).startswith(os.path.realpath(backup_dir)):
        return JsonResponse({'error': '无效的文件路径'}, status=400)

    if not os.path.exists(filepath):
        return JsonResponse({'error': '文件不存在'}, status=404)

    with open(filepath, 'rb') as f:
        response = HttpResponse(f.read(), content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{safe_filename}"'
        return response


@login_required
@require_http_methods(['POST'])
def api_delete_backup(request, filename):
    """删除备份文件 API"""
    import os
    from django.conf import settings

    # 安全检查：防止路径遍历攻击
    safe_filename = os.path.basename(filename)
    if not safe_filename.startswith('backup_') or not safe_filename.endswith('.json'):
        return JsonResponse({'error': '无效的文件名'}, status=400)

    backup_dir = os.path.join(settings.BASE_DIR, 'backups')
    filepath = os.path.join(backup_dir, safe_filename)

    # 确保文件路径在备份目录内
    if not os.path.realpath(filepath).startswith(os.path.realpath(backup_dir)):
        return JsonResponse({'error': '无效的文件路径'}, status=400)

    if not os.path.exists(filepath):
        return JsonResponse({'error': '文件不存在'}, status=404)

    os.remove(filepath)
    return JsonResponse({'status': 'success', 'message': '删除成功'})


@login_required
def api_data_quality_check(request):
    """数据质量检查 API"""
    from quant.models import StockData
    from quant.data_fetcher import TradingCalendar
    from django.db.models import Count, Min, Max

    symbol = request.GET.get('symbol')

    issues = []

    if symbol:
        # 检查单个股票
        data = StockData.objects.filter(symbol=symbol).order_by('date')
        if not data.exists():
            return JsonResponse({'issues': [{'type': 'no_data', 'message': f'{symbol} 无数据'}]})

        dates = list(data.values_list('date', flat=True))

        # 1. 检查缺失交易日
        if len(dates) >= 2:
            trade_dates = TradingCalendar.get_trade_dates_range(dates[0], dates[-1])
            missing_dates = set(trade_dates) - set(dates)
            if missing_dates:
                issues.append({
                    'type': 'missing_dates',
                    'symbol': symbol,
                    'count': len(missing_dates),
                    'dates': sorted([d.strftime('%Y-%m-%d') for d in list(missing_dates)[:10]]),
                    'message': f'{symbol} 缺失 {len(missing_dates)} 个交易日数据'
                })

        # 2. 检查异常价格
        for record in data:
            # 价格为0或负数
            if record.close <= 0 or record.open <= 0:
                issues.append({
                    'type': 'invalid_price',
                    'symbol': symbol,
                    'date': record.date.strftime('%Y-%m-%d'),
                    'message': f'{symbol} {record.date} 价格异常 (close={record.close})'
                })
            # 涨跌幅超过20%（可能是除权未复权）
            if record.high > 0 and record.low > 0:
                daily_range = (record.high - record.low) / record.low * 100
                if daily_range > 25:
                    issues.append({
                        'type': 'extreme_volatility',
                        'symbol': symbol,
                        'date': record.date.strftime('%Y-%m-%d'),
                        'message': f'{symbol} {record.date} 日内波动异常 ({daily_range:.1f}%)'
                    })
            # 成交量为0
            if record.volume == 0:
                issues.append({
                    'type': 'zero_volume',
                    'symbol': symbol,
                    'date': record.date.strftime('%Y-%m-%d'),
                    'message': f'{symbol} {record.date} 成交量为0'
                })
    else:
        # 检查所有股票概览
        symbols = StockData.objects.values('symbol').annotate(
            count=Count('id'),
            min_date=Min('date'),
            max_date=Max('date')
        )

        for s in symbols:
            # 检查数据连续性
            expected_days = (s['max_date'] - s['min_date']).days * 0.7  # 约70%是交易日
            if s['count'] < expected_days * 0.8:  # 数据量不足预期的80%
                issues.append({
                    'type': 'incomplete_data',
                    'symbol': s['symbol'],
                    'count': s['count'],
                    'expected': int(expected_days),
                    'message': f"{s['symbol']} 数据可能不完整 ({s['count']}/{int(expected_days)})"
                })

    return JsonResponse({
        'issues': issues[:50],  # 最多返回50条
        'total_issues': len(issues)
    })


@login_required
def api_data_sources(request):
    """获取数据源配置 API"""
    # 支持的数据源
    sources = [
        {
            'id': 'akshare',
            'name': 'AkShare',
            'description': '免费开源的A股数据接口',
            'status': 'active',
            'markets': ['A股'],
            'features': ['日线', '分钟线', '财务数据', '实时行情'],
        },
        {
            'id': 'tushare',
            'name': 'Tushare',
            'description': '需要积分的专业金融数据接口',
            'status': 'available',
            'markets': ['A股', '港股', '美股'],
            'features': ['日线', '分钟线', '财务数据', '基本面'],
            'config_required': ['token'],
        },
        {
            'id': 'baostock',
            'name': 'BaoStock',
            'description': '免费的证券数据接口',
            'status': 'available',
            'markets': ['A股'],
            'features': ['日线', '分钟线', '指数'],
        },
    ]
    return JsonResponse({'sources': sources})


# ==================== 自动化扩展 ====================

@login_required
def automation_extended_page(request):
    """自动化扩展页面"""
    from .models import Webhook, ScheduledReport, StrategySignal

    webhooks = Webhook.objects.filter(owner=request.user)
    reports = ScheduledReport.objects.filter(owner=request.user)
    signals = StrategySignal.objects.filter(owner=request.user)[:20]

    context = {
        'webhooks': webhooks,
        'reports': reports,
        'signals': signals,
    }
    return render(request, 'trading/automation_extended.html', context)


@login_required
def api_strategy_signals(request):
    """策略信号列表 API"""
    from .models import StrategySignal

    signals = StrategySignal.objects.filter(owner=request.user).order_by('-created_at')[:50]
    result = [{
        'id': s.id,
        'strategy_name': s.strategy_name,
        'symbol': s.symbol,
        'signal_type': s.signal_type,
        'signal_type_display': s.get_signal_type_display(),
        'source': s.get_source_display(),
        'price': float(s.price) if s.price else None,
        'quantity': s.quantity,
        'reason': s.reason,
        'is_notified': s.is_notified,
        'created_at': s.created_at.strftime('%Y-%m-%d %H:%M:%S'),
    } for s in signals]

    return JsonResponse({'signals': result})


@login_required
@require_http_methods(['POST'])
def api_create_strategy_signal(request):
    """创建策略信号 API（用于回测等内部调用）"""
    from .models import StrategySignal
    from .notifications import NotificationService

    try:
        data = json.loads(request.body)
        signal = StrategySignal.objects.create(
            owner=request.user,
            strategy_name=data.get('strategy_name', ''),
            symbol=data.get('symbol', ''),
            signal_type=data.get('signal_type', 'buy'),
            source=data.get('source', 'backtest'),
            price=data.get('price'),
            quantity=data.get('quantity'),
            reason=data.get('reason', ''),
            extra_data=data.get('extra_data', {}),
        )

        # 发送通知
        service = NotificationService(request.user)
        service.create_notification(
            notification_type='system',
            title=f'策略信号: {signal.symbol} {signal.get_signal_type_display()}',
            message=f'{signal.strategy_name} 产生 {signal.get_signal_type_display()} 信号，价格: {signal.price or "-"}',
            priority='high',
            extra_data={'signal_id': signal.id}
        )
        signal.is_notified = True
        signal.save(update_fields=['is_notified'])

        return JsonResponse({'status': 'success', 'signal_id': signal.id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


# Webhook APIs
@login_required
def api_webhooks(request):
    """Webhook列表 API"""
    from .models import Webhook

    webhooks = Webhook.objects.filter(owner=request.user)[:50]
    result = [{
        'id': w.id,
        'name': w.name,
        'webhook_type': w.webhook_type,
        'webhook_type_display': w.get_webhook_type_display(),
        'url': w.url,
        'secret_key': w.secret_key,
        'status': w.status,
        'trigger_count': w.trigger_count,
        'last_triggered': w.last_triggered.strftime('%Y-%m-%d %H:%M') if w.last_triggered else None,
    } for w in webhooks]

    return JsonResponse({'webhooks': result})


@login_required
@require_http_methods(['POST'])
def api_create_webhook(request):
    """创建Webhook API"""
    from .models import Webhook

    try:
        data = json.loads(request.body)
        webhook = Webhook.objects.create(
            owner=request.user,
            name=data.get('name', ''),
            webhook_type=data.get('webhook_type', 'inbound'),
            url=data.get('url', ''),
            description=data.get('description', ''),
        )
        return JsonResponse({
            'status': 'success',
            'webhook_id': webhook.id,
            'secret_key': webhook.secret_key,
            'message': f'Webhook创建成功，密钥: {webhook.secret_key}'
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(['POST'])
def api_delete_webhook(request, webhook_id):
    """删除Webhook API"""
    from .models import Webhook

    try:
        webhook = Webhook.objects.get(id=webhook_id, owner=request.user)
        webhook.delete()
        return JsonResponse({'status': 'success'})
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Webhook不存在'}, status=404)


@require_http_methods(['POST'])
@csrf_exempt
def api_webhook_receive(request, secret_key):
    """接收外部Webhook信号 API（无需登录）"""
    from .models import Webhook, WebhookLog, StrategySignal
    from .notifications import NotificationService

    try:
        webhook = Webhook.objects.get(secret_key=secret_key, webhook_type='inbound', status='active')
    except Webhook.DoesNotExist:
        return JsonResponse({'error': 'Invalid webhook'}, status=404)

    # 签名验证（如果提供了签名头）
    valid, error_msg = verify_webhook_signature(request, secret_key)
    if not valid:
        WebhookLog.objects.create(
            webhook=webhook, direction='in', payload={},
            success=False, error_message=f'签名验证失败: {error_msg}'
        )
        return JsonResponse({'error': error_msg}, status=401)

    # 速率限制检查
    allowed, remaining, reset_time = check_webhook_rate_limit(secret_key)
    if not allowed:
        response = JsonResponse({'error': '请求过于频繁，请稍后再试'}, status=429)
        response['X-RateLimit-Remaining'] = '0'
        response['X-RateLimit-Reset'] = str(reset_time)
        return response

    try:
        data = json.loads(request.body)

        # 记录日志
        log = WebhookLog.objects.create(
            webhook=webhook,
            direction='in',
            payload=data,
            success=True,
        )

        # 更新webhook统计
        webhook.last_triggered = timezone.now()
        webhook.trigger_count += 1
        webhook.save(update_fields=['last_triggered', 'trigger_count'])

        # 创建策略信号
        signal = StrategySignal.objects.create(
            owner=webhook.owner,
            strategy_name=data.get('strategy', webhook.name),
            symbol=data.get('symbol', ''),
            signal_type=data.get('action', 'buy'),
            source='webhook',
            price=data.get('price'),
            quantity=data.get('quantity'),
            reason=data.get('message', ''),
            extra_data=data,
        )

        # 发送通知
        service = NotificationService(webhook.owner)
        service.create_notification(
            notification_type='system',
            title=f'Webhook信号: {signal.symbol}',
            message=f'{signal.strategy_name} - {signal.get_signal_type_display()} @ {signal.price or "-"}',
            priority='high',
        )
        signal.is_notified = True
        signal.save(update_fields=['is_notified'])

        return JsonResponse({'status': 'success', 'signal_id': signal.id})

    except json.JSONDecodeError:
        WebhookLog.objects.create(
            webhook=webhook, direction='in', payload={},
            success=False, error_message='Invalid JSON'
        )
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        WebhookLog.objects.create(
            webhook=webhook, direction='in', payload=data if 'data' in dir() else {},
            success=False, error_message=str(e)
        )
        return JsonResponse({'error': str(e)}, status=500)


# 定时报告 APIs
@login_required
def api_scheduled_reports(request):
    """定时报告列表 API"""
    from .models import ScheduledReport

    reports = ScheduledReport.objects.filter(owner=request.user)[:50]
    result = [{
        'id': r.id,
        'name': r.name,
        'report_type': r.report_type,
        'report_type_display': r.get_report_type_display(),
        'frequency': r.frequency,
        'frequency_display': r.get_frequency_display(),
        'send_time': r.send_time.strftime('%H:%M'),
        'send_day': r.send_day,
        'email': r.email,
        'is_active': r.is_active,
        'last_sent': r.last_sent.strftime('%Y-%m-%d %H:%M') if r.last_sent else None,
    } for r in reports]

    return JsonResponse({'reports': result})


@login_required
@require_http_methods(['POST'])
def api_create_scheduled_report(request):
    """创建定时报告 API"""
    from .models import ScheduledReport

    try:
        data = json.loads(request.body)
        report = ScheduledReport.objects.create(
            owner=request.user,
            name=data.get('name', ''),
            report_type=data.get('report_type', 'trade_summary'),
            frequency=data.get('frequency', 'daily'),
            send_time=data.get('send_time', '08:00'),
            send_day=data.get('send_day', 1),
            email=data.get('email', ''),
        )
        return JsonResponse({'status': 'success', 'report_id': report.id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(['POST'])
def api_toggle_scheduled_report(request, report_id):
    """切换定时报告状态 API"""
    from .models import ScheduledReport

    try:
        report = ScheduledReport.objects.get(id=report_id, owner=request.user)
        report.is_active = not report.is_active
        report.save(update_fields=['is_active'])
        return JsonResponse({'status': 'success', 'is_active': report.is_active})
    except ScheduledReport.DoesNotExist:
        return JsonResponse({'error': '报告不存在'}, status=404)


@login_required
@require_http_methods(['POST'])
def api_delete_scheduled_report(request, report_id):
    """删除定时报告 API"""
    from .models import ScheduledReport

    try:
        report = ScheduledReport.objects.get(id=report_id, owner=request.user)
        report.delete()
        return JsonResponse({'status': 'success'})
    except ScheduledReport.DoesNotExist:
        return JsonResponse({'error': '报告不存在'}, status=404)


@login_required
@require_http_methods(['POST'])
def api_send_test_report(request):
    """发送测试报告 API"""
    from django.core.mail import send_mail
    from django.conf import settings

    try:
        data = json.loads(request.body)
        email = data.get('email')

        if not email:
            return JsonResponse({'error': '请提供邮箱地址'}, status=400)

        # 生成测试报告内容
        report_content = f"""
MyTrader 测试报告

用户: {request.user.username}
时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}

这是一封测试邮件，用于验证邮件发送功能是否正常。

如果您收到此邮件，说明邮件配置正确。

---
MyTrader 交易管理系统
        """

        # 尝试发送邮件
        try:
            send_mail(
                subject='[MyTrader] 测试报告',
                message=report_content,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@mytrader.local'),
                recipient_list=[email],
                fail_silently=False,
            )
            return JsonResponse({'status': 'success', 'message': f'测试邮件已发送至 {email}'})
        except Exception as e:
            return JsonResponse({'status': 'warning', 'message': f'邮件发送失败（可能未配置SMTP）: {str(e)}'})

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)




# ==================== 用户偏好设置 API ====================

@login_required
def api_user_preference(request):
    """获取用户偏好设置 API"""
    pref, created = UserPreference.objects.get_or_create(
        user=request.user,
        defaults={'dashboard_layout': UserPreference.get_default_layout()}
    )
    return JsonResponse({
        'theme': pref.theme,
        'dashboard_layout': pref.dashboard_layout or UserPreference.get_default_layout(),
        'shortcuts_enabled': pref.shortcuts_enabled,
        'sidebar_collapsed': pref.sidebar_collapsed,
        'notification_sound': pref.notification_sound,
    })


@login_required
@require_http_methods(['POST'])
def api_update_preference(request):
    """更新用户偏好设置 API"""
    try:
        data = json.loads(request.body)
        pref, created = UserPreference.objects.get_or_create(
            user=request.user,
            defaults={'dashboard_layout': UserPreference.get_default_layout()}
        )

        if 'theme' in data:
            pref.theme = data['theme']
        if 'dashboard_layout' in data:
            pref.dashboard_layout = data['dashboard_layout']
        if 'shortcuts_enabled' in data:
            pref.shortcuts_enabled = data['shortcuts_enabled']
        if 'sidebar_collapsed' in data:
            pref.sidebar_collapsed = data['sidebar_collapsed']
        if 'notification_sound' in data:
            pref.notification_sound = data['notification_sound']

        pref.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(['POST'])
def api_update_dashboard_layout(request):
    """更新仪表盘布局 API"""
    try:
        data = json.loads(request.body)
        modules = data.get('modules', [])

        pref, created = UserPreference.objects.get_or_create(
            user=request.user,
            defaults={'dashboard_layout': UserPreference.get_default_layout()}
        )

        layout = pref.dashboard_layout or {}
        layout['modules'] = modules
        pref.dashboard_layout = layout
        pref.save()

        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)


def settings_page(request):
    """用户设置页面"""
    if not request.user.is_authenticated:
        return redirect('admin:login')

    pref, created = UserPreference.objects.get_or_create(
        user=request.user,
        defaults={'dashboard_layout': UserPreference.get_default_layout()}
    )

    return render(request, 'trading/settings.html', {
        'preference': pref,
        'default_layout': UserPreference.get_default_layout(),
    })
