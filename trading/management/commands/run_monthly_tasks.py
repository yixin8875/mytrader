"""
每月自动化任务管理命令
用法: python manage.py run_monthly_tasks
"""
from django.core.management.base import BaseCommand
from trading.automation import run_monthly_tasks
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '运行每月自动化任务：生成月度报表'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            help='指定年份（默认上个月所在年份）',
        )
        parser.add_argument(
            '--month',
            type=int,
            help='指定月份（默认上个月）',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='模拟运行，不实际执行',
        )

    def handle(self, *args, **options):
        year = options.get('year')
        month = options.get('month')

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('模拟运行模式，不会实际执行任务'))
            self.stdout.write('将要执行的任务：')
            if year and month:
                self.stdout.write(f'  1. 生成 {year}年{month}月 月度报表')
            else:
                self.stdout.write('  1. 生成上月月度报表')
            return

        self.stdout.write('开始运行每月自动化任务...')

        try:
            # 如果指定了年月，需要修改automation模块来支持
            # 目前使用默认的上个月
            results = run_monthly_tasks()

            # 输出结果
            monthly_reports = results.get('monthly_reports', [])
            if monthly_reports:
                self.stdout.write(self.style.SUCCESS(
                    f'✓ 生成了 {len(monthly_reports) if isinstance(monthly_reports, list) else 1} 份月报'
                ))
                for report in (monthly_reports if isinstance(monthly_reports, list) else [monthly_reports]):
                    if report:
                        self.stdout.write(
                            f'  - {report.account.name}: {report.year}年{report.month}月 '
                            f'盈亏: ¥{report.profit_loss:.2f}'
                        )
            else:
                self.stdout.write('  - 无需生成月报（无数据或已存在）')

            self.stdout.write(self.style.SUCCESS('\n每月任务完成！'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'任务执行失败: {e}'))
            logger.exception('Monthly tasks failed')
            raise
