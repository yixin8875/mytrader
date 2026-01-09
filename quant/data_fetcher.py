"""
A股数据获取服务
- 强制使用前复权(qfq)保证价格连续性
- 集成交易日历，剔除非交易日
"""
import akshare as ak
import pandas as pd
from decimal import Decimal
from datetime import datetime, date, timedelta
from functools import lru_cache
from quant.models import StockData
import logging

logger = logging.getLogger(__name__)


class TradingCalendar:
    """A股交易日历"""

    _cache = None
    _cache_date = None

    @classmethod
    def get_trade_dates(cls, force_refresh=False):
        """获取交易日历（带缓存，每天刷新一次）"""
        today = date.today()
        if cls._cache is not None and cls._cache_date == today and not force_refresh:
            return cls._cache

        try:
            df = ak.tool_trade_date_hist_sina()
            cls._cache = set(pd.to_datetime(df['trade_date']).dt.date)
            cls._cache_date = today
            logger.info(f'交易日历已更新，共 {len(cls._cache)} 个交易日')
            return cls._cache
        except Exception as e:
            logger.error(f'获取交易日历失败: {e}')
            return cls._cache or set()

    @classmethod
    def is_trade_date(cls, check_date):
        """判断是否为交易日"""
        if isinstance(check_date, str):
            check_date = datetime.strptime(check_date, '%Y-%m-%d').date()
        elif isinstance(check_date, datetime):
            check_date = check_date.date()

        trade_dates = cls.get_trade_dates()
        return check_date in trade_dates

    @classmethod
    def get_trade_dates_range(cls, start_date, end_date):
        """获取日期范围内的交易日列表"""
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y%m%d').date()
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y%m%d').date()

        trade_dates = cls.get_trade_dates()
        return sorted([d for d in trade_dates if start_date <= d <= end_date])

    @classmethod
    def get_last_trade_date(cls, before_date=None):
        """获取最近的交易日"""
        if before_date is None:
            before_date = date.today()
        elif isinstance(before_date, str):
            before_date = datetime.strptime(before_date, '%Y-%m-%d').date()

        trade_dates = cls.get_trade_dates()
        past_dates = [d for d in trade_dates if d <= before_date]
        return max(past_dates) if past_dates else None

    @classmethod
    def get_next_trade_date(cls, after_date=None):
        """获取下一个交易日"""
        if after_date is None:
            after_date = date.today()
        elif isinstance(after_date, str):
            after_date = datetime.strptime(after_date, '%Y-%m-%d').date()

        trade_dates = cls.get_trade_dates()
        future_dates = [d for d in trade_dates if d > after_date]
        return min(future_dates) if future_dates else None


class StockDataFetcher:
    """
    A股数据获取器
    - 强制使用前复权(qfq)
    - 自动过滤非交易日
    """

    ADJUST_QFQ = 'qfq'  # 前复权（默认，推荐用于回测）
    ADJUST_HFQ = 'hfq'  # 后复权
    ADJUST_NONE = ''    # 不复权

    def __init__(self, adjust=ADJUST_QFQ):
        """
        初始化数据获取器
        adjust: 复权类型，默认前复权(qfq)
        """
        if adjust not in [self.ADJUST_QFQ, self.ADJUST_HFQ, self.ADJUST_NONE]:
            raise ValueError(f'无效的复权类型: {adjust}')
        self.adjust = adjust
        self.calendar = TradingCalendar()

    def fetch(self, symbol, start_date, end_date, save_to_db=True):
        """
        获取股票历史数据（前复权）

        Args:
            symbol: 股票代码，如 '000001'
            start_date: 开始日期，格式 'YYYYMMDD' 或 date 对象
            end_date: 结束日期
            save_to_db: 是否保存到数据库

        Returns:
            DataFrame 或 保存的记录数
        """
        # 格式化日期
        if isinstance(start_date, (date, datetime)):
            start_date = start_date.strftime('%Y%m%d')
        if isinstance(end_date, (date, datetime)):
            end_date = end_date.strftime('%Y%m%d')

        logger.info(f'获取 {symbol} 数据 ({start_date} ~ {end_date})，复权类型: {self.adjust}')

        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period='daily',
                start_date=start_date,
                end_date=end_date,
                adjust=self.adjust  # 强制使用指定复权类型
            )

            if df.empty:
                logger.warning(f'{symbol} 在指定日期范围内无数据')
                return df if not save_to_db else 0

            # 标准化列名
            df = self._normalize_columns(df)

            # 过滤非交易日（理论上 AkShare 返回的都是交易日，但做个保险）
            df = self._filter_trade_dates(df)

            if save_to_db:
                return self._save_to_db(symbol, df)

            return df

        except Exception as e:
            logger.error(f'{symbol} 数据获取失败: {e}')
            raise

    def fetch_today(self, symbol, save_to_db=True):
        """获取今日数据（如果是交易日）"""
        today = date.today()

        if not self.calendar.is_trade_date(today):
            logger.info(f'{today} 非交易日，跳过')
            return None

        return self.fetch(symbol, today, today, save_to_db)

    def fetch_latest(self, symbol, days=1, save_to_db=True):
        """获取最近N个交易日的数据"""
        end_date = self.calendar.get_last_trade_date()
        if not end_date:
            return None

        # 往前推足够多的自然日以确保覆盖N个交易日
        start_date = end_date - timedelta(days=days * 2)
        df = self.fetch(symbol, start_date, end_date, save_to_db=False)

        if df is not None and not df.empty:
            df = df.tail(days)
            if save_to_db:
                return self._save_to_db(symbol, df)

        return df

    def _normalize_columns(self, df):
        """标准化 DataFrame 列名"""
        column_map = {
            '日期': 'date',
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '收盘': 'close',
            '成交量': 'volume',
            '成交额': 'amount',
        }
        df = df.rename(columns=column_map)

        # 转换日期
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date

        return df

    def _filter_trade_dates(self, df):
        """过滤非交易日数据"""
        if 'date' not in df.columns:
            return df

        trade_dates = self.calendar.get_trade_dates()
        original_len = len(df)
        df = df[df['date'].isin(trade_dates)]

        if len(df) < original_len:
            logger.warning(f'过滤了 {original_len - len(df)} 条非交易日数据')

        return df

    def _save_to_db(self, symbol, df):
        """批量保存数据到数据库（优化性能）"""
        if df.empty:
            return 0

        # 查询已存在的日期
        existing_dates = set(
            StockData.objects.filter(
                symbol=symbol,
                date__in=df['date'].tolist()
            ).values_list('date', flat=True)
        )

        # 准备数据记录
        records_to_create = []
        records_to_update = []

        for _, row in df.iterrows():
            record_data = {
                'symbol': symbol,
                'date': row['date'],
                'open': Decimal(str(row['open'])),
                'high': Decimal(str(row['high'])),
                'low': Decimal(str(row['low'])),
                'close': Decimal(str(row['close'])),
                'volume': int(row['volume']),
                'amount': Decimal(str(row['amount'])) if 'amount' in row and pd.notna(row['amount']) else None,
            }

            if row['date'] in existing_dates:
                records_to_update.append(record_data)
            else:
                records_to_create.append(StockData(**record_data))

        created_count = 0
        updated_count = 0

        # 批量新增
        if records_to_create:
            StockData.objects.bulk_create(records_to_create, batch_size=500)
            created_count = len(records_to_create)

        # 批量更新
        if records_to_update:
            # 使用 bulk_create 的 update_conflicts 实现 upsert
            update_objs = [StockData(**r) for r in records_to_update]
            StockData.objects.bulk_create(
                update_objs,
                update_conflicts=True,
                unique_fields=['symbol', 'date'],
                update_fields=['open', 'high', 'low', 'close', 'volume', 'amount'],
                batch_size=500
            )
            updated_count = len(records_to_update)

        logger.info(f'{symbol}: 新增 {created_count} 条，更新 {updated_count} 条')
        return created_count + updated_count


# 便捷函数
def fetch_stock_data(symbol, start_date, end_date, adjust='qfq', save_to_db=True):
    """便捷函数：获取股票数据（默认前复权）"""
    fetcher = StockDataFetcher(adjust=adjust)
    return fetcher.fetch(symbol, start_date, end_date, save_to_db)


def is_trade_date(check_date=None):
    """便捷函数：判断是否为交易日"""
    if check_date is None:
        check_date = date.today()
    return TradingCalendar.is_trade_date(check_date)


def get_trade_dates(start_date, end_date):
    """便捷函数：获取日期范围内的交易日"""
    return TradingCalendar.get_trade_dates_range(start_date, end_date)
