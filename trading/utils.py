"""
交易模块工具函数
"""
from functools import wraps
from datetime import datetime
from django.http import JsonResponse


def api_login_required(view_func):
    """API 视图的登录验证装饰器，返回 JSON 401 响应"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': '未登录'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def parse_date(date_str, default=None):
    """解析日期字符串
    Args:
        date_str: 日期字符串，格式 YYYY-MM-DD
        default: 解析失败时的默认值
    Returns:
        date 对象或默认值
    """
    if not date_str:
        return default
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return default


def parse_date_range(start_str, end_str, default_start=None, default_end=None):
    """解析日期范围
    Args:
        start_str: 开始日期字符串
        end_str: 结束日期字符串
        default_start: 开始日期默认值
        default_end: 结束日期默认值
    Returns:
        (start_date, end_date) 元组
    """
    return parse_date(start_str, default_start), parse_date(end_str, default_end)


# Webhook 速率限制缓存
_webhook_rate_limit = {}


def check_webhook_rate_limit(secret_key, max_requests=60, window_seconds=60):
    """检查 Webhook 速率限制
    Args:
        secret_key: Webhook 密钥
        max_requests: 时间窗口内最大请求数
        window_seconds: 时间窗口（秒）
    Returns:
        (allowed, remaining, reset_time) 元组
    """
    import time
    now = time.time()

    if secret_key not in _webhook_rate_limit:
        _webhook_rate_limit[secret_key] = {'count': 0, 'window_start': now}

    rate_info = _webhook_rate_limit[secret_key]

    # 检查是否需要重置窗口
    if now - rate_info['window_start'] > window_seconds:
        rate_info['count'] = 0
        rate_info['window_start'] = now

    # 检查是否超过限制
    if rate_info['count'] >= max_requests:
        reset_time = int(rate_info['window_start'] + window_seconds - now)
        return False, 0, reset_time

    rate_info['count'] += 1
    remaining = max_requests - rate_info['count']
    reset_time = int(rate_info['window_start'] + window_seconds - now)

    return True, remaining, reset_time
