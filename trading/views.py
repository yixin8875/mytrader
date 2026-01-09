from django.shortcuts import render
from django.http import JsonResponse
from django.db.models import Sum, Count, Avg
from django.db.models.functions import TruncMonth
from django.utils import timezone
from datetime import timedelta
from .models import Account, TradeLog, DailyReport, Position


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
