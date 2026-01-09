from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Min, Max
from .models import Strategy, BacktestResult, StockData
from .tasks import run_backtest_task, fetch_stock_history
import json
import re
import logging

logger = logging.getLogger(__name__)


def validate_symbol(symbol):
    """验证股票代码格式（6位数字）"""
    return bool(symbol and re.match(r'^\d{6}$', symbol))


def validate_date(date_str):
    """验证日期格式（YYYY-MM-DD）"""
    return bool(date_str and re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))


# ============ 数据管理 ============

@login_required
def stock_data_page(request):
    """股票数据管理页面"""
    # 获取已有数据的统计
    stats = StockData.objects.values('symbol').annotate(
        count=Count('id'),
        start_date=Min('date'),
        end_date=Max('date')
    ).order_by('symbol')

    total_records = StockData.objects.count()
    total_symbols = StockData.objects.values('symbol').distinct().count()

    return render(request, 'quant/stock_data.html', {
        'stats': stats,
        'total_records': total_records,
        'total_symbols': total_symbols,
    })


@login_required
@require_POST
def fetch_stock_data_api(request):
    """下载股票数据 API"""
    try:
        data = json.loads(request.body)
        symbols = data.get('symbols', [])
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if not symbols:
            return JsonResponse({'status': 'error', 'message': '请输入股票代码'}, status=400)

        if not start_date or not end_date:
            return JsonResponse({'status': 'error', 'message': '请选择日期范围'}, status=400)

        # 验证股票代码格式
        invalid_symbols = [s for s in symbols if not validate_symbol(s)]
        if invalid_symbols:
            return JsonResponse({
                'status': 'error',
                'message': f'股票代码格式错误: {", ".join(invalid_symbols)}'
            }, status=400)

        # 验证日期
        if not validate_date(start_date) or not validate_date(end_date):
            return JsonResponse({'status': 'error', 'message': '日期格式错误'}, status=400)

        if start_date >= end_date:
            return JsonResponse({'status': 'error', 'message': '开始日期必须早于结束日期'}, status=400)

        # 转换日期格式
        start_date_fmt = start_date.replace('-', '')
        end_date_fmt = end_date.replace('-', '')

        # 为每个股票创建下载任务
        task_ids = []
        for symbol in symbols:
            task = fetch_stock_history.delay(symbol, start_date_fmt, end_date_fmt)
            task_ids.append({'symbol': symbol, 'task_id': task.id})

        return JsonResponse({
            'status': 'success',
            'message': f'已提交 {len(symbols)} 个下载任务',
            'tasks': task_ids
        })

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '请求数据格式错误'}, status=400)
    except Exception as e:
        logger.exception('下载任务提交失败')
        return JsonResponse({'status': 'error', 'message': '服务器错误'}, status=500)


@login_required
def fetch_task_status(request, task_id):
    """查询下载任务状态"""
    from celery.result import AsyncResult

    if not re.match(r'^[a-f0-9\-]{36}$', task_id):
        return JsonResponse({'status': 'error', 'message': '无效的任务ID'}, status=400)

    result = AsyncResult(task_id)

    response = {
        'task_id': task_id,
        'status': result.status,
    }

    if result.ready():
        if result.successful():
            response['result'] = result.result
        else:
            response['error'] = '下载失败'

    return JsonResponse(response)


@login_required
@require_POST
def delete_stock_data_api(request):
    """删除股票数据 API"""
    try:
        data = json.loads(request.body)
        symbol = data.get('symbol')

        if not symbol:
            return JsonResponse({'status': 'error', 'message': '请指定股票代码'}, status=400)

        deleted, _ = StockData.objects.filter(symbol=symbol).delete()

        return JsonResponse({
            'status': 'success',
            'message': f'已删除 {symbol} 的 {deleted} 条数据'
        })

    except Exception as e:
        logger.exception('删除数据失败')
        return JsonResponse({'status': 'error', 'message': '删除失败'}, status=500)


@login_required
def strategy_backtest_list(request, strategy_id):
    """策略回测结果列表页面"""
    strategy = get_object_or_404(Strategy, id=strategy_id)

    # 验证用户是否为策略所有者
    if strategy.owner != request.user:
        return HttpResponseForbidden('无权访问此策略')

    results = strategy.backtest_results.all()[:20]
    symbols = list(StockData.objects.values_list('symbol', flat=True).distinct()[:50])

    return render(request, 'quant/backtest_list.html', {
        'strategy': strategy,
        'results': results,
        'symbols': symbols,
    })


@login_required
def backtest_detail(request, result_id):
    """回测详情页面（含收益曲线）"""
    result = get_object_or_404(BacktestResult, id=result_id)

    # 验证用户是否为策略所有者
    if result.strategy.owner != request.user:
        return HttpResponseForbidden('无权访问此回测结果')

    return render(request, 'quant/backtest_detail.html', {
        'result': result,
        'equity_curve_json': json.dumps(result.equity_curve),
    })


@login_required
@require_POST
def trigger_backtest(request):
    """触发新的回测任务"""
    try:
        data = json.loads(request.body)
        strategy_id = data.get('strategy_id')
        symbol = data.get('symbol')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        initial_capital = data.get('initial_capital', 100000)

        # 参数存在性验证
        if not all([strategy_id, symbol, start_date, end_date]):
            return JsonResponse({'status': 'error', 'message': '缺少必要参数'}, status=400)

        # 验证策略所有权
        try:
            strategy = Strategy.objects.get(id=strategy_id)
            if strategy.owner != request.user:
                return JsonResponse({'status': 'error', 'message': '无权操作此策略'}, status=403)
        except Strategy.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': '策略不存在'}, status=404)

        # 输入格式验证
        if not validate_symbol(symbol):
            return JsonResponse({'status': 'error', 'message': '股票代码格式错误（需6位数字）'}, status=400)

        if not validate_date(start_date) or not validate_date(end_date):
            return JsonResponse({'status': 'error', 'message': '日期格式错误（需YYYY-MM-DD）'}, status=400)

        if start_date >= end_date:
            return JsonResponse({'status': 'error', 'message': '开始日期必须早于结束日期'}, status=400)

        # 资金范围验证
        try:
            initial_capital = int(initial_capital)
            if not (10000 <= initial_capital <= 100000000):
                return JsonResponse({'status': 'error', 'message': '初始资金需在1万到1亿之间'}, status=400)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'message': '初始资金格式错误'}, status=400)

        # 触发 Celery 任务
        task = run_backtest_task.delay(
            strategy_id=strategy_id,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital
        )

        return JsonResponse({
            'status': 'success',
            'task_id': task.id,
            'message': '回测任务已提交'
        })

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': '请求数据格式错误'}, status=400)
    except Exception as e:
        # 记录详细错误到日志，返回通用错误信息
        logger.exception('回测任务触发失败')
        return JsonResponse({'status': 'error', 'message': '服务器内部错误，请稍后重试'}, status=500)


@login_required
def backtest_task_status(request, task_id):
    """查询回测任务状态"""
    from celery.result import AsyncResult

    # 验证 task_id 格式（防止注入）
    if not re.match(r'^[a-f0-9\-]{36}$', task_id):
        return JsonResponse({'status': 'error', 'message': '无效的任务ID'}, status=400)

    result = AsyncResult(task_id)

    response = {
        'task_id': task_id,
        'status': result.status,
    }

    if result.ready():
        if result.successful():
            result_id = result.result
            # 验证回测结果所有权
            try:
                backtest = BacktestResult.objects.get(id=result_id)
                if backtest.strategy.owner == request.user:
                    response['result_id'] = result_id
                else:
                    response['error'] = '无权访问此结果'
            except BacktestResult.DoesNotExist:
                response['error'] = '结果不存在'
        else:
            # 不暴露详细错误信息
            response['error'] = '任务执行失败'
            logger.error(f'回测任务失败: {task_id}, 错误: {result.result}')

    return JsonResponse(response)
