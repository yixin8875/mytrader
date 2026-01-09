from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, F, DecimalField
from .models import (
    Account, AccountTransaction, Symbol, Strategy, TradeLog, TradeImage, Position,
    DailyReport, MonthlyReport, PerformanceMetrics, TradeReview,
    RiskRule, RiskAlert, RiskSnapshot,
    WatchlistGroup, WatchlistItem, TradePlan, DailyNote,
    Notification, PriceAlert, NotificationSetting, TradeTag
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    """交易账户管理界面"""
    list_display = ['name', 'account_type', 'broker', 'current_balance',
                    'total_profit_loss', 'profit_loss_ratio', 'status', 'owner', 'created_at']
    list_filter = ['account_type', 'status', 'created_at']
    search_fields = ['name', 'broker', 'account_id', 'owner__username']
    readonly_fields = ['created_at', 'updated_at', 'total_profit_loss', 'profit_loss_ratio']
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'account_type', 'broker', 'account_id', 'owner')
        }),
        ('资金信息', {
            'fields': ('initial_balance', 'current_balance', 'available_balance',
                      'total_profit_loss', 'profit_loss_ratio')
        }),
        ('状态', {
            'fields': ('status',)
        }),
        ('其他', {
            'fields': ('notes', 'created_at', 'updated_at')
        }),
    )

    def total_profit_loss(self, obj):
        profit_loss = obj.total_profit_loss
        color = 'green' if profit_loss >= 0 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, f'{profit_loss:.2f}')
    total_profit_loss.short_description = '总盈亏'

    def profit_loss_ratio(self, obj):
        ratio = obj.profit_loss_ratio
        color = 'green' if ratio >= 0 else 'red'
        return format_html('<span style="color: {};">{}%</span>', color, f'{ratio:.2f}')
    profit_loss_ratio.short_description = '盈亏比例'


@admin.register(AccountTransaction)
class AccountTransactionAdmin(admin.ModelAdmin):
    """账户流水管理界面"""
    list_display = ['transaction_time', 'account', 'transaction_type', 'amount_display',
                    'balance_before', 'balance_after', 'trade_log', 'description']
    list_filter = ['transaction_type', 'account', 'transaction_time']
    search_fields = ['account__name', 'description', 'trade_log__order_id']
    readonly_fields = ['balance_before', 'balance_after', 'created_at']
    date_hierarchy = 'transaction_time'
    fieldsets = (
        ('基本信息', {
            'fields': ('account', 'transaction_type', 'amount', 'trade_log')
        }),
        ('余额变动', {
            'fields': ('balance_before', 'balance_after')
        }),
        ('其他', {
            'fields': ('description', 'transaction_time', 'created_at')
        }),
    )

    def amount_display(self, obj):
        color = 'green' if obj.amount >= 0 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, f'{obj.amount:.2f}')
    amount_display.short_description = '金额'

    def has_add_permission(self, request):
        """禁止手动添加流水记录"""
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除流水记录"""
        return False


@admin.register(Symbol)
class SymbolAdmin(admin.ModelAdmin):
    """交易标的管理界面"""
    list_display = ['code', 'name', 'symbol_type', 'exchange', 'contract_size',
                    'currency', 'is_active', 'created_at']
    list_filter = ['symbol_type', 'exchange', 'currency', 'is_active', 'created_at']
    search_fields = ['code', 'name', 'exchange', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('基本信息', {
            'fields': ('code', 'name', 'symbol_type', 'exchange', 'is_active')
        }),
        ('合约规格', {
            'fields': ('contract_size', 'minimum_tick', 'currency', 'margin_rate')
        }),
        ('手续费设置', {
            'fields': ('commission_rate', 'commission_per_contract')
        }),
        ('其他', {
            'fields': ('description', 'created_at', 'updated_at')
        }),
    )


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    """交易策略管理界面"""
    list_display = ['name', 'status', 'owner', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'description', 'owner__username']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'description', 'owner')
        }),
        ('状态', {
            'fields': ('status',)
        }),
        ('其他', {
            'fields': ('created_at', 'updated_at')
        }),
    )


class TradeImageInline(admin.TabularInline):
    """交易截图内联"""
    model = TradeImage
    extra = 0
    fields = ('image', 'image_preview', 'description')
    readonly_fields = ('image_preview',)

    def image_preview(self, obj):
        if obj.pk and obj.image:
            return format_html('<img src="{}" style="max-width: 300px; max-height: 200px;"/>', obj.image.url)
        return "上传后显示预览"
    image_preview.short_description = '预览'


class TradeReviewInline(admin.StackedInline):
    """交易复盘内联"""
    model = TradeReview
    extra = 0
    max_num = 1
    can_delete = False

    fieldsets = (
        ('情绪与评分', {
            'fields': (('emotion_before', 'emotion_after'), ('execution_score', 'followed_plan'))
        }),
        ('复盘标签', {
            'fields': ('tags', 'market_condition'),
            'description': '标签可选：planned(计划内), impulsive(冲动), overtrading(过度), early_exit(过早), late_exit(过晚), wrong_direction(方向错), position_too_big(仓重), position_too_small(仓轻), missed_stop(未止损), moved_stop(移止损), news_driven(消息), technical(技术), fundamental(基本面), perfect(完美), lucky(运气)'
        }),
        ('交易分析', {
            'fields': ('entry_reason', 'exit_reason'),
            'classes': ('collapse',)
        }),
        ('复盘总结', {
            'fields': ('what_went_well', 'what_went_wrong', 'lessons_learned', 'improvement_plan'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TradeLog)
class TradeLogAdmin(admin.ModelAdmin):
    """交易日志管理界面"""
    inlines = [TradeImageInline, TradeReviewInline]
    list_display = ['trade_time', 'account', 'symbol', 'side', 'quantity',
                    'executed_price', 'total_amount', 'profit_loss', 'holding_display', 'tags_display', 'status']
    list_filter = ['status', 'side', 'account', 'strategy', 'symbol', 'tags', 'trade_time']
    search_fields = ['symbol__code', 'symbol__name', 'order_id', 'account__name', 'strategy__name']
    date_hierarchy = 'trade_time'
    filter_horizontal = ['tags']

    def get_readonly_fields(self, request, obj=None):
        if obj:  # 编辑已存在的对象
            return ['trade_time', 'created_at', 'total_amount', 'holding_minutes']
        return ['trade_time', 'created_at']  # 新建时不显示total_amount

    def get_fieldsets(self, request, obj=None):
        if obj:  # 编辑已存在的对象，显示total_amount
            return (
                ('基本信息', {
                    'fields': ('account', 'strategy', 'symbol', 'side', 'tags')
                }),
                ('交易详情', {
                    'fields': ('quantity', 'price', 'executed_price', 'order_id', 'total_amount')
                }),
                ('费用与盈亏', {
                    'fields': ('commission', 'slippage', 'profit_loss')
                }),
                ('持仓时间', {
                    'fields': ('open_time', 'close_time', 'holding_minutes'),
                    'classes': ('collapse',)
                }),
                ('状态', {
                    'fields': ('status', 'trade_time')
                }),
                ('其他', {
                    'fields': ('notes', 'created_at')
                }),
            )
        else:  # 新建时不显示total_amount
            return (
                ('基本信息', {
                    'fields': ('account', 'strategy', 'symbol', 'side', 'tags')
                }),
                ('交易详情', {
                    'fields': ('quantity', 'price', 'executed_price', 'order_id')
                }),
                ('费用与盈亏', {
                    'fields': ('commission', 'slippage', 'profit_loss')
                }),
                ('持仓时间', {
                    'fields': ('open_time', 'close_time'),
                    'classes': ('collapse',)
                }),
                ('状态', {
                    'fields': ('status', 'trade_time')
                }),
                ('其他', {
                    'fields': ('notes', 'created_at')
                }),
            )

    def total_amount(self, obj):
        return f"{obj.total_amount:,.2f}"
    total_amount.short_description = '交易总额'

    def holding_display(self, obj):
        if obj.holding_minutes is None:
            return '-'
        if obj.holding_minutes < 60:
            return f"{obj.holding_minutes}分钟"
        elif obj.holding_minutes < 1440:
            hours = obj.holding_minutes // 60
            mins = obj.holding_minutes % 60
            return f"{hours}小时{mins}分"
        else:
            days = obj.holding_minutes // 1440
            return f"{days}天"
    holding_display.short_description = '持仓时长'

    def tags_display(self, obj):
        tags = obj.tags.all()[:3]
        if not tags:
            return '-'
        html = ' '.join([
            f'<span style="background:{t.color};color:white;padding:2px 6px;border-radius:3px;font-size:11px;">{t.name}</span>'
            for t in tags
        ])
        return format_html(html)
    tags_display.short_description = '标签'

    class Media:
        css = {
            'all': ('trading/css/trade_log_admin.css',)
        }
        js = ('trading/js/trade_log_admin.js',)


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    """持仓管理界面"""
    list_display = ['account', 'symbol', 'quantity', 'avg_price',
                    'current_price', 'market_value', 'profit_loss', 'profit_loss_ratio']
    list_filter = ['account', 'symbol', 'updated_at']
    search_fields = ['symbol__code', 'symbol__name', 'account__name']
    readonly_fields = ['updated_at']
    fieldsets = (
        ('基本信息', {
            'fields': ('account', 'symbol', 'quantity')
        }),
        ('价格信息', {
            'fields': ('avg_price', 'current_price')
        }),
        ('盈亏信息', {
            'fields': ('market_value', 'profit_loss', 'profit_loss_ratio')
        }),
        ('其他', {
            'fields': ('updated_at',)
        }),
    )

    def profit_loss(self, obj):
        color = 'green' if obj.profit_loss >= 0 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, f'{obj.profit_loss:.2f}')
    profit_loss.short_description = '盈亏'

    def profit_loss_ratio(self, obj):
        color = 'green' if obj.profit_loss_ratio >= 0 else 'red'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.profit_loss_ratio:.2f}')
    profit_loss_ratio.short_description = '盈亏比例'


@admin.register(DailyReport)
class DailyReportAdmin(admin.ModelAdmin):
    """每日报表管理界面"""
    list_display = ['report_date', 'account', 'starting_balance', 'ending_balance',
                    'profit_loss', 'profit_loss_ratio', 'trade_count', 'win_rate']
    list_filter = ['account', 'report_date']
    search_fields = ['account__name']
    readonly_fields = ['created_at']
    date_hierarchy = 'report_date'
    fieldsets = (
        ('基本信息', {
            'fields': ('account', 'report_date')
        }),
        ('资金变动', {
            'fields': ('starting_balance', 'ending_balance', 'net_deposit')
        }),
        ('盈亏分析', {
            'fields': ('profit_loss', 'profit_loss_ratio', 'max_drawdown')
        }),
        ('交易统计', {
            'fields': ('trade_count', 'win_count', 'loss_count', 'win_rate')
        }),
        ('费用', {
            'fields': ('commission',)
        }),
        ('其他', {
            'fields': ('created_at',)
        }),
    )

    def profit_loss(self, obj):
        color = 'green' if obj.profit_loss >= 0 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, f'{obj.profit_loss:.2f}')
    profit_loss.short_description = '当日盈亏'

    def profit_loss_ratio(self, obj):
        color = 'green' if obj.profit_loss_ratio >= 0 else 'red'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.profit_loss_ratio:.2f}')
    profit_loss_ratio.short_description = '盈亏比例'


@admin.register(MonthlyReport)
class MonthlyReportAdmin(admin.ModelAdmin):
    """月度报表管理界面"""
    list_display = ['year', 'month', 'account', 'starting_balance', 'ending_balance',
                    'profit_loss', 'profit_loss_ratio', 'trade_count', 'sharpe_ratio']
    list_filter = ['account', 'year', 'month']
    search_fields = ['account__name']
    readonly_fields = ['created_at']
    fieldsets = (
        ('基本信息', {
            'fields': ('account', 'year', 'month')
        }),
        ('资金变动', {
            'fields': ('starting_balance', 'ending_balance', 'net_deposit')
        }),
        ('盈亏分析', {
            'fields': ('profit_loss', 'profit_loss_ratio', 'max_drawdown')
        }),
        ('交易统计', {
            'fields': ('trade_count', 'win_rate')
        }),
        ('绩效指标', {
            'fields': ('sharpe_ratio',)
        }),
        ('其他', {
            'fields': ('created_at',)
        }),
    )

    def profit_loss(self, obj):
        color = 'green' if obj.profit_loss >= 0 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, f'{obj.profit_loss:.2f}')
    profit_loss.short_description = '月度盈亏'

    def profit_loss_ratio(self, obj):
        color = 'green' if obj.profit_loss_ratio >= 0 else 'red'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.profit_loss_ratio:.2f}')
    profit_loss_ratio.short_description = '盈亏比例'


@admin.register(PerformanceMetrics)
class PerformanceMetricsAdmin(admin.ModelAdmin):
    """策略绩效指标管理界面"""
    list_display = ['strategy', 'total_trades', 'win_rate', 'total_return',
                    'profit_factor', 'sharpe_ratio', 'max_drawdown_ratio']
    list_filter = ['strategy__status']
    search_fields = ['strategy__name']
    readonly_fields = ['updated_at']
    fieldsets = (
        ('基本信息', {
            'fields': ('strategy',)
        }),
        ('交易统计', {
            'fields': ('total_trades', 'profitable_trades', 'losing_trades', 'win_rate')
        }),
        ('盈亏分析', {
            'fields': ('total_profit', 'total_loss', 'profit_factor',
                      'average_profit', 'average_loss',
                      'largest_profit', 'largest_loss')
        }),
        ('风险指标', {
            'fields': ('max_drawdown', 'max_drawdown_ratio')
        }),
        ('绩效指标', {
            'fields': ('sharpe_ratio', 'sortino_ratio', 'calmar_ratio',
                      'total_return', 'annualized_return')
        }),
        ('其他', {
            'fields': ('updated_at',)
        }),
    )

    def win_rate(self, obj):
        color = 'green' if obj.win_rate >= 50 else 'red'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.win_rate:.2f}')
    win_rate.short_description = '胜率'

    def total_return(self, obj):
        color = 'green' if obj.total_return >= 0 else 'red'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.total_return:.2f}')
    total_return.short_description = '总收益率'

    def max_drawdown_ratio(self, obj):
        color = 'red' if obj.max_drawdown_ratio < 0 else 'gray'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.max_drawdown_ratio:.2f}')
    max_drawdown_ratio.short_description = '最大回撤比例'


@admin.register(TradeReview)
class TradeReviewAdmin(admin.ModelAdmin):
    """交易复盘管理界面"""
    list_display = ['trade_info', 'trade_time', 'profit_loss_display', 'emotion_before',
                    'emotion_after', 'execution_score_display', 'followed_plan_display', 'tags_display']
    list_filter = ['emotion_before', 'emotion_after', 'execution_score', 'followed_plan', 'created_at']
    search_fields = ['trade_log__symbol__code', 'trade_log__symbol__name', 'entry_reason',
                    'exit_reason', 'lessons_learned', 'tags']
    readonly_fields = ['created_at', 'updated_at', 'trade_summary']
    date_hierarchy = 'created_at'
    raw_id_fields = ['trade_log']

    fieldsets = (
        ('关联交易', {
            'fields': ('trade_log', 'trade_summary')
        }),
        ('情绪记录', {
            'fields': (('emotion_before', 'emotion_after'),)
        }),
        ('评分与标签', {
            'fields': (('execution_score', 'followed_plan'), 'tags', 'market_condition')
        }),
        ('入场出场分析', {
            'fields': ('entry_reason', 'exit_reason')
        }),
        ('复盘总结', {
            'fields': ('what_went_well', 'what_went_wrong', 'lessons_learned', 'improvement_plan')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def trade_info(self, obj):
        """交易信息"""
        trade = obj.trade_log
        side_color = 'red' if trade.side == 'buy' else 'green'
        return format_html(
            '<span style="color: {};">{}</span> {}',
            side_color, trade.get_side_display(), trade.symbol.code
        )
    trade_info.short_description = '交易'

    def trade_time(self, obj):
        """交易时间"""
        return obj.trade_log.trade_time.strftime('%Y-%m-%d %H:%M')
    trade_time.short_description = '交易时间'

    def profit_loss_display(self, obj):
        """盈亏显示"""
        pl = obj.trade_log.profit_loss
        color = 'green' if pl >= 0 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, f'{pl:.2f}')
    profit_loss_display.short_description = '盈亏'

    def execution_score_display(self, obj):
        """评分显示"""
        if not obj.execution_score:
            return '-'
        color = obj.get_score_color()
        return format_html('<span style="color: {};">{}分</span>', color, obj.execution_score)
    execution_score_display.short_description = '评分'

    def followed_plan_display(self, obj):
        """是否遵守计划"""
        if obj.followed_plan is None:
            return '-'
        if obj.followed_plan:
            return format_html('<span style="color: green;">是</span>')
        return format_html('<span style="color: red;">否</span>')
    followed_plan_display.short_description = '遵守计划'

    def tags_display(self, obj):
        """标签显示"""
        tags = obj.get_tags_display()
        if not tags:
            return '-'
        return ', '.join(tags[:3]) + ('...' if len(tags) > 3 else '')
    tags_display.short_description = '标签'

    def trade_summary(self, obj):
        """交易摘要"""
        if not obj.pk:
            return '保存后显示'
        trade = obj.trade_log
        pl_color = 'green' if trade.profit_loss >= 0 else 'red'
        return format_html(
            '''
            <div style="background: #f5f5f5; padding: 10px; border-radius: 5px;">
                <p><strong>标的:</strong> {} ({})</p>
                <p><strong>方向:</strong> {} | <strong>数量:</strong> {}</p>
                <p><strong>价格:</strong> {} → {}</p>
                <p><strong>盈亏:</strong> <span style="color: {};">{}</span></p>
                <p><strong>时间:</strong> {}</p>
            </div>
            ''',
            trade.symbol.code, trade.symbol.name,
            trade.get_side_display(), trade.quantity,
            trade.price, trade.executed_price or '-',
            pl_color, f'{trade.profit_loss:.2f}',
            trade.trade_time.strftime('%Y-%m-%d %H:%M')
        )
    trade_summary.short_description = '交易摘要'


@admin.register(RiskRule)
class RiskRuleAdmin(admin.ModelAdmin):
    """风险规则管理界面"""
    list_display = ['name', 'account', 'rule_type', 'threshold_display', 'level_display',
                    'action', 'is_active', 'alerts_count']
    list_filter = ['rule_type', 'level', 'action', 'is_active', 'account']
    search_fields = ['name', 'account__name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['is_active']

    fieldsets = (
        ('基本信息', {
            'fields': ('account', 'name', 'rule_type')
        }),
        ('阈值设置', {
            'fields': (('threshold_value', 'threshold_percent'),),
            'description': '可以设置固定金额或相对于账户资金的百分比'
        }),
        ('触发设置', {
            'fields': (('level', 'action'),)
        }),
        ('状态', {
            'fields': ('is_active', 'description')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def threshold_display(self, obj):
        """阈值显示"""
        return obj.get_threshold_display()
    threshold_display.short_description = '阈值'

    def level_display(self, obj):
        """级别显示"""
        colors = {'warning': 'orange', 'danger': 'red', 'critical': 'darkred'}
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>',
                          colors.get(obj.level, 'gray'), obj.get_level_display())
    level_display.short_description = '级别'

    def alerts_count(self, obj):
        """触发次数"""
        count = obj.alerts.count()
        active_count = obj.alerts.filter(status='active').count()
        if active_count > 0:
            return format_html('<span style="color: red;">{} (活跃:{})</span>', count, active_count)
        return count
    alerts_count.short_description = '触发次数'


@admin.register(RiskAlert)
class RiskAlertAdmin(admin.ModelAdmin):
    """风险警告管理界面"""
    list_display = ['triggered_at', 'account', 'level_display', 'alert_type_display',
                    'title', 'value_display', 'status_display']
    list_filter = ['status', 'level', 'alert_type', 'account', 'triggered_at']
    search_fields = ['title', 'message', 'account__name']
    readonly_fields = ['triggered_at', 'current_value', 'threshold_value']
    date_hierarchy = 'triggered_at'
    actions = ['mark_acknowledged', 'mark_resolved', 'mark_ignored']

    fieldsets = (
        ('警告信息', {
            'fields': ('account', 'rule', 'trade_log')
        }),
        ('警告详情', {
            'fields': (('alert_type', 'level'), 'title', 'message')
        }),
        ('触发数据', {
            'fields': (('current_value', 'threshold_value'),)
        }),
        ('状态', {
            'fields': ('status', ('acknowledged_at', 'resolved_at'))
        }),
        ('时间', {
            'fields': ('triggered_at',)
        }),
    )

    def level_display(self, obj):
        """级别显示"""
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>',
                          obj.get_level_color(), obj.get_level_display())
    level_display.short_description = '级别'

    def alert_type_display(self, obj):
        """类型显示"""
        return obj.get_alert_type_display()
    alert_type_display.short_description = '类型'

    def status_display(self, obj):
        """状态显示"""
        return format_html('<span style="color: {};">{}</span>',
                          obj.get_status_color(), obj.get_status_display())
    status_display.short_description = '状态'

    def value_display(self, obj):
        """数值显示"""
        return format_html('{} / {}', f'{obj.current_value:.2f}', f'{obj.threshold_value:.2f}')
    value_display.short_description = '当前/阈值'

    @admin.action(description='标记为已确认')
    def mark_acknowledged(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='acknowledged', acknowledged_at=timezone.now())

    @admin.action(description='标记为已解决')
    def mark_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='resolved', resolved_at=timezone.now())

    @admin.action(description='标记为已忽略')
    def mark_ignored(self, request, queryset):
        queryset.update(status='ignored')


@admin.register(RiskSnapshot)
class RiskSnapshotAdmin(admin.ModelAdmin):
    """风险快照管理界面"""
    list_display = ['snapshot_date', 'account', 'daily_pnl_display', 'consecutive_display',
                    'drawdown_display', 'position_ratio_display', 'risk_score_display', 'alerts_count']
    list_filter = ['account', 'snapshot_date']
    search_fields = ['account__name']
    readonly_fields = ['created_at', 'updated_at', 'risk_level_display']
    date_hierarchy = 'snapshot_date'

    fieldsets = (
        ('基本信息', {
            'fields': ('account', 'snapshot_date')
        }),
        ('当日数据', {
            'fields': (('daily_pnl', 'daily_pnl_percent'),
                      ('daily_trade_count', 'daily_win_count', 'daily_loss_count'))
        }),
        ('连续统计', {
            'fields': (('consecutive_wins', 'consecutive_losses'),)
        }),
        ('回撤数据', {
            'fields': ('peak_balance',
                      ('current_drawdown', 'current_drawdown_percent'),
                      ('max_drawdown', 'max_drawdown_percent'))
        }),
        ('仓位数据', {
            'fields': (('total_position_value', 'position_ratio'),)
        }),
        ('风险评估', {
            'fields': (('risk_score', 'risk_level_display'), 'active_alerts_count')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def daily_pnl_display(self, obj):
        """当日盈亏显示"""
        color = 'green' if obj.daily_pnl >= 0 else 'red'
        return format_html('<span style="color: {};">{} ({}%)</span>',
                          color, f'{obj.daily_pnl:.2f}', f'{obj.daily_pnl_percent:.2f}')
    daily_pnl_display.short_description = '当日盈亏'

    def consecutive_display(self, obj):
        """连续统计显示"""
        if obj.consecutive_losses > 0:
            return format_html('<span style="color: red;">连亏{}次</span>', obj.consecutive_losses)
        elif obj.consecutive_wins > 0:
            return format_html('<span style="color: green;">连盈{}次</span>', obj.consecutive_wins)
        return '-'
    consecutive_display.short_description = '连续'

    def drawdown_display(self, obj):
        """回撤显示"""
        if obj.current_drawdown_percent > 10:
            color = 'red'
        elif obj.current_drawdown_percent > 5:
            color = 'orange'
        else:
            color = 'gray'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.current_drawdown_percent:.2f}')
    drawdown_display.short_description = '当前回撤'

    def position_ratio_display(self, obj):
        """仓位比例显示"""
        if obj.position_ratio > 80:
            color = 'red'
        elif obj.position_ratio > 60:
            color = 'orange'
        else:
            color = 'green'
        return format_html('<span style="color: {};">{}%</span>', color, f'{obj.position_ratio:.2f}')
    position_ratio_display.short_description = '仓位'

    def risk_score_display(self, obj):
        """风险评分显示"""
        level, level_name = obj.get_risk_level()
        colors = {'critical': 'darkred', 'danger': 'red', 'warning': 'orange', 'safe': 'green'}
        return format_html('<span style="color: {}; font-weight: bold;">{} ({})</span>',
                          colors.get(level, 'gray'), obj.risk_score, level_name)
    risk_score_display.short_description = '风险评分'

    def risk_level_display(self, obj):
        """风险等级显示（详情页）"""
        if not obj.pk:
            return '-'
        level, level_name = obj.get_risk_level()
        colors = {'critical': 'darkred', 'danger': 'red', 'warning': 'orange', 'safe': 'green'}
        return format_html('<span style="color: {}; font-size: 16px; font-weight: bold;">{}</span>',
                          colors.get(level, 'gray'), level_name)
    risk_level_display.short_description = '风险等级'

    def alerts_count(self, obj):
        """警告数"""
        count = obj.active_alerts_count
        if count > 0:
            return format_html('<span style="color: red; font-weight: bold;">{}</span>', count)
        return format_html('<span style="color: green;">0</span>')
    alerts_count.short_description = '活跃警告'


class WatchlistItemInline(admin.TabularInline):
    """观察项目内联"""
    model = WatchlistItem
    extra = 1
    fields = ('symbol', 'priority', 'target_price', 'alert_price_above', 'alert_price_below', 'notes', 'is_active')
    raw_id_fields = ['symbol']


@admin.register(WatchlistGroup)
class WatchlistGroupAdmin(admin.ModelAdmin):
    """观察分组管理界面"""
    inlines = [WatchlistItemInline]
    list_display = ['name', 'owner', 'items_count_display', 'color_display', 'sort_order', 'created_at']
    list_filter = ['owner', 'created_at']
    search_fields = ['name', 'description', 'owner__username']
    list_editable = ['sort_order']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'owner', 'description')
        }),
        ('显示设置', {
            'fields': (('color', 'sort_order'),)
        }),
    )

    def items_count_display(self, obj):
        count = obj.items_count()
        return format_html('<span style="font-weight: bold;">{}</span>', count)
    items_count_display.short_description = '项目数'

    def color_display(self, obj):
        return format_html(
            '<span style="display: inline-block; width: 20px; height: 20px; background: {}; border-radius: 3px;"></span>',
            obj.color
        )
    color_display.short_description = '颜色'


@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    """观察项目管理界面"""
    list_display = ['symbol', 'group', 'priority_display', 'target_price', 'price_alerts', 'is_active', 'updated_at']
    list_filter = ['group', 'priority', 'is_active', 'group__owner']
    search_fields = ['symbol__code', 'symbol__name', 'notes', 'tags']
    raw_id_fields = ['symbol']
    list_editable = ['is_active']

    fieldsets = (
        ('基本信息', {
            'fields': ('group', 'symbol', 'priority')
        }),
        ('价格监控', {
            'fields': ('target_price', ('alert_price_above', 'alert_price_below'))
        }),
        ('备注', {
            'fields': ('notes', 'tags', 'is_active')
        }),
    )

    def priority_display(self, obj):
        colors = {1: 'gray', 2: 'blue', 3: 'orange', 4: 'red'}
        return format_html('<span style="color: {};">{}</span>',
                          colors.get(obj.priority, 'gray'), obj.get_priority_display())
    priority_display.short_description = '优先级'

    def price_alerts(self, obj):
        alerts = []
        if obj.alert_price_above:
            alerts.append(f'↑{obj.alert_price_above}')
        if obj.alert_price_below:
            alerts.append(f'↓{obj.alert_price_below}')
        return ' | '.join(alerts) if alerts else '-'
    price_alerts.short_description = '价格提醒'


@admin.register(TradePlan)
class TradePlanAdmin(admin.ModelAdmin):
    """交易计划管理界面"""
    list_display = ['plan_date', 'symbol', 'direction_display', 'entry_range', 'stop_loss',
                    'rr_ratio_display', 'status_display', 'is_valid_display']
    list_filter = ['status', 'plan_type', 'direction', 'account', 'plan_date']
    search_fields = ['symbol__code', 'symbol__name', 'analysis', 'entry_condition']
    date_hierarchy = 'plan_date'
    raw_id_fields = ['symbol', 'executed_trade']
    actions = ['mark_pending', 'mark_cancelled', 'mark_expired']

    fieldsets = (
        ('基本信息', {
            'fields': ('account', 'symbol', 'strategy', ('plan_type', 'direction'))
        }),
        ('计划时间', {
            'fields': (('plan_date', 'valid_until'),)
        }),
        ('入场计划', {
            'fields': (('entry_price_min', 'entry_price_max'), 'entry_condition')
        }),
        ('出场计划', {
            'fields': ('stop_loss', ('take_profit_1', 'take_profit_2', 'take_profit_3'), 'exit_condition')
        }),
        ('仓位管理', {
            'fields': (('planned_quantity', 'max_risk_amount'), 'position_size_percent')
        }),
        ('分析', {
            'fields': ('analysis', 'key_levels'),
            'classes': ('collapse',)
        }),
        ('状态', {
            'fields': ('status',)
        }),
        ('执行记录', {
            'fields': ('executed_trade', 'executed_at', 'execution_notes'),
            'classes': ('collapse',)
        }),
    )

    def direction_display(self, obj):
        colors = {'long': 'red', 'short': 'green', 'both': 'purple'}
        return format_html('<span style="color: {};">{}</span>',
                          colors.get(obj.direction, 'gray'), obj.get_direction_display())
    direction_display.short_description = '方向'

    def entry_range(self, obj):
        return f'{obj.entry_price_min} - {obj.entry_price_max}'
    entry_range.short_description = '入场区间'

    def rr_ratio_display(self, obj):
        rr = obj.risk_reward_ratio
        if rr is None:
            return '-'
        color = 'green' if rr >= 2 else ('orange' if rr >= 1 else 'red')
        return format_html('<span style="color: {};">1:{}</span>', color, rr)
    rr_ratio_display.short_description = '盈亏比'

    def status_display(self, obj):
        colors = {
            'draft': 'gray', 'pending': 'blue', 'partial': 'orange',
            'executed': 'green', 'cancelled': 'gray', 'expired': 'red'
        }
        return format_html('<span style="color: {};">{}</span>',
                          colors.get(obj.status, 'gray'), obj.get_status_display())
    status_display.short_description = '状态'

    def is_valid_display(self, obj):
        if obj.is_valid:
            return format_html('<span style="color: green;">有效</span>')
        return format_html('<span style="color: gray;">无效</span>')
    is_valid_display.short_description = '有效性'

    @admin.action(description='标记为待执行')
    def mark_pending(self, request, queryset):
        queryset.update(status='pending')

    @admin.action(description='标记为已取消')
    def mark_cancelled(self, request, queryset):
        queryset.update(status='cancelled')

    @admin.action(description='标记为已过期')
    def mark_expired(self, request, queryset):
        queryset.update(status='expired')


@admin.register(DailyNote)
class DailyNoteAdmin(admin.ModelAdmin):
    """每日笔记管理界面"""
    list_display = ['note_date', 'owner', 'market_outlook_display', 'mood_display',
                    'plan_stats', 'has_summary']
    list_filter = ['owner', 'market_outlook', 'mood', 'note_date']
    search_fields = ['pre_market_plan', 'post_market_summary', 'lessons_learned']
    date_hierarchy = 'note_date'

    fieldsets = (
        ('基本信息', {
            'fields': ('owner', 'note_date')
        }),
        ('盘前计划', {
            'fields': ('market_outlook', 'pre_market_plan', 'focus_sectors', 'key_events')
        }),
        ('盘后总结', {
            'fields': ('post_market_summary', 'lessons_learned', 'mood')
        }),
        ('统计', {
            'fields': (('planned_trades', 'executed_trades', 'followed_plan_count'),),
            'classes': ('collapse',)
        }),
    )

    def market_outlook_display(self, obj):
        if not obj.market_outlook:
            return '-'
        colors = {'bullish': 'red', 'bearish': 'green', 'neutral': 'gray', 'uncertain': 'orange'}
        labels = {'bullish': '看多', 'bearish': '看空', 'neutral': '中性', 'uncertain': '不确定'}
        return format_html('<span style="color: {};">{}</span>',
                          colors.get(obj.market_outlook, 'gray'), labels.get(obj.market_outlook, '-'))
    market_outlook_display.short_description = '市场展望'

    def mood_display(self, obj):
        if not obj.mood:
            return '-'
        colors = {'great': 'green', 'good': 'blue', 'normal': 'gray', 'bad': 'orange', 'terrible': 'red'}
        labels = {'great': '很好', 'good': '不错', 'normal': '一般', 'bad': '不好', 'terrible': '很差'}
        return format_html('<span style="color: {};">{}</span>',
                          colors.get(obj.mood, 'gray'), labels.get(obj.mood, '-'))
    mood_display.short_description = '心情'

    def plan_stats(self, obj):
        if obj.planned_trades == 0:
            return '-'
        rate = obj.plan_execution_rate
        color = 'green' if rate >= 80 else ('orange' if rate >= 50 else 'red')
        return format_html('{}/{} (<span style="color: {};">{}%</span>)',
                          obj.executed_trades, obj.planned_trades, color, rate)
    plan_stats.short_description = '计划执行'

    def has_summary(self, obj):
        if obj.post_market_summary:
            return format_html('<span style="color: green;">已总结</span>')
        return format_html('<span style="color: gray;">未总结</span>')
    has_summary.short_description = '盘后总结'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """通知消息管理界面"""
    list_display = ['created_at', 'owner', 'type_display', 'priority_display', 'title', 'is_read_display']
    list_filter = ['notification_type', 'priority', 'is_read', 'owner', 'created_at']
    search_fields = ['title', 'message', 'owner__username']
    readonly_fields = ['created_at', 'read_at']
    date_hierarchy = 'created_at'
    actions = ['mark_as_read', 'mark_as_unread']

    fieldsets = (
        ('基本信息', {
            'fields': ('owner', 'notification_type', 'priority')
        }),
        ('通知内容', {
            'fields': ('title', 'message')
        }),
        ('关联对象', {
            'fields': ('related_symbol', 'related_trade', 'related_plan', 'related_alert'),
            'classes': ('collapse',)
        }),
        ('状态', {
            'fields': (('is_read', 'read_at'),)
        }),
        ('其他', {
            'fields': ('extra_data', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def type_display(self, obj):
        colors = {
            'price_alert': 'blue',
            'plan_reminder': 'purple',
            'risk_warning': 'red',
            'daily_summary': 'green',
            'trade_executed': 'teal',
            'system': 'gray',
        }
        color = colors.get(obj.notification_type, 'gray')
        return format_html('<span style="color: {};">{}</span>',
                          color, obj.get_notification_type_display())
    type_display.short_description = '类型'

    def priority_display(self, obj):
        colors = {'low': 'gray', 'normal': 'blue', 'high': 'orange', 'urgent': 'red'}
        color = colors.get(obj.priority, 'gray')
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>',
                          color, obj.get_priority_display())
    priority_display.short_description = '优先级'

    def is_read_display(self, obj):
        if obj.is_read:
            return format_html('<span style="color: gray;">已读</span>')
        return format_html('<span style="color: red; font-weight: bold;">未读</span>')
    is_read_display.short_description = '状态'

    @admin.action(description='标记为已读')
    def mark_as_read(self, request, queryset):
        from django.utils import timezone
        queryset.update(is_read=True, read_at=timezone.now())

    @admin.action(description='标记为未读')
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False, read_at=None)


@admin.register(PriceAlert)
class PriceAlertAdmin(admin.ModelAdmin):
    """价格提醒管理界面"""
    list_display = ['symbol', 'owner', 'condition_display', 'target_price', 'last_price',
                    'status_display', 'trigger_count', 'created_at']
    list_filter = ['status', 'condition', 'owner', 'created_at']
    search_fields = ['symbol__code', 'symbol__name', 'owner__username', 'notes']
    raw_id_fields = ['symbol']
    readonly_fields = ['triggered_at', 'trigger_count', 'last_price', 'created_at', 'updated_at']
    actions = ['cancel_alerts', 'reactivate_alerts']

    fieldsets = (
        ('基本信息', {
            'fields': ('owner', 'symbol')
        }),
        ('提醒条件', {
            'fields': (('condition', 'target_price'), 'valid_until', 'trigger_once')
        }),
        ('状态', {
            'fields': ('status', 'last_price', ('triggered_at', 'trigger_count'))
        }),
        ('其他', {
            'fields': ('notes', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def condition_display(self, obj):
        colors = {'above': 'red', 'below': 'green', 'cross_up': 'orange', 'cross_down': 'blue'}
        return format_html('<span style="color: {};">{}</span>',
                          colors.get(obj.condition, 'gray'), obj.get_condition_display())
    condition_display.short_description = '条件'

    def status_display(self, obj):
        colors = {'active': 'green', 'triggered': 'blue', 'cancelled': 'gray', 'expired': 'red'}
        return format_html('<span style="color: {};">{}</span>',
                          colors.get(obj.status, 'gray'), obj.get_status_display())
    status_display.short_description = '状态'

    @admin.action(description='取消选中的提醒')
    def cancel_alerts(self, request, queryset):
        queryset.filter(status='active').update(status='cancelled')

    @admin.action(description='重新激活选中的提醒')
    def reactivate_alerts(self, request, queryset):
        queryset.exclude(status='active').update(status='active')


@admin.register(NotificationSetting)
class NotificationSettingAdmin(admin.ModelAdmin):
    """通知设置管理界面"""
    list_display = ['owner', 'enable_price_alert', 'enable_plan_reminder',
                    'enable_risk_warning', 'enable_daily_summary', 'daily_summary_time']
    list_filter = ['enable_price_alert', 'enable_plan_reminder', 'enable_risk_warning']
    search_fields = ['owner__username']

    fieldsets = (
        ('用户', {
            'fields': ('owner',)
        }),
        ('通知开关', {
            'fields': (('enable_price_alert', 'enable_plan_reminder'),
                      ('enable_risk_warning', 'enable_daily_summary'),
                      'enable_trade_notification')
        }),
        ('提醒时间', {
            'fields': ('daily_summary_time', 'plan_reminder_minutes')
        }),
        ('静默时段', {
            'fields': (('quiet_hours_start', 'quiet_hours_end'),),
            'description': '在此时段内不发送通知'
        }),
    )


@admin.register(TradeTag)
class TradeTagAdmin(admin.ModelAdmin):
    """交易标签管理界面"""
    list_display = ['name', 'category', 'color_display', 'trade_count', 'win_rate_display', 'owner', 'is_system']
    list_filter = ['category', 'is_system', 'owner']
    search_fields = ['name', 'description']

    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'category', 'color', 'description')
        }),
        ('归属', {
            'fields': ('owner', 'is_system')
        }),
    )

    def color_display(self, obj):
        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;border-radius:3px;">{}</span>',
            obj.color, obj.name
        )
    color_display.short_description = '预览'

    def trade_count(self, obj):
        return obj.trade_logs.count()
    trade_count.short_description = '交易数'

    def win_rate_display(self, obj):
        trades = obj.trade_logs.all()
        total = trades.count()
        if total == 0:
            return '-'
        wins = trades.filter(profit_loss__gt=0).count()
        rate = wins / total * 100
        color = 'green' if rate >= 50 else 'red'
        return format_html('<span style="color:{};">{:.1f}%</span>', color, rate)
    win_rate_display.short_description = '胜率'
