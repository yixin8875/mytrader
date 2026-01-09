"""
每小时自动化任务管理命令
用法: python manage.py run_hourly_tasks
"""
from django.core.management.base import BaseCommand
from trading.automation import run_hourly_tasks
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '运行每小时自动化任务：检查交易计划提醒、风险规则检查'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='模拟运行，不实际执行',
        )

    def handle(self, *args, **options):
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('模拟运行模式，不会实际执行任务'))
            self.stdout.write('将要执行的任务：')
            self.stdout.write('  1. 检查交易计划提醒')
            self.stdout.write('  2. 检查风险规则')
            return

        self.stdout.write('开始运行每小时自动化任务...')

        try:
            results = run_hourly_tasks()

            # 输出结果
            plan_reminders = results.get('plan_reminders', [])
            if plan_reminders:
                self.stdout.write(self.style.SUCCESS(
                    f'✓ 发送了 {len(plan_reminders)} 个计划提醒'
                ))
            else:
                self.stdout.write('  - 无需发送计划提醒')

            risk_checks = results.get('risk_checks', [])
            if risk_checks:
                self.stdout.write(self.style.WARNING(
                    f'⚠ 触发了 {len(risk_checks)} 个风险警告'
                ))
            else:
                self.stdout.write(self.style.SUCCESS('✓ 风险检查通过'))

            self.stdout.write(self.style.SUCCESS('\n每小时任务完成！'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'任务执行失败: {e}'))
            logger.exception('Hourly tasks failed')
            raise
