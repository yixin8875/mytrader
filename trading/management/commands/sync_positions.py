"""
同步持仓管理命令
用法: python manage.py sync_positions
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '根据已成交交易重新计算并同步所有持仓'

    def add_arguments(self, parser):
        parser.add_argument(
            '--account',
            type=int,
            help='仅同步指定账户ID的持仓',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='模拟运行，显示将要执行的操作但不实际执行',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='先清除所有持仓再重新计算',
        )

    def handle(self, *args, **options):
        from trading.models import Account, TradeLog, Position, Symbol

        account_id = options.get('account')
        dry_run = options['dry_run']
        clear_first = options['clear']

        if dry_run:
            self.stdout.write(self.style.WARNING('模拟运行模式'))

        # 获取账户
        if account_id:
            accounts = Account.objects.filter(id=account_id)
            if not accounts.exists():
                self.stdout.write(self.style.ERROR(f'账户ID {account_id} 不存在'))
                return
        else:
            accounts = Account.objects.filter(status='active')

        self.stdout.write(f'开始同步 {accounts.count()} 个账户的持仓...')

        total_positions = 0
        total_updated = 0

        for account in accounts:
            self.stdout.write(f'\n处理账户: {account.name}')

            if clear_first and not dry_run:
                Position.objects.filter(account=account).delete()
                self.stdout.write('  - 已清除现有持仓')

            # 获取该账户所有已成交的交易，按时间排序
            trades = TradeLog.objects.filter(
                account=account,
                status='filled'
            ).select_related('symbol').order_by('trade_time')

            if not trades.exists():
                self.stdout.write('  - 无交易记录')
                continue

            # 按标的分组计算持仓
            symbol_positions = {}

            for trade in trades:
                symbol = trade.symbol
                if not symbol:
                    continue

                if symbol.id not in symbol_positions:
                    symbol_positions[symbol.id] = {
                        'symbol': symbol,
                        'quantity': Decimal('0'),
                        'total_cost': Decimal('0'),
                        'current_price': Decimal('0'),
                    }

                pos = symbol_positions[symbol.id]
                price = trade.executed_price or trade.price
                qty = trade.quantity

                if trade.side == 'buy':
                    # 买入
                    if pos['quantity'] >= 0:
                        # 多头加仓
                        new_cost = pos['total_cost'] + price * qty
                        pos['quantity'] += qty
                        pos['total_cost'] = new_cost
                    else:
                        # 平空仓
                        if qty <= abs(pos['quantity']):
                            pos['quantity'] += qty
                        else:
                            remaining = qty - abs(pos['quantity'])
                            pos['quantity'] = remaining
                            pos['total_cost'] = price * remaining
                else:  # sell
                    # 卖出
                    if pos['quantity'] > 0:
                        # 平多仓
                        if qty <= pos['quantity']:
                            pos['quantity'] -= qty
                            if pos['quantity'] > 0:
                                # 按比例减少成本
                                avg_cost = pos['total_cost'] / (pos['quantity'] + qty)
                                pos['total_cost'] = avg_cost * pos['quantity']
                            else:
                                pos['total_cost'] = Decimal('0')
                        else:
                            # 超卖转空（仅期货）
                            if symbol.symbol_type in ['futures', 'forex', 'crypto']:
                                remaining = qty - pos['quantity']
                                pos['quantity'] = -remaining
                                pos['total_cost'] = price * remaining
                            else:
                                pos['quantity'] = Decimal('0')
                                pos['total_cost'] = Decimal('0')
                    else:
                        # 空头加仓
                        if symbol.symbol_type in ['futures', 'forex', 'crypto']:
                            pos['total_cost'] += price * qty
                            pos['quantity'] -= qty

                pos['current_price'] = price

            # 更新或创建持仓记录
            for symbol_id, pos_data in symbol_positions.items():
                qty = pos_data['quantity']
                symbol = pos_data['symbol']

                if qty == 0:
                    # 持仓为0，删除记录
                    if not dry_run:
                        Position.objects.filter(
                            account=account,
                            symbol=symbol
                        ).delete()
                    self.stdout.write(f'  - {symbol.code}: 已平仓')
                    continue

                # 计算均价
                avg_price = pos_data['total_cost'] / abs(qty) if qty != 0 else Decimal('0')
                current_price = pos_data['current_price']

                # 计算市值和盈亏
                market_value = abs(qty) * current_price

                if avg_price > 0 and current_price > 0:
                    if qty > 0:
                        price_diff = current_price - avg_price
                    else:
                        price_diff = avg_price - current_price

                    if symbol.symbol_type in ['futures', 'index']:
                        profit_loss = price_diff * abs(qty) * symbol.contract_size
                    else:
                        profit_loss = price_diff * abs(qty)

                    profit_loss_ratio = (price_diff / avg_price) * 100
                else:
                    profit_loss = Decimal('0')
                    profit_loss_ratio = Decimal('0')

                total_positions += 1

                if dry_run:
                    self.stdout.write(
                        f'  - {symbol.code}: 数量={qty}, 均价={avg_price:.4f}, '
                        f'现价={current_price:.4f}, 盈亏={profit_loss:.2f}'
                    )
                else:
                    position, created = Position.objects.update_or_create(
                        account=account,
                        symbol=symbol,
                        defaults={
                            'quantity': qty,
                            'avg_price': avg_price,
                            'current_price': current_price,
                            'market_value': market_value,
                            'profit_loss': profit_loss,
                            'profit_loss_ratio': profit_loss_ratio,
                        }
                    )
                    total_updated += 1
                    action = '创建' if created else '更新'
                    self.stdout.write(
                        f'  - {symbol.code}: {action} 数量={qty}, 均价={avg_price:.4f}, '
                        f'盈亏={profit_loss:.2f}'
                    )

        if dry_run:
            self.stdout.write(self.style.WARNING(f'\n模拟完成: 将处理 {total_positions} 个持仓'))
        else:
            self.stdout.write(self.style.SUCCESS(f'\n同步完成: 处理了 {total_updated} 个持仓'))
