"""
URL configuration for mytrader project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from trading import views
from quant import views as quant_views

urlpatterns = [
    path('', views.home, name='home'),
    path('api/dashboard/', views.api_dashboard_data, name='api_dashboard'),
    path('analytics/', views.analytics_page, name='analytics'),
    path('api/analytics/', views.api_analytics_data, name='api_analytics'),
    # 数据导入导出
    path('import-export/', views.import_export_page, name='import_export'),
    path('export/trades/', views.export_trades, name='export_trades'),
    path('export/accounts/', views.export_accounts, name='export_accounts'),
    path('export/positions/', views.export_positions, name='export_positions'),
    path('export/symbols/', views.export_symbols, name='export_symbols'),
    path('export/analysis/', views.export_analysis, name='export_analysis'),
    path('download/template/', views.download_template, name='download_template'),
    path('import/trades/', views.import_trades, name='import_trades'),
    path('import/symbols/', views.import_symbols, name='import_symbols'),
    # 通知管理
    path('notifications/', views.notifications_page, name='notifications'),
    path('api/notifications/', views.api_notifications, name='api_notifications'),
    path('api/notifications/unread-count/', views.api_notification_unread_count, name='api_notification_unread_count'),
    path('api/notifications/<int:notification_id>/read/', views.api_notification_mark_read, name='api_notification_mark_read'),
    path('api/notifications/mark-all-read/', views.api_notification_mark_all_read, name='api_notification_mark_all_read'),
    path('api/notifications/<int:notification_id>/delete/', views.api_notification_delete, name='api_notification_delete'),
    path('api/notifications/clear-old/', views.api_notification_clear_old, name='api_notification_clear_old'),
    # 价格提醒
    path('api/price-alerts/', views.api_price_alerts, name='api_price_alerts'),
    path('api/price-alerts/create/', views.api_price_alert_create, name='api_price_alert_create'),
    path('api/price-alerts/<int:alert_id>/cancel/', views.api_price_alert_cancel, name='api_price_alert_cancel'),
    # 通知设置
    path('api/notification-settings/', views.api_notification_settings_update, name='api_notification_settings_update'),
    # 自动化任务
    path('automation/', views.automation_page, name='automation'),
    path('api/automation/run/', views.api_run_automation_task, name='api_automation_run'),
    path('api/automation/status/', views.api_automation_status, name='api_automation_status'),
    # 量化数据管理
    path('quant/data/', quant_views.stock_data_page, name='stock_data_page'),
    path('quant/data/fetch/', quant_views.fetch_stock_data_api, name='fetch_stock_data_api'),
    path('quant/data/task/<str:task_id>/', quant_views.fetch_task_status, name='fetch_task_status'),
    path('quant/data/delete/', quant_views.delete_stock_data_api, name='delete_stock_data_api'),
    # 量化回测
    path('quant/strategy/<int:strategy_id>/backtest/', quant_views.strategy_backtest_list, name='strategy_backtest_list'),
    path('quant/backtest/<int:result_id>/', quant_views.backtest_detail, name='backtest_detail'),
    path('quant/backtest/trigger/', quant_views.trigger_backtest, name='trigger_backtest'),
    path('quant/backtest/task/<str:task_id>/', quant_views.backtest_task_status, name='backtest_task_status'),
    path('admin/', admin.site.urls),
]
