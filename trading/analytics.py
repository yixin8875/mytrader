"""
交易深度分析模块
提供多维度的交易数据统计和分析
"""
from django.db.models import Sum, Count, Avg, Max, Min, F, Q, Case, When, Value, IntegerField
from django.db.models.functions import TruncDate, TruncHour, TruncWeek, TruncMonth, ExtractHour, ExtractWeekDay
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from collections import defaultdict


class TradeAnalytics:
    """交易分析服务类"""

    def __init__(self, user, account=None, start_date=None, end_date=None):
        """
        初始化分析器
        Args:
            user: 用户对象
            account: 可选，指定账户
            start_date: 开始日期
            end_date: 结束日期
        """
        self.user = user
        self.account = account
        self.start_date = start_date
        self.end_date = end_date or timezone.now().date()

        # 延迟导入避免循环引用
        from .models import TradeLog, Account
        self.TradeLog = TradeLog
        self.Account = Account

    def get_base_queryset(self):
        """获取基础查询集"""
        qs = self.TradeLog.objects.filter(
            account__owner=self.user,
            status='filled'
        )
        if self.account:
            qs = qs.filter(account=self.account)
        if self.start_date:
            qs = qs.filter(trade_time__date__gte=self.start_date)
        if self.end_date:
            qs = qs.filter(trade_time__date__lte=self.end_date)
        return qs

    # ==================== 时段分析 ====================

    def analyze_by_hour(self):
        """按小时分析交易表现"""
        qs = self.get_base_queryset()

        hourly_stats = qs.annotate(
            hour=ExtractHour('trade_time')
        ).values('hour').annotate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
            max_profit=Max('profit_loss', filter=Q(profit_loss__gt=0)),
            max_loss=Min('profit_loss', filter=Q(profit_loss__lt=0)),
        ).order_by('hour')

        results = []
        for stat in hourly_stats:
            total = stat['total_trades']
            wins = stat['win_trades'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0
            results.append({
                'hour': stat['hour'],
                'hour_display': f"{stat['hour']:02d}:00-{stat['hour']:02d}:59",
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': stat['loss_trades'] or 0,
                'win_rate': round(win_rate, 2),
                'total_pnl': float(stat['total_pnl'] or 0),
                'avg_pnl': float(stat['avg_pnl'] or 0),
                'max_profit': float(stat['max_profit'] or 0),
                'max_loss': float(stat['max_loss'] or 0),
            })
        return results

    def analyze_by_weekday(self):
        """按星期几分析交易表现"""
        qs = self.get_base_queryset()

        weekday_stats = qs.annotate(
            weekday=ExtractWeekDay('trade_time')
        ).values('weekday').annotate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
        ).order_by('weekday')

        weekday_names = {
            1: '周日', 2: '周一', 3: '周二', 4: '周三',
            5: '周四', 6: '周五', 7: '周六'
        }

        results = []
        for stat in weekday_stats:
            total = stat['total_trades']
            wins = stat['win_trades'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0
            results.append({
                'weekday': stat['weekday'],
                'weekday_name': weekday_names.get(stat['weekday'], '未知'),
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': stat['loss_trades'] or 0,
                'win_rate': round(win_rate, 2),
                'total_pnl': float(stat['total_pnl'] or 0),
                'avg_pnl': float(stat['avg_pnl'] or 0),
            })
        return results

    # ==================== 品种分析 ====================

    def analyze_by_symbol(self):
        """按交易标的分析表现"""
        qs = self.get_base_queryset()

        symbol_stats = qs.values(
            'symbol__code', 'symbol__name', 'symbol__symbol_type'
        ).annotate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
            total_commission=Sum('commission'),
            avg_quantity=Avg('quantity'),
            first_trade=Min('trade_time'),
            last_trade=Max('trade_time'),
        ).order_by('-total_pnl')

        results = []
        for stat in symbol_stats:
            total = stat['total_trades']
            wins = stat['win_trades'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0
            results.append({
                'symbol_code': stat['symbol__code'],
                'symbol_name': stat['symbol__name'],
                'symbol_type': stat['symbol__symbol_type'],
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': stat['loss_trades'] or 0,
                'win_rate': round(win_rate, 2),
                'total_pnl': float(stat['total_pnl'] or 0),
                'avg_pnl': float(stat['avg_pnl'] or 0),
                'total_commission': float(stat['total_commission'] or 0),
                'net_pnl': float((stat['total_pnl'] or 0) - (stat['total_commission'] or 0)),
                'avg_quantity': float(stat['avg_quantity'] or 0),
                'first_trade': stat['first_trade'],
                'last_trade': stat['last_trade'],
            })
        return results

    def analyze_by_symbol_type(self):
        """按标的类型分析表现"""
        qs = self.get_base_queryset()

        type_stats = qs.values('symbol__symbol_type').annotate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
        ).order_by('-total_pnl')

        type_names = {
            'stock': '股票', 'futures': '期货', 'forex': '外汇',
            'crypto': '加密货币', 'index': '指数', 'commodity': '商品',
            'bond': '债券', 'etf': 'ETF'
        }

        results = []
        for stat in type_stats:
            total = stat['total_trades']
            wins = stat['win_trades'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0
            results.append({
                'symbol_type': stat['symbol__symbol_type'],
                'type_name': type_names.get(stat['symbol__symbol_type'], '其他'),
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': stat['loss_trades'] or 0,
                'win_rate': round(win_rate, 2),
                'total_pnl': float(stat['total_pnl'] or 0),
                'avg_pnl': float(stat['avg_pnl'] or 0),
            })
        return results

    # ==================== 策略分析 ====================

    def analyze_by_strategy(self):
        """按策略分析表现"""
        qs = self.get_base_queryset()

        strategy_stats = qs.values(
            'strategy__id', 'strategy__name'
        ).annotate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
            max_profit=Max('profit_loss', filter=Q(profit_loss__gt=0)),
            max_loss=Min('profit_loss', filter=Q(profit_loss__lt=0)),
            total_commission=Sum('commission'),
        ).order_by('-total_pnl')

        results = []
        for stat in strategy_stats:
            total = stat['total_trades']
            wins = stat['win_trades'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0

            # 计算盈亏比
            avg_win = 0
            avg_loss = 0
            if wins > 0:
                win_qs = qs.filter(strategy_id=stat['strategy__id'], profit_loss__gt=0)
                avg_win = win_qs.aggregate(avg=Avg('profit_loss'))['avg'] or 0
            losses = stat['loss_trades'] or 0
            if losses > 0:
                loss_qs = qs.filter(strategy_id=stat['strategy__id'], profit_loss__lt=0)
                avg_loss = abs(loss_qs.aggregate(avg=Avg('profit_loss'))['avg'] or 0)
            profit_factor = (avg_win / avg_loss) if avg_loss > 0 else 0

            results.append({
                'strategy_id': stat['strategy__id'],
                'strategy_name': stat['strategy__name'] or '无策略',
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': stat['loss_trades'] or 0,
                'win_rate': round(win_rate, 2),
                'total_pnl': float(stat['total_pnl'] or 0),
                'avg_pnl': float(stat['avg_pnl'] or 0),
                'max_profit': float(stat['max_profit'] or 0),
                'max_loss': float(stat['max_loss'] or 0),
                'profit_factor': round(profit_factor, 2),
                'net_pnl': float((stat['total_pnl'] or 0) - (stat['total_commission'] or 0)),
            })
        return results

    # ==================== 方向分析 ====================

    def analyze_by_side(self):
        """按交易方向分析"""
        qs = self.get_base_queryset()

        side_stats = qs.values('side').annotate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
        ).order_by('side')

        side_names = {'buy': '买入/做多', 'sell': '卖出/做空'}

        results = []
        for stat in side_stats:
            total = stat['total_trades']
            wins = stat['win_trades'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0
            results.append({
                'side': stat['side'],
                'side_name': side_names.get(stat['side'], stat['side']),
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': stat['loss_trades'] or 0,
                'win_rate': round(win_rate, 2),
                'total_pnl': float(stat['total_pnl'] or 0),
                'avg_pnl': float(stat['avg_pnl'] or 0),
            })
        return results

    # ==================== 连续统计 ====================

    def analyze_streaks(self):
        """分析连续盈亏记录"""
        qs = self.get_base_queryset().order_by('trade_time')

        trades = list(qs.values('id', 'trade_time', 'profit_loss', 'symbol__code'))

        if not trades:
            return {
                'max_win_streak': 0,
                'max_loss_streak': 0,
                'current_streak': 0,
                'current_streak_type': None,
                'streaks_history': []
            }

        # 计算连续记录
        streaks = []
        current_streak = 0
        current_type = None

        max_win_streak = 0
        max_loss_streak = 0

        for trade in trades:
            pnl = trade['profit_loss'] or 0
            if pnl > 0:
                trade_type = 'win'
            elif pnl < 0:
                trade_type = 'loss'
            else:
                trade_type = 'even'

            if trade_type == current_type:
                current_streak += 1
            else:
                if current_streak > 0 and current_type:
                    streaks.append({
                        'type': current_type,
                        'count': current_streak,
                        'end_date': trade['trade_time']
                    })
                current_streak = 1
                current_type = trade_type

            if trade_type == 'win':
                max_win_streak = max(max_win_streak, current_streak)
            elif trade_type == 'loss':
                max_loss_streak = max(max_loss_streak, current_streak)

        # 添加最后一个连续记录
        if current_streak > 0 and current_type:
            streaks.append({
                'type': current_type,
                'count': current_streak,
                'end_date': trades[-1]['trade_time']
            })

        return {
            'max_win_streak': max_win_streak,
            'max_loss_streak': max_loss_streak,
            'current_streak': current_streak,
            'current_streak_type': current_type,
            'streaks_history': streaks[-10:]  # 最近10次连续记录
        }

    # ==================== 盈亏分布 ====================

    def analyze_pnl_distribution(self):
        """分析盈亏金额分布"""
        qs = self.get_base_queryset()

        trades = list(qs.values_list('profit_loss', flat=True))
        if not trades:
            return {'buckets': [], 'stats': {}}

        trades = [float(t) for t in trades if t is not None]

        # 计算统计数据
        total = len(trades)
        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t < 0]

        stats = {
            'total_trades': total,
            'win_count': len(wins),
            'loss_count': len(losses),
            'even_count': total - len(wins) - len(losses),
            'total_pnl': sum(trades),
            'avg_pnl': sum(trades) / total if total > 0 else 0,
            'avg_win': sum(wins) / len(wins) if wins else 0,
            'avg_loss': sum(losses) / len(losses) if losses else 0,
            'max_win': max(wins) if wins else 0,
            'max_loss': min(losses) if losses else 0,
            'win_rate': len(wins) / total * 100 if total > 0 else 0,
        }

        # 计算盈亏比
        if stats['avg_loss'] != 0:
            stats['profit_factor'] = abs(stats['avg_win'] / stats['avg_loss'])
        else:
            stats['profit_factor'] = 0

        # 计算分布桶
        if trades:
            min_pnl = min(trades)
            max_pnl = max(trades)
            range_pnl = max_pnl - min_pnl

            if range_pnl > 0:
                bucket_size = range_pnl / 10
                buckets = []
                for i in range(10):
                    lower = min_pnl + i * bucket_size
                    upper = min_pnl + (i + 1) * bucket_size
                    count = len([t for t in trades if lower <= t < upper])
                    buckets.append({
                        'range': f'{lower:.0f} ~ {upper:.0f}',
                        'lower': lower,
                        'upper': upper,
                        'count': count,
                        'percent': count / total * 100 if total > 0 else 0
                    })
            else:
                buckets = [{'range': f'{min_pnl:.0f}', 'count': total, 'percent': 100}]
        else:
            buckets = []

        return {'buckets': buckets, 'stats': stats}

    # ==================== 月度分析 ====================

    def analyze_by_month(self):
        """按月分析交易表现"""
        qs = self.get_base_queryset()

        monthly_stats = qs.annotate(
            month=TruncMonth('trade_time')
        ).values('month').annotate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
            total_commission=Sum('commission'),
        ).order_by('-month')

        results = []
        for stat in monthly_stats:
            total = stat['total_trades']
            wins = stat['win_trades'] or 0
            win_rate = (wins / total * 100) if total > 0 else 0
            results.append({
                'month': stat['month'].strftime('%Y-%m') if stat['month'] else '',
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': stat['loss_trades'] or 0,
                'win_rate': round(win_rate, 2),
                'total_pnl': float(stat['total_pnl'] or 0),
                'avg_pnl': float(stat['avg_pnl'] or 0),
                'net_pnl': float((stat['total_pnl'] or 0) - (stat['total_commission'] or 0)),
            })
        return results

    # ==================== 综合摘要 ====================

    def get_summary(self):
        """获取综合分析摘要"""
        qs = self.get_base_queryset()

        # 基础统计
        basic_stats = qs.aggregate(
            total_trades=Count('id'),
            win_trades=Count('id', filter=Q(profit_loss__gt=0)),
            loss_trades=Count('id', filter=Q(profit_loss__lt=0)),
            total_pnl=Sum('profit_loss'),
            avg_pnl=Avg('profit_loss'),
            total_commission=Sum('commission'),
            max_profit=Max('profit_loss', filter=Q(profit_loss__gt=0)),
            max_loss=Min('profit_loss', filter=Q(profit_loss__lt=0)),
            total_quantity=Sum('quantity'),
        )

        total = basic_stats['total_trades'] or 0
        wins = basic_stats['win_trades'] or 0
        losses = basic_stats['loss_trades'] or 0

        # 计算平均盈利和平均亏损
        avg_win = 0
        avg_loss = 0
        if wins > 0:
            avg_win = qs.filter(profit_loss__gt=0).aggregate(avg=Avg('profit_loss'))['avg'] or 0
        if losses > 0:
            avg_loss = abs(qs.filter(profit_loss__lt=0).aggregate(avg=Avg('profit_loss'))['avg'] or 0)

        # 盈亏比
        profit_factor = (float(avg_win) / float(avg_loss)) if avg_loss > 0 else 0

        # 期望值
        win_rate = (wins / total) if total > 0 else 0
        expectancy = (win_rate * float(avg_win)) - ((1 - win_rate) * float(avg_loss))

        # 最佳/最差品种
        symbol_analysis = self.analyze_by_symbol()
        best_symbol = symbol_analysis[0] if symbol_analysis else None
        worst_symbol = symbol_analysis[-1] if len(symbol_analysis) > 1 else None

        # 最佳/最差时段
        hour_analysis = self.analyze_by_hour()
        best_hour = max(hour_analysis, key=lambda x: x['total_pnl']) if hour_analysis else None
        worst_hour = min(hour_analysis, key=lambda x: x['total_pnl']) if hour_analysis else None

        # 连续统计
        streaks = self.analyze_streaks()

        return {
            'basic': {
                'total_trades': total,
                'win_trades': wins,
                'loss_trades': losses,
                'even_trades': total - wins - losses,
                'win_rate': round(wins / total * 100 if total > 0 else 0, 2),
                'total_pnl': float(basic_stats['total_pnl'] or 0),
                'avg_pnl': float(basic_stats['avg_pnl'] or 0),
                'total_commission': float(basic_stats['total_commission'] or 0),
                'net_pnl': float((basic_stats['total_pnl'] or 0) - (basic_stats['total_commission'] or 0)),
                'max_profit': float(basic_stats['max_profit'] or 0),
                'max_loss': float(basic_stats['max_loss'] or 0),
            },
            'ratios': {
                'avg_win': float(avg_win),
                'avg_loss': float(avg_loss),
                'profit_factor': round(profit_factor, 2),
                'expectancy': round(expectancy, 2),
            },
            'best_symbol': best_symbol,
            'worst_symbol': worst_symbol,
            'best_hour': best_hour,
            'worst_hour': worst_hour,
            'streaks': streaks,
        }

    # ==================== 完整报告 ====================

    def get_full_report(self):
        """获取完整分析报告"""
        return {
            'summary': self.get_summary(),
            'by_hour': self.analyze_by_hour(),
            'by_weekday': self.analyze_by_weekday(),
            'by_symbol': self.analyze_by_symbol(),
            'by_symbol_type': self.analyze_by_symbol_type(),
            'by_strategy': self.analyze_by_strategy(),
            'by_side': self.analyze_by_side(),
            'by_month': self.analyze_by_month(),
            'pnl_distribution': self.analyze_pnl_distribution(),
            'streaks': self.analyze_streaks(),
        }
