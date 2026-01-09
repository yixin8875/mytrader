from django.contrib import admin
from django.utils.html import format_html
from .models import StockData, Strategy, BacktestResult, TradeOrder


@admin.register(StockData)
class StockDataAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']
    list_filter = ['symbol', 'date']
    search_fields = ['symbol']
    date_hierarchy = 'date'
    ordering = ['-date', 'symbol']


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'strategy_type', 'status', 'initial_capital', 'updated_at']
    list_filter = ['strategy_type', 'status', 'owner']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('基本信息', {
            'fields': ('owner', 'name', 'strategy_type', 'description', 'status')
        }),
        ('策略配置', {
            'fields': ('parameters', 'symbols', 'initial_capital')
        }),
        ('时间信息', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(BacktestResult)
class BacktestResultAdmin(admin.ModelAdmin):
    list_display = ['strategy', 'start_date', 'end_date', 'total_return_display',
                    'sharpe_ratio', 'max_drawdown_display', 'total_trades', 'win_rate']
    list_filter = ['strategy', 'created_at']
    search_fields = ['strategy__name', 'name']
    readonly_fields = ['created_at', 'net_profit']
    date_hierarchy = 'created_at'

    def total_return_display(self, obj):
        color = 'green' if obj.total_return >= 0 else 'red'
        return format_html('<span style="color: {};">{}</span>', color, f'{obj.total_return:.2f}%')
    total_return_display.short_description = '总收益率'

    def max_drawdown_display(self, obj):
        return format_html('<span style="color: red;">{}</span>', f'{obj.max_drawdown:.2f}%')
    max_drawdown_display.short_description = '最大回撤'


@admin.register(TradeOrder)
class TradeOrderAdmin(admin.ModelAdmin):
    list_display = ['symbol', 'side', 'quantity', 'price', 'status', 'mode', 'strategy', 'created_at']
    list_filter = ['status', 'side', 'mode', 'order_type', 'strategy']
    search_fields = ['symbol', 'reason']
    readonly_fields = ['created_at', 'filled_amount']
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
