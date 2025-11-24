# -*- coding: utf-8 -*-

"""Nobitex Exchange - Custom CCXT Implementation"""

from ccxt.base.exchange import Exchange
from ccxt.base.errors import ExchangeError, AuthenticationError, InsufficientFunds
from ccxt.base.types import Any, Balances, Int, Market, Num, OrderBook, OrderSide, OrderType, Str, Ticker, Trade, Order
from ccxt.base.precise import Precise
from typing import List, Optional, Dict
import hashlib
import hmac
import time
import requests


class nobitex(Exchange):
    """
    Nobitex Exchange - Iranian Cryptocurrency Exchange
    API Documentation: https://apidocs.nobitex.ir/
    """

    def describe(self) -> Any:
        return self.deep_extend(super(nobitex, self).describe(), {
            'id': 'nobitex',
            'name': 'Nobitex',
            'countries': ['IR'],
            'rateLimit': 200,  # 300 requests/minute = 200ms between requests
            'version': 'v2',
            'has': {
                'CORS': False,
                'spot': True,
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
                'fetchOrderBook': True,
                'fetchTicker': True,
                'fetchTickers': True,
                'fetchTrades': True,
                'createOrder': True,
                'createMarketOrder': True,
                'createLimitOrder': True,
                'createStopOrder': True,
                'cancelOrder': True,
            },
            'timeframes': {
                '1m': '1',
                '5m': '5',
                '15m': '15',
                '30m': '30',
                '1h': '60',
                '3h': '180',
                '4h': '240',
                '6h': '360',
                '1d': 'D',
                '2d': '2D',
                '3d': '3D',
            },
            'urls': {
                'logo': 'https://nobitex.ir/static/media/logo.png',
                'api': {
                    'public': 'https://apiv2.nobitex.ir',
                    'private': 'https://apiv2.nobitex.ir',
                },
                'www': 'https://nobitex.ir',
                'doc': 'https://apidocs.nobitex.ir/',
                'referral': None,
            },
            'api': {
                'public': {
                    'get': [
                        'market/stats',
                        'market/global-stats',
                        'v3/orderbook/{symbol}',
                        'v2/orderbook/{symbol}',
                        'v2/depth/{symbol}',
                        'v2/trades/{symbol}',
                        'market/udf/history',
                    ],
                },
                'private': {
                    'post': [
                        'auth/login',
                        'market/orders/add',
                        'market/orders/status',
                        'market/orders/cancel-old',
                        'market/orders/update-status',
                        'market/orders/cancel-batch',
                        'users/wallets/balance',
                    ],
                    'get': [
                        'market/orders/list',
                        'market/trades/list',
                        'users/wallets/list',
                    ],
                },
            },
            'fees': {
                'trading': {
                    'maker': self.parse_number('0.003'),
                    'taker': self.parse_number('0.004'),
                },
            },
            'requiredCredentials': {
                'apiKey': True,    # username
                'secret': True,    # password
            },
            'options': {
                'token': None,
                'token_expires': 0,
                'min_order_irt': 3000000,   # 3M Rial
                'min_order_usdt': 11,        # 11 USDT
            },
        })

    def _get_token(self):
        """Get or refresh authentication token"""
        options = self.safe_value(self.options, 'nobitex', {})
        token = self.safe_string(options, 'token')
        expires = self.safe_integer(options, 'token_expires', 0)

        if token and self.milliseconds() < expires:
            return token

        # Authenticate
        url = self.urls['api']['private'] + '/auth/login'
        payload = {
            'username': self.apiKey,
            'password': self.secret,
            'remember': 'yes',
        }

        response = requests.post(url, json=payload)
        data = response.json()

        if data.get('status') != 'ok':
            raise AuthenticationError(self.id + ' authentication failed: ' + str(data.get('message')))

        token = data['key']
        # Token expires in 30 days, refresh after 29 days
        expires = self.milliseconds() + (29 * 24 * 3600 * 1000)

        if 'nobitex' not in self.options:
            self.options['nobitex'] = {}
        self.options['nobitex']['token'] = token
        self.options['nobitex']['token_expires'] = expires

        return token

    def sign(self, path, api='public', method='GET', params={}, headers=None, body=None):
        """Sign API request"""
        url = self.urls['api'][api] + '/' + path

        if api == 'public':
            if params:
                url += '?' + self.urlencode(params)
        else:
            token = self._get_token()
            headers = {
                'Authorization': 'Token ' + token,
                'Content-Type': 'application/json',
            }
            if method == 'POST':
                body = self.json(params)
            elif params:
                url += '?' + self.urlencode(params)

        return {'url': url, 'method': method, 'body': body, 'headers': headers}

    def fetch_markets(self, params={}) -> List[Market]:
        """Fetch available trading pairs"""
        response = self.publicGetMarketStats(params)
        stats = self.safe_value(response, 'stats', {})

        result = []
        for symbol_key in stats.keys():
            parts = symbol_key.split('-')
            if len(parts) != 2:
                continue

            base = parts[0].upper()
            quote = parts[1].upper()
            symbol = base + '/' + quote
            market_id = base + quote

            min_cost = self.safe_integer(self.options, 'min_order_usdt', 11)
            if quote == 'IRT':
                min_cost = self.safe_integer(self.options, 'min_order_irt', 3000000)

            result.append({
                'id': market_id,
                'symbol': symbol,
                'base': base,
                'quote': quote,
                'baseId': base.lower(),
                'quoteId': quote.lower(),
                'active': True,
                'type': 'spot',
                'spot': True,
                'margin': False,
                'swap': False,
                'future': False,
                'option': False,
                'contract': False,
                'precision': {
                    'price': 8,
                    'amount': 8,
                    'base': 8,
                    'quote': 8,
                },
                'limits': {
                    'amount': {
                        'min': 0.00001,
                        'max': None,
                    },
                    'price': {
                        'min': None,
                        'max': None,
                    },
                    'cost': {
                        'min': min_cost,
                        'max': None,
                    },
                },
                'info': stats[symbol_key],
            })

        return result

    def fetch_ticker(self, symbol: str, params={}) -> Ticker:
        """Fetch ticker for a symbol"""
        self.load_markets()
        market = self.market(symbol)
        nobitex_symbol = market['baseId'] + '-' + market['quoteId']

        response = self.publicGetMarketStats(params)
        stats = self.safe_value(response, 'stats', {})

        if nobitex_symbol not in stats:
            raise ExchangeError(self.id + ' symbol not found: ' + symbol)

        data = stats[nobitex_symbol]
        return self.parse_ticker(data, market)

    def parse_ticker(self, ticker, market=None) -> Ticker:
        """Parse ticker data"""
        timestamp = self.safe_integer(ticker, 'time')
        symbol = None
        if market:
            symbol = market['symbol']

        return {
            'symbol': symbol,
            'timestamp': timestamp,
            'datetime': self.iso8601(timestamp) if timestamp else None,
            'high': self.safe_number(ticker, 'dayHigh'),
            'low': self.safe_number(ticker, 'dayLow'),
            'bid': self.safe_number(ticker, 'bestBuy'),
            'bidVolume': None,
            'ask': self.safe_number(ticker, 'bestSell'),
            'askVolume': None,
            'vwap': None,
            'open': None,
            'close': self.safe_number(ticker, 'latest'),
            'last': self.safe_number(ticker, 'latest'),
            'previousClose': None,
            'change': self.safe_number(ticker, 'dayChange'),
            'percentage': None,
            'average': None,
            'baseVolume': self.safe_number(ticker, 'volumeSrc'),
            'quoteVolume': self.safe_number(ticker, 'volumeDst'),
            'info': ticker,
        }

    def fetch_balance(self, params={}) -> Balances:
        """Fetch account balance"""
        self.load_markets()
        response = self.privateGetUsersWalletsList(params)
        return self.parse_balance(response)

    def parse_balance(self, response) -> Balances:
        """Parse balance response"""
        wallets = self.safe_value(response, 'wallets', [])
        result = {
            'info': response,
            'timestamp': self.milliseconds(),
            'datetime': self.iso8601(self.milliseconds()),
        }

        for wallet in wallets:
            currency = self.safe_string(wallet, 'currency', '').upper()
            balance = self.safe_string(wallet, 'balance', '0')
            blocked = self.safe_string(wallet, 'blocked', '0')

            account = self.account()
            account['total'] = balance
            account['used'] = blocked
            account['free'] = str(float(balance) - float(blocked))
            result[currency] = account

        return self.safe_balance(result)

    def create_order(self, symbol: str, type: OrderType, side: OrderSide, amount: float, price: Num = None, params={}) -> Order:
        """Create a new order"""
        self.load_markets()
        market = self.market(symbol)

        request = {
            'type': side,
        }

        # Determine source and destination currencies
        if side == 'sell':
            request['srcCurrency'] = market['base']
            request['dstCurrency'] = market['quote']
            request['amount'] = str(amount)
        else:
            request['srcCurrency'] = market['quote']
            request['dstCurrency'] = market['base']
            if type == 'limit' and price:
                total_cost = amount * float(price)
                request['amount'] = str(total_cost)
            else:
                request['amount'] = str(amount)

        # Set execution type
        if type == 'limit':
            if price is None:
                raise ExchangeError(self.id + ' createOrder() requires price for limit orders')
            request['price'] = str(price)
            request['execution'] = 'limit'
        elif type == 'market':
            request['execution'] = 'market'
        else:
            raise ExchangeError(self.id + ' createOrder() does not support order type: ' + type)

        response = self.privatePostMarketOrdersAdd(request)
        order = self.safe_value(response, 'order', {})
        return self.parse_order(order, market)

    def parse_order(self, order, market=None) -> Order:
        """Parse order data"""
        id = self.safe_string(order, 'id')
        timestamp = self.safe_integer(order, 'created_at')
        status_map = {
            'Active': 'open',
            'Done': 'closed',
            'Canceled': 'canceled',
            'Cancel': 'canceled',
        }
        status = status_map.get(self.safe_string(order, 'status'), 'open')

        order_type = self.safe_string(order, 'type', 'buy')
        execution = self.safe_string(order, 'execution', 'limit')

        # Parse symbol
        src = self.safe_string(order, 'srcCurrency', '').upper()
        dst = self.safe_string(order, 'dstCurrency', '').upper()

        if order_type == 'sell':
            symbol = src + '/' + dst
            side = 'sell'
        else:
            symbol = dst + '/' + src
            side = 'buy'

        price = self.safe_number(order, 'price')
        amount_str = self.safe_string(order, 'amount')
        matched = self.safe_number(order, 'matchedAmount', 0)
        unmatched = self.safe_number(order, 'unmatchedAmount', 0)

        # For buy orders, convert amounts from quote to base
        if side == 'buy' and price and price > 0:
            amount = float(amount_str) / price if amount_str else 0
            filled = matched / price if matched else 0
            remaining = unmatched / price if unmatched else 0
        else:
            amount = float(amount_str) if amount_str else 0
            filled = matched
            remaining = unmatched

        return {
            'id': id,
            'clientOrderId': None,
            'timestamp': timestamp,
            'datetime': self.iso8601(timestamp) if timestamp else None,
            'lastTradeTimestamp': None,
            'symbol': symbol,
            'type': execution,
            'timeInForce': None,
            'postOnly': None,
            'side': side,
            'price': price,
            'stopPrice': self.safe_number(order, 'stopPrice'),
            'amount': amount,
            'cost': filled * price if price and filled else None,
            'average': price,
            'filled': filled,
            'remaining': remaining,
            'status': status,
            'fee': {
                'cost': self.safe_number(order, 'fee', 0),
                'currency': dst if order_type == 'sell' else src,
            },
            'trades': None,
            'info': order,
        }

    def cancel_order(self, id: str, symbol: Str = None, params={}) -> Order:
        """Cancel an order"""
        self.load_markets()
        request = {
            'order': id,
            'status': 'canceled',
        }
        response = self.privatePostMarketOrdersUpdateStatus(self.extend(request, params))

        # Try to fetch the updated order
        try:
            return self.fetch_order(id, symbol)
        except Exception:
            return {
                'id': id,
                'status': 'canceled',
                'info': response,
            }

    def fetch_order(self, id: str, symbol: Str = None, params={}) -> Order:
        """Fetch order by ID"""
        self.load_markets()
        request = {'id': id}
        response = self.privatePostMarketOrdersStatus(self.extend(request, params))
        order = self.safe_value(response, 'order', {})
        if not order:
            raise ExchangeError(self.id + ' order not found: ' + id)
        return self.parse_order(order)

    def fetch_open_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        """Fetch open orders"""
        self.load_markets()
        request = {'status': 'open'}

        if symbol:
            market = self.market(symbol)
            request['srcCurrency'] = market['baseId']
            request['dstCurrency'] = market['quoteId']

        response = self.privateGetMarketOrdersList(self.extend(request, params))
        orders = self.safe_value(response, 'orders', [])

        result = [self.parse_order(order) for order in orders]

        if since:
            result = [o for o in result if o.get('timestamp') and o['timestamp'] >= since]
        if limit:
            result = result[:limit]

        return result

    def fetch_closed_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        """Fetch closed orders"""
        self.load_markets()
        request = {'status': 'done'}

        if symbol:
            market = self.market(symbol)
            request['srcCurrency'] = market['baseId']
            request['dstCurrency'] = market['quoteId']

        response = self.privateGetMarketOrdersList(self.extend(request, params))
        orders = self.safe_value(response, 'orders', [])

        result = [self.parse_order(order) for order in orders]

        if since:
            result = [o for o in result if o.get('timestamp') and o['timestamp'] >= since]
        if limit:
            result = result[:limit]

        return result

    def fetch_ohlcv(self, symbol: str, timeframe='1h', since: Int = None, limit: Int = None, params={}) -> List[list]:
        """Fetch OHLCV data"""
        self.load_markets()
        market = self.market(symbol)
        nobitex_symbol = market['id']
        nobitex_timeframe = self.safe_string(self.timeframes, timeframe, '60')

        request = {
            'symbol': nobitex_symbol,
            'resolution': nobitex_timeframe,
        }

        if since:
            request['from'] = int(since / 1000)
            # Max 90-day window
            max_to = request['from'] + (90 * 24 * 3600)
            current_time = int(self.milliseconds() / 1000)
            request['to'] = min(max_to, current_time)
        elif limit:
            to_time = int(self.milliseconds() / 1000)
            request['to'] = to_time
            timeframe_seconds = self.parse_timeframe(timeframe)
            request['from'] = to_time - (limit * timeframe_seconds)

        response = self.publicGetMarketUdfHistory(self.extend(request, params))

        if response.get('s') != 'ok':
            return []

        timestamps = self.safe_value(response, 't', [])
        opens = self.safe_value(response, 'o', [])
        highs = self.safe_value(response, 'h', [])
        lows = self.safe_value(response, 'l', [])
        closes = self.safe_value(response, 'c', [])
        volumes = self.safe_value(response, 'v', [])

        ohlcv = []
        for i in range(len(timestamps)):
            ohlcv.append([
                timestamps[i] * 1000,
                float(opens[i]),
                float(highs[i]),
                float(lows[i]),
                float(closes[i]),
                float(volumes[i]),
            ])

        if limit and len(ohlcv) > limit:
            ohlcv = ohlcv[-limit:]

        return ohlcv
