from django.core.management.base import BaseCommand
from quant.models import StockData
from decimal import Decimal
from datetime import datetime, timedelta
import akshare as ak


class Command(BaseCommand):
    help = '通过 AkShare 下载 A 股历史数据'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbols',
            nargs='+',
            help='股票代码列表，如 000001 600519'
        )
        parser.add_argument(
            '--start',
            type=str,
            default=(datetime.now() - timedelta(days=365)).strftime('%Y%m%d'),
            help='开始日期，格式 YYYYMMDD'
        )
        parser.add_argument(
            '--end',
            type=str,
            default=datetime.now().strftime('%Y%m%d'),
            help='结束日期，格式 YYYYMMDD'
        )
        parser.add_argument(
            '--adjust',
            type=str,
            default='qfq',
            choices=['', 'qfq', 'hfq'],
            help='复权类型：空=不复权, qfq=前复权, hfq=后复权'
        )

    def handle(self, *args, **options):
        symbols = options['symbols']
        if not symbols:
            self.stdout.write(self.style.WARNING('请指定股票代码，如 --symbols 000001 600519'))
            return

        start_date = options['start']
        end_date = options['end']
        adjust = options['adjust']

        for symbol in symbols:
            self.download_stock_data(symbol, start_date, end_date, adjust)

    def download_stock_data(self, symbol, start_date, end_date, adjust):
        self.stdout.write(f'下载 {symbol} 数据...')
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period='daily',
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )

            if df.empty:
                self.stdout.write(self.style.WARNING(f'{symbol} 无数据'))
                return

            created_count = 0
            updated_count = 0

            for _, row in df.iterrows():
                date = row['日期']
                if isinstance(date, str):
                    date = datetime.strptime(date, '%Y-%m-%d').date()

                defaults = {
                    'open': Decimal(str(row['开盘'])),
                    'high': Decimal(str(row['最高'])),
                    'low': Decimal(str(row['最低'])),
                    'close': Decimal(str(row['收盘'])),
                    'volume': int(row['成交量']),
                    'amount': Decimal(str(row['成交额'])) if '成交额' in row else None,
                }

                obj, created = StockData.objects.update_or_create(
                    symbol=symbol,
                    date=date,
                    defaults=defaults
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

            self.stdout.write(self.style.SUCCESS(
                f'{symbol}: 新增 {created_count} 条，更新 {updated_count} 条'
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'{symbol} 下载失败: {e}'))
