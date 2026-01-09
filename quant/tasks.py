from celery import shared_task
from quant.models import StockData
from datetime import date
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def update_daily_kline(self, symbols=None):
    """
    每日收盘后更新 K 线数据（自动检查交易日）
    symbols: 股票代码列表，为空则更新数据库中已有的所有股票
    """
    from quant.data_fetcher import StockDataFetcher, is_trade_date

    # 检查是否为交易日
    if not is_trade_date():
        logger.info('今日非交易日，跳过更新')
        return {'status': 'skip', 'message': '非交易日'}

    if symbols is None:
        symbols = list(StockData.objects.values_list('symbol', flat=True).distinct())

    if not symbols:
        logger.warning('没有需要更新的股票')
        return {'status': 'skip', 'message': '没有需要更新的股票'}

    fetcher = StockDataFetcher(adjust='qfq')  # 强制前复权
    results = {'success': [], 'failed': [], 'trade_date': str(date.today())}

    for symbol in symbols:
        try:
            count = fetcher.fetch_today(symbol, save_to_db=True)
            if count:
                results['success'].append(symbol)
                logger.info(f'{symbol} 更新成功')
            else:
                logger.info(f'{symbol} 今日无数据')
        except Exception as e:
            results['failed'].append({'symbol': symbol, 'error': str(e)})
            logger.error(f'{symbol} 更新失败: {e}')

    return results


@shared_task
def fetch_stock_history(symbol, start_date, end_date, adjust='qfq'):
    """
    异步下载单只股票历史数据（使用 data_fetcher）
    """
    from quant.data_fetcher import fetch_stock_data

    try:
        count = fetch_stock_data(symbol, start_date, end_date, adjust=adjust, save_to_db=True)
        return {'status': 'success', 'symbol': symbol, 'count': count}
    except Exception as e:
        logger.error(f'{symbol} 下载失败: {e}')
        return {'status': 'error', 'symbol': symbol, 'error': str(e)}


@shared_task(bind=True)
def run_backtest_task(self, strategy_id, symbol, start_date, end_date, initial_capital=100000):
    """
    异步执行回测任务
    """
    from quant.backtest_service import run_backtest
    from datetime import datetime as dt

    try:
        # 转换日期格式
        if isinstance(start_date, str):
            start_date = dt.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = dt.strptime(end_date, '%Y-%m-%d').date()

        result = run_backtest(
            strategy_id=strategy_id,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital
        )

        logger.info(f'回测完成: {result.id}')
        return result.id

    except Exception as e:
        logger.error(f'回测失败: {e}')
        raise self.retry(exc=e, countdown=60, max_retries=2)

