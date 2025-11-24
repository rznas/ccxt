# -*- coding: utf-8 -*-

"""MetaTrader 5 Exchange - Custom CCXT Implementation"""

from ccxt.base.exchange import Exchange
from ccxt.base.errors import ExchangeError, NetworkError, AuthenticationError
from ccxt.base.types import Any, Balances, Int, Market, Num, OrderSide, OrderType, Str, Ticker, Order
from typing import List, Optional, Dict
from datetime import datetime, timedelta

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None


class mt5(Exchange):
    """
    MetaTrader 5 Exchange - Forex and CFD Trading
    Requires MetaTrader5 Python package and running MT5 terminal
    """

    def describe(self) -> Any:
        if not MT5_AVAILABLE:
            raise ExchangeError('MetaTrader5 Python package not installed. Install with: pip install MetaTrader5')

        return self.deep_extend(super(mt5, self).describe(), {
            'id': 'mt5',
            'name': 'MetaTrader5',
            'countries': ['Global'],
            'rateLimit': 50,
            'version': 'v1',
            'has': {
                'CORS': False,
                'spot': False,
                'margin': True,
                'swap': False,
                'future': False,
                'option': False,
                'fetchBalance': True,
                'fetchClosedOrders': True,
                'fetchMarkets': True,
                'fetchMyTrades': True,
                'fetchOHLCV': True,
                'fetchOpenOrders': True,
                'fetchOrder': True,
                'fetchOrderBook': False,
                'fetchTicker': True,
                'fetchTickers': True,
                'fetchTrades': False,
                'createOrder': True,
                'createMarketOrder': True,
                'createLimitOrder': True,
                'cancelOrder': True,
            },
            'timeframes': {
                '1m': getattr(mt5, 'TIMEFRAME_M1', None) if mt5 else None,
                '5m': getattr(mt5, 'TIMEFRAME_M5', None) if mt5 else None,
                '15m': getattr(mt5, 'TIMEFRAME_M15', None) if mt5 else None,
                '30m': getattr(mt5, 'TIMEFRAME_M30', None) if mt5 else None,
                '1h': getattr(mt5, 'TIMEFRAME_H1', None) if mt5 else None,
                '4h': getattr(mt5, 'TIMEFRAME_H4', None) if mt5 else None,
                '1d': getattr(mt5, 'TIMEFRAME_D1', None) if mt5 else None,
                '1w': getattr(mt5, 'TIMEFRAME_W1', None) if mt5 else None,
                '1M': getattr(mt5, 'TIMEFRAME_MN1', None) if mt5 else None,
            },
            'urls': {
                'logo': 'https://www.metatrader5.com/i/logo.png',
                'api': None,  # Local API through terminal
                'www': 'https://www.metatrader5.com',
                'doc': 'https://www.mql5.com/en/docs/python_metatrader5',
            },
            'requiredCredentials': {
                'apiKey': False,    # Uses account/password/server
                'secret': False,
            },
            'options': {
                'account': 0,
                'password': '',
                'server': '',
                'magic_number': 234000,
                'deviation': 20,
                'connected': False,
            },
        })

    def _connect(self):
        """Connect to MT5 terminal"""
        if self.safe_value(self.options, 'connected', False):
            return True

        # Initialize MT5
        if not mt5.initialize():
            error_code, error_msg = mt5.last_error()
            raise NetworkError(self.id + ' MT5 initialization failed: ' + str(error_msg))

        # Login if credentials provided
        account = self.safe_integer(self.options, 'account', 0)
        password = self.safe_string(self.options, 'password', '')
        server = self.safe_string(self.options, 'server', '')

        if account and password and server:
            authorized = mt5.login(login=account, password=password, server=server)
            if not authorized:
                error_code, error_msg = mt5.last_error()
                mt5.shutdown()
                raise AuthenticationError(self.id + ' MT5 login failed: ' + str(error_msg))

        self.options['connected'] = True
        return True

    def _disconnect(self):
        """Disconnect from MT5 terminal"""
        if self.safe_value(self.options, 'connected', False):
            mt5.shutdown()
            self.options['connected'] = False

    def fetch_markets(self, params={}) -> List[Market]:
        """Fetch available symbols from MT5"""
        self._connect()

        symbols = mt5.symbols_get()
        if symbols is None:
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to get symbols: ' + str(error_msg))

        result = []
        for symbol in symbols:
            if not symbol.visible:
                continue

            market_id = symbol.name
            # Parse base/quote (works for standard forex pairs)
            if len(symbol.name) >= 6:
                base = symbol.name[:3]
                quote = symbol.name[3:6]
                unified_symbol = base + '/' + quote
            else:
                base = symbol.name
                quote = 'USD'
                unified_symbol = symbol.name

            result.append({
                'id': market_id,
                'symbol': unified_symbol,
                'base': base,
                'quote': quote,
                'baseId': base,
                'quoteId': quote,
                'active': symbol.visible and symbol.trade_mode != 0,
                'type': 'spot',
                'spot': False,
                'margin': True,
                'swap': False,
                'future': False,
                'option': False,
                'contract': False,
                'precision': {
                    'price': symbol.digits,
                    'amount': len(str(symbol.volume_step).split('.')[-1]) if '.' in str(symbol.volume_step) else 0,
                },
                'limits': {
                    'amount': {
                        'min': symbol.volume_min,
                        'max': symbol.volume_max,
                    },
                    'price': {
                        'min': None,
                        'max': None,
                    },
                    'cost': {
                        'min': None,
                        'max': None,
                    },
                },
                'info': symbol._asdict(),
            })

        return result

    def fetch_balance(self, params={}) -> Balances:
        """Fetch account balance"""
        self._connect()

        account_info = mt5.account_info()
        if account_info is None:
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to get account info: ' + str(error_msg))

        currency = account_info.currency
        timestamp = self.milliseconds()

        result = {
            'info': account_info._asdict(),
            'timestamp': timestamp,
            'datetime': self.iso8601(timestamp),
        }

        account = self.account()
        account['free'] = str(account_info.margin_free)
        account['used'] = str(account_info.margin)
        account['total'] = str(account_info.equity)
        result[currency] = account

        return self.safe_balance(result)

    def fetch_ticker(self, symbol: str, params={}) -> Ticker:
        """Fetch ticker for a symbol"""
        self._connect()
        self.load_markets()
        market = self.market(symbol)
        mt5_symbol = market['id']

        # Ensure symbol is selected
        if not mt5.symbol_select(mt5_symbol, True):
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to select symbol ' + mt5_symbol + ': ' + str(error_msg))

        tick = mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to get tick for ' + mt5_symbol + ': ' + str(error_msg))

        return self.parse_ticker(tick, market)

    def parse_ticker(self, ticker, market=None) -> Ticker:
        """Parse MT5 tick to CCXT ticker"""
        timestamp = ticker.time * 1000
        last = ticker.last if ticker.last > 0 else (ticker.bid + ticker.ask) / 2

        return {
            'symbol': market['symbol'] if market else None,
            'timestamp': timestamp,
            'datetime': self.iso8601(timestamp),
            'high': None,
            'low': None,
            'bid': ticker.bid,
            'bidVolume': None,
            'ask': ticker.ask,
            'askVolume': None,
            'vwap': None,
            'open': None,
            'close': last,
            'last': last,
            'previousClose': None,
            'change': None,
            'percentage': None,
            'average': None,
            'baseVolume': getattr(ticker, 'volume_real', None),
            'quoteVolume': None,
            'info': ticker._asdict(),
        }

    def fetch_ohlcv(self, symbol: str, timeframe='1h', since: Int = None, limit: Int = None, params={}) -> List[list]:
        """Fetch OHLCV data"""
        self._connect()
        self.load_markets()
        market = self.market(symbol)
        mt5_symbol = market['id']
        mt5_timeframe = self.safe_value(self.timeframes, timeframe, mt5.TIMEFRAME_H1)

        # Ensure symbol is selected
        if not mt5.symbol_select(mt5_symbol, True):
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to select symbol ' + mt5_symbol + ': ' + str(error_msg))

        # Determine date range
        if since:
            date_from = datetime.fromtimestamp(since / 1000)
        else:
            date_from = datetime.now() - timedelta(days=30)

        if limit is None:
            limit = 500

        # Fetch rates
        rates = mt5.copy_rates_from(mt5_symbol, mt5_timeframe, date_from, limit)

        if rates is None:
            error_code, error_msg = mt5.last_error()
            if error_code == 1:  # No data available
                return []
            raise ExchangeError(self.id + ' failed to fetch OHLCV for ' + mt5_symbol + ': ' + str(error_msg))

        if len(rates) == 0:
            return []

        ohlcv = []
        for rate in rates:
            ohlcv.append([
                int(rate['time'] * 1000),
                float(rate['open']),
                float(rate['high']),
                float(rate['low']),
                float(rate['close']),
                float(rate['tick_volume']),
            ])

        return ohlcv

    def create_order(self, symbol: str, type: OrderType, side: OrderSide, amount: float, price: Num = None, params={}) -> Order:
        """Create a new order"""
        self._connect()
        self.load_markets()
        market = self.market(symbol)
        mt5_symbol = market['id']

        # Ensure symbol is selected
        if not mt5.symbol_select(mt5_symbol, True):
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to select symbol: ' + str(error_msg))

        # Get current tick
        tick = mt5.symbol_info_tick(mt5_symbol)
        if tick is None:
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to get tick: ' + str(error_msg))

        # Determine order type and price
        if type == 'market':
            trade_action = mt5.TRADE_ACTION_DEAL
            order_type_mt5 = mt5.ORDER_TYPE_BUY if side == 'buy' else mt5.ORDER_TYPE_SELL
            execution_price = tick.ask if side == 'buy' else tick.bid
        elif type == 'limit':
            trade_action = mt5.TRADE_ACTION_PENDING
            order_type_mt5 = mt5.ORDER_TYPE_BUY_LIMIT if side == 'buy' else mt5.ORDER_TYPE_SELL_LIMIT
            if price is None:
                raise ExchangeError(self.id + ' createOrder() requires price for limit orders')
            execution_price = float(price)
        else:
            raise ExchangeError(self.id + ' createOrder() unsupported order type: ' + type)

        # Get symbol info for filling type
        symbol_info = mt5.symbol_info(mt5_symbol)
        if symbol_info is None:
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' failed to get symbol info: ' + str(error_msg))

        # Determine filling type
        filling_type = mt5.ORDER_FILLING_FOK
        if symbol_info.filling_mode & 1:
            filling_type = mt5.ORDER_FILLING_FOK
        elif symbol_info.filling_mode & 2:
            filling_type = mt5.ORDER_FILLING_IOC
        elif symbol_info.filling_mode & 4:
            filling_type = mt5.ORDER_FILLING_RETURN

        # Prepare order request
        magic_number = self.safe_integer(self.options, 'magic_number', 234000)
        deviation = self.safe_integer(self.options, 'deviation', 20)

        request = {
            'action': trade_action,
            'symbol': mt5_symbol,
            'volume': float(amount),
            'type': order_type_mt5,
            'price': execution_price,
            'deviation': deviation,
            'magic': magic_number,
            'comment': 'CCXT',
            'type_time': mt5.ORDER_TIME_GTC,
            'type_filling': filling_type,
        }

        # Add SL/TP if provided
        if 'stopLoss' in params:
            request['sl'] = float(params['stopLoss'])
        if 'takeProfit' in params:
            request['tp'] = float(params['takeProfit'])

        # Check order
        result_check = mt5.order_check(request)
        if result_check is None or result_check.retcode != 0:
            error_msg = result_check.comment if result_check else 'Unknown error'
            raise ExchangeError(self.id + ' order check failed: ' + error_msg)

        # Send order
        result = mt5.order_send(request)
        if result is None:
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' order send failed: ' + str(error_msg))

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise ExchangeError(self.id + ' order failed (code ' + str(result.retcode) + '): ' + result.comment)

        return self.parse_order(result._asdict(), market)

    def parse_order(self, order, market=None) -> Order:
        """Parse MT5 order to CCXT format"""
        order_id = str(order.get('order', ''))
        timestamp = self.milliseconds()
        symbol = market['symbol'] if market else None

        return {
            'id': order_id,
            'clientOrderId': None,
            'timestamp': timestamp,
            'datetime': self.iso8601(timestamp),
            'lastTradeTimestamp': None,
            'symbol': symbol,
            'type': order.get('type', 'market'),
            'timeInForce': 'GTC',
            'postOnly': False,
            'side': order.get('side', 'buy'),
            'price': order.get('price'),
            'stopPrice': None,
            'amount': order.get('volume', 0),
            'cost': order.get('price', 0) * order.get('volume', 0),
            'average': order.get('price'),
            'filled': order.get('volume', 0),
            'remaining': 0,
            'status': 'closed' if order.get('retcode') == mt5.TRADE_RETCODE_DONE else 'open',
            'fee': None,
            'trades': None,
            'info': order,
        }

    def cancel_order(self, id: str, symbol: Str = None, params={}) -> Order:
        """Cancel a pending order"""
        self._connect()

        request = {
            'action': mt5.TRADE_ACTION_REMOVE,
            'order': int(id),
        }

        result = mt5.order_send(request)
        if result is None:
            error_code, error_msg = mt5.last_error()
            raise ExchangeError(self.id + ' order cancel failed: ' + str(error_msg))

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise ExchangeError(self.id + ' order cancel failed (code ' + str(result.retcode) + '): ' + result.comment)

        return {
            'id': id,
            'status': 'canceled',
            'info': result._asdict(),
        }

    def fetch_order(self, id: str, symbol: Str = None, params={}) -> Order:
        """Fetch order by ID"""
        self._connect()
        order_ticket = int(id)

        # Check active pending orders
        orders = mt5.orders_get(ticket=order_ticket)
        if orders and len(orders) > 0:
            return self.parse_order(orders[0]._asdict())

        # Check positions
        positions = mt5.positions_get(ticket=order_ticket)
        if positions and len(positions) > 0:
            return self.parse_order(positions[0]._asdict())

        # Check history
        history_orders = mt5.history_orders_get(ticket=order_ticket)
        if history_orders and len(history_orders) > 0:
            return self.parse_order(history_orders[0]._asdict())

        raise ExchangeError(self.id + ' order not found: ' + id)

    def fetch_open_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        """Fetch open pending orders"""
        self._connect()

        if symbol:
            market = self.market(symbol)
            mt5_symbol = market['id']
            orders = mt5.orders_get(symbol=mt5_symbol)
        else:
            orders = mt5.orders_get()

        if orders is None:
            error_code, error_msg = mt5.last_error()
            if error_code == 1:  # No orders
                return []
            raise ExchangeError(self.id + ' failed to fetch orders: ' + str(error_msg))

        result = [self.parse_order(order._asdict()) for order in orders]

        if limit:
            result = result[:limit]

        return result

    def __del__(self):
        """Cleanup on destruction"""
        try:
            self._disconnect()
        except:
            pass