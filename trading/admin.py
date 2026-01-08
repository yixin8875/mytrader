from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, F, DecimalField
from .models import (
    Account, AccountTransaction, Symbol, Strategy, TradeLog, TradeImage, Position,
    DailyReport, MonthlyReport, PerformanceMetrics
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


@admin.register(TradeLog)
class TradeLogAdmin(admin.ModelAdmin):
    """交易日志管理界面"""
    inlines = [TradeImageInline]
    list_display = ['trade_time', 'account', 'symbol', 'side', 'quantity',
                    'executed_price', 'total_amount', 'profit_loss', 'status']
    list_filter = ['status', 'side', 'account', 'strategy', 'symbol', 'trade_time']
    search_fields = ['symbol__code', 'symbol__name', 'order_id', 'account__name', 'strategy__name']
    date_hierarchy = 'trade_time'

    def get_readonly_fields(self, request, obj=None):
        if obj:  # 编辑已存在的对象
            return ['trade_time', 'created_at', 'total_amount']
        return ['trade_time', 'created_at']  # 新建时不显示total_amount

    def get_fieldsets(self, request, obj=None):
        if obj:  # 编辑已存在的对象，显示total_amount
            return (
                ('基本信息', {
                    'fields': ('account', 'strategy', 'symbol', 'side')
                }),
                ('交易详情', {
                    'fields': ('quantity', 'price', 'executed_price', 'order_id', 'total_amount')
                }),
                ('费用与盈亏', {
                    'fields': ('commission', 'slippage', 'profit_loss')
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
                    'fields': ('account', 'strategy', 'symbol', 'side')
                }),
                ('交易详情', {
                    'fields': ('quantity', 'price', 'executed_price', 'order_id')
                }),
                ('费用与盈亏', {
                    'fields': ('commission', 'slippage', 'profit_loss')
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
