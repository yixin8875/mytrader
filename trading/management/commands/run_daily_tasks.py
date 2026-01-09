"""
每日自动化任务管理命令
用法: python manage.py run_daily_tasks
"""
from django.core.management.base import BaseCommand
from trading.automation import run_daily_tasks
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '运行每日自动化任务：生成日报、更新风险快照、检查风险规则、过期处理等'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='模拟运行，不实际执行',
        )
        parser.add_argument(
            '--account',
            type=int,
            help='仅为指定账户ID运行任务',
        )

    def handle(self, *args, **options):
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('模拟运行模式，不会实际执行任务'))
            self.stdout.write('将要执行的任务：')
            self.stdout.write('  1. 生成每日报表（昨天）')
            self.stdout.write('  2. 更新风险快照')
            self.stdout.write('  3. 检查风险规则')
            self.stdout.write('  4. 过期交易计划')
            self.stdout.write('  5. 过期价格提醒')
            self.stdout.write('  6. 更新策略绩效')
            return

        self.stdout.write('开始运行每日自动化任务...')

        try:
            results = run_daily_tasks()

            # 输出结果
            daily_reports = results.get('daily_reports', [])
            if daily_reports:
                self.stdout.write(self.style.SUCCESS(
                    f'✓ 生成了 {len(daily_reports) if isinstance(daily_reports, list) else 1} 份日报'
                ))
            else:
                self.stdout.write('  - 无需生成日报（无交易或已存在）')

            snapshots = results.get('risk_snapshots', [])
            self.stdout.write(self.style.SUCCESS(
                f'✓ 更新了 {len(snapshots)} 个风险快照'
            ))

            alerts = results.get('risk_alerts', [])
            if alerts:
                self.stdout.write(self.style.WARNING(
                    f'⚠ 触发了 {len(alerts)} 个风险警告'
                ))
            else:
                self.stdout.write(self.style.SUCCESS('✓ 无风险警告'))

            expired_plans = results.get('expired_plans', 0)
            if expired_plans:
                self.stdout.write(f'  - 过期了 {expired_plans} 个交易计划')

            expired_alerts = results.get('expired_alerts', 0)
            if expired_alerts:
                self.stdout.write(f'  - 过期了 {expired_alerts} 个价格提醒')

            metrics = results.get('strategy_metrics', [])
            self.stdout.write(self.style.SUCCESS(
                f'✓ 更新了 {len(metrics)} 个策略绩效'
            ))

            self.stdout.write(self.style.SUCCESS('\n每日任务完成！'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'任务执行失败: {e}'))
            logger.exception('Daily tasks failed')
            raise
