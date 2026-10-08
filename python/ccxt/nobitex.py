# -*- coding: utf-8 -*-

"""
Nobitex - custom CCXT implementation (spot).

API reference: https://apidocs.nobitex.ir

Conventions
- Market ids are Nobitex symbols (BTCIRT, BTCUSDT). The rial currency id is ``rls``
  and its unified code is ``RLS``; prices of IRT markets are quoted in rials, as
  returned by the API. Override ``commonCurrencies`` to rename it if needed.
- ``amount`` is always in the base currency (Nobitex ``srcCurrency``) for both sides.

Authentication (selected by ``options['authMethod']`` or auto-detected)
- ``apiKey``: Nobitex API key. ``apiKey`` = public key, ``secret`` = Ed25519 private key
  (URL-safe base64). Requests are signed with the Nobitex-Key/-Signature/-Timestamp headers.
- ``token``: a token copied from the Nobitex panel, passed as the ``token`` credential.
- ``login``: username/password (``login``/``password``, or ``apiKey``/``secret`` for
  backwards compatibility). Tokens are fetched with captcha=api and refreshed on expiry;
  set ``twofa`` to the TOTP secret so the required X-TOTP header can be generated.
"""

import base64
from decimal import Decimal, InvalidOperation

from cryptography.hazmat.primitives.asymmetric import ed25519

from ccxt.base.exchange import Exchange
from ccxt.abstract.nobitex import ImplicitAPI
from ccxt.base.types import Any, Balances, Currencies, Int, Market, Num, Order, OrderBook, OrderSide, OrderType, Str, Strings, Ticker, Tickers, Trade
from typing import List
from ccxt.base.errors import ExchangeError
from ccxt.base.errors import AuthenticationError
from ccxt.base.errors import PermissionDenied
from ccxt.base.errors import ArgumentsRequired
from ccxt.base.errors import BadRequest
from ccxt.base.errors import BadSymbol
from ccxt.base.errors import MarketClosed
from ccxt.base.errors import InsufficientFunds
from ccxt.base.errors import InvalidOrder
from ccxt.base.errors import OrderNotFound
from ccxt.base.errors import DuplicateOrderId
from ccxt.base.errors import NotSupported
from ccxt.base.errors import DDoSProtection
from ccxt.base.decimal_to_precision import TICK_SIZE
from ccxt.base.precise import Precise


class NobitexCommon:
    """Request building, signing and parsing shared by the sync and async classes (no I/O)."""

    login = ''  # username for options['authMethod'] == 'login' (not a base Exchange attribute)

    def describe(self) -> Any:
        return self.deep_extend(super().describe(), {
            'id': 'nobitex',
            'name': 'Nobitex',
            'countries': ['IR'],
            'rateLimit': 200,  # 300 requests/minute; per-endpoint costs live in abstract/nobitex.py
            'version': 'v2',
            'certified': False,
            'pro': False,
            'has': {
                'CORS': None,
                'spot': True,
                'margin': False,
                'swap': False,
                'future': False,
                'option': False,
                'cancelAllOrders': True,
                'cancelOrder': True,
                'createLimitOrder': True,
                'createMarketOrder': True,
                'createOrder': True,
                'createStopLimitOrder': True,
                'createStopMarketOrder': True,
                'createStopOrder': True,
                'createTriggerOrder': True,
                'fetchBalance': True,
                'fetchClosedOrders': True,
                'fetchCurrencies': True,
                'fetchMarkets': True,
                'fetchMyTrades': True,
                'fetchOHLCV': True,
                'fetchOpenOrders': True,
                'fetchOrder': True,
                'fetchOrderBook': True,
                'fetchOrders': True,
                'fetchTicker': True,
                'fetchTickers': True,
                'fetchTrades': True,
                'sandbox': True,
                'signIn': True,
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
                '12h': '720',
                '1d': 'D',
                '2d': '2D',
                '3d': '3D',
            },
            'urls': {
                'logo': 'https://nobitex.ir/logo.png',
                'api': {
                    'public': 'https://apiv2.nobitex.ir',
                    'private': 'https://apiv2.nobitex.ir',
                },
                'test': {
                    'public': 'https://testnetapiv2.nobitex.ir',
                    'private': 'https://testnetapiv2.nobitex.ir',
                },
                'www': 'https://nobitex.ir',
                'doc': ['https://apidocs.nobitex.ir'],
                'fees': 'https://nobitex.ir/fees/',
            },
            'fees': {
                'trading': {
                    'tierBased': True,
                    'percentage': True,
                    'maker': self.parse_number('0.0025'),
                    'taker': self.parse_number('0.0025'),
                },
            },
            'precisionMode': TICK_SIZE,
            'requiredCredentials': {
                'apiKey': False,
                'secret': False,
            },
            'options': {
                'authMethod': None,  # 'apiKey' | 'token' | 'login'; None = auto-detect
                'userAgent': 'TraderBot/ccxt-nobitex-2.0',  # required by Nobitex for bots
                'loginPath': 'v2/auth/login',
                'loginRemember': True,
                'token': None,  # token obtained through sign_in()
                'tokenExpiresAt': None,
                'device': None,
                'systemOptionsTTL': 60000,  # cache v2/options between fetchCurrencies and fetchMarkets
                'systemOptions': None,
                'fetchOrdersPageSize': 100,
                'fetchMyTradesPageSize': 100,
            },
            'exceptions': {
                'exact': {
                    'InvalidOrderPrice': InvalidOrder,
                    'BadPrice': InvalidOrder,
                    'PriceConditionFailed': InvalidOrder,
                    'SmallOrder': InvalidOrder,
                    'OverValueOrder': InsufficientFunds,
                    'InsufficientBalance': InsufficientFunds,
                    'DuplicateOrder': DuplicateOrderId,
                    'DuplicateClientOrderId': DuplicateOrderId,
                    'InvalidMarketPair': BadSymbol,
                    'InvalidSymbol': BadSymbol,
                    'MarketClosed': MarketClosed,
                    'TradingUnavailable': PermissionDenied,
                    'FeatureUnavailable': NotSupported,
                    'NullIdAndClientOrderId': ArgumentsRequired,
                    'TooManyRequests': DDoSProtection,
                    'Invalid2FA': AuthenticationError,
                    'MissingOTP': AuthenticationError,
                    'MissingCaptcha': AuthenticationError,
                    'ValidationError': BadRequest,
                },
                'broad': {
                    'is not a valid market pair': BadSymbol,
                },
            },
        })

    # ------------------------------------------------------------------ auth

    def _auth_method(self):
        method = self.safe_string(self.options, 'authMethod')
        if method is not None:
            return method
        if self.token:
            return 'token'
        if self.apiKey and self.secret and self._looks_like_ed25519_secret(self.secret):
            return 'apiKey'
        if (self.login or self.apiKey) and (self.password or self.secret):
            return 'login'
        return None

    def _decode_ed25519_secret(self, secret):
        value = secret.strip()
        value += '=' * (-len(value) % 4)
        return base64.urlsafe_b64decode(value)

    def _looks_like_ed25519_secret(self, secret):
        try:
            return len(self._decode_ed25519_secret(secret)) == 32
        except (ValueError, TypeError):
            return False

    def _ed25519_signature(self, payload):
        privateKey = ed25519.Ed25519PrivateKey.from_private_bytes(self._decode_ed25519_secret(self.secret))
        return base64.urlsafe_b64encode(privateKey.sign(self.encode(payload))).decode('utf-8')

    def _has_valid_token(self):
        token = self.safe_string(self.options, 'token')
        if token is None:
            return False
        expiresAt = self.safe_integer(self.options, 'tokenExpiresAt')
        return (expiresAt is None) or (self.milliseconds() < expiresAt)

    def _clear_token(self):
        self.options['token'] = None
        self.options['tokenExpiresAt'] = None

    def _current_token(self):
        if self._auth_method() == 'token':
            return self.token
        return self.safe_string(self.options, 'token')

    def _login_request(self, params={}):
        username = self.login or self.apiKey
        password = self.password or self.secret
        if not username or not password:
            raise AuthenticationError(self.id + ' sign_in() requires login/password (or apiKey/secret) credentials')
        request = {
            'username': username,
            'password': password,
            'captcha': 'api',
        }
        if self.safe_bool(self.options, 'loginRemember', True):
            request['remember'] = 'yes'
        device = self.safe_string(self.options, 'device')
        if device is not None:
            request['device'] = device
        headers = {}
        otp = self.safe_string(params, 'otp')
        if otp is None and self.twofa:
            otp = self.totp(self.twofa)
        if otp is not None:
            headers['X-TOTP'] = otp
        path = self.safe_string(self.options, 'loginPath', 'v2/auth/login')
        return path, self.extend(request, self.omit(params, 'otp')), headers

    def _store_login_response(self, response):
        #
        #     {"status": "success", "key": "<token>", "expiresIn": 2592000, "device": "AlRyansW"}
        #
        token = self.safe_string(response, 'key')
        if token is None:
            if self.safe_string(response, 'mfaToken') is not None:
                raise AuthenticationError(self.id + ' login requested a second factor; set the twofa credential (TOTP secret) so X-TOTP is sent')
            raise AuthenticationError(self.id + ' login failed: ' + self.json(response))
        remember = self.safe_bool(self.options, 'loginRemember', True)
        expiresIn = self.safe_integer(response, 'expiresIn', 30 * 86400 if remember else 4 * 3600)
        margin = min(600, expiresIn // 2)  # refresh a little before the token expires
        self.options['token'] = token
        self.options['tokenExpiresAt'] = self.milliseconds() + (expiresIn - margin) * 1000
        device = self.safe_string(response, 'device')
        if device is not None:
            self.options['device'] = device

    def sign(self, path, api='public', method='GET', params={}, headers=None, body=None):
        query = self.omit(params, self.extract_params(path))
        requestPath = '/' + self.implode_params(path, params)
        url = self.urls['api'][api] + requestPath
        headers = self.extend({'User-Agent': self.safe_string(self.options, 'userAgent')}, headers or {})
        if method == 'GET':
            if query:
                suffix = '?' + self.urlencode(query)
                url += suffix
                requestPath += suffix
        else:
            body = self.json(query)
            headers['Content-Type'] = 'application/json'
        if api == 'private':
            authMethod = self._auth_method()
            if authMethod == 'apiKey':
                timestamp = str(self.seconds())
                payload = timestamp + method + requestPath + (body or '')
                headers['Nobitex-Key'] = self.apiKey
                headers['Nobitex-Signature'] = self._ed25519_signature(payload)
                headers['Nobitex-Timestamp'] = timestamp
            else:
                token = self._current_token()
                if token is None:
                    raise AuthenticationError(self.id + ' requires an API key (apiKey + Ed25519 secret), a token, or login credentials')
                headers['Authorization'] = 'Token ' + token
        return {'url': url, 'method': method, 'body': body, 'headers': headers}

    def handle_errors(self, code, reason, url, method, headers, body, response, requestHeaders, requestBody):
        #
        #     {"status": "failed", "code": "SmallOrder", "message": "..."}
        #     {"status": "failed", "code": "TooManyRequests", "message": "...", "backOff": 12, "limit": 60}
        #     {"detail": "اطلاعات برای اعتبارسنجی ارسال نشده است."}  (HTTP 401)
        #     {"s": "error", "errmsg": "Invalid resolution!"}  (market/udf/history)
        #
        if response is None or not isinstance(response, dict):
            if code == 429:
                raise DDoSProtection(self.id + ' ' + body)
            return None
        feedback = self.id + ' ' + body
        if self.safe_string(response, 's') == 'error':
            raise BadRequest(feedback)
        errorCode = self.safe_string(response, 'code')
        if code == 401:
            if self._auth_method() == 'login':
                self._clear_token()
            raise AuthenticationError(feedback)
        if code == 429 or errorCode == 'TooManyRequests':
            raise DDoSProtection(feedback)
        if self.safe_string(response, 'status') != 'failed' and code < 400:
            return None
        if code >= 500:
            return None  # let the base class raise ExchangeNotAvailable
        self.throw_exactly_matched_exception(self.exceptions['exact'], errorCode, feedback)
        message = self.safe_string_2(response, 'message', 'detail')
        if message is not None:
            self.throw_broadly_matched_exception(self.exceptions['broad'], message, feedback)
        if url.find('market/orders/update-status') >= 0:
            raise InvalidOrder(feedback)  # transition rejected, e.g. order is already closed
        if url.find('market/orders/status') >= 0 and (code == 404 or code == 400):
            raise OrderNotFound(feedback)
        raise ExchangeError(feedback)

    # --------------------------------------------------------------- helpers

    def _normalize_number_string(self, value):
        # Nobitex returns zeros like "0E-10", which Precise does not parse
        if value is None:
            return None
        value = str(value)
        if 'e' in value or 'E' in value:
            try:
                return format(Decimal(value), 'f')
            except InvalidOperation:
                return value
        return value

    def _safe_num_string(self, obj, key):
        return self._normalize_number_string(self.safe_string(obj, key))

    def _market_id(self, baseId, quoteId):
        quote = 'IRT' if quoteId == 'rls' else quoteId.upper()
        return baseId.upper() + quote

    def _safe_market_from_pair(self, pair, market=None):
        # converts "btc-rls" / "BTC-RLS" (stats keys and order.market) to a market
        if pair is None:
            return market
        parts = pair.lower().split('-')
        if len(parts) != 2:
            return market
        marketId = self._market_id(parts[0], parts[1])
        if (self.markets_by_id is not None) and (marketId in self.markets_by_id):
            return self.safe_market(marketId)
        return market

    def _cached_system_options(self):
        cached = self.safe_dict(self.options, 'systemOptions')
        if cached is None:
            return None
        ttl = self.safe_integer(self.options, 'systemOptionsTTL', 60000)
        if self.milliseconds() - self.safe_integer(cached, 'timestamp', 0) > ttl:
            return None
        return self.safe_dict(cached, 'response')

    def _store_system_options(self, response):
        self.options['systemOptions'] = {'timestamp': self.milliseconds(), 'response': response}
        return response

    # -------------------------------------------------------------- markets

    def parse_markets_response(self, statsResponse, optionsResponse) -> List[Market]:
        #
        # market/stats: {"stats": {"btc-rls": {"isClosed": false, "bestSell": "...", ...}}}
        # v2/options:   {"nobitex": {"amountPrecisions": {"BTCIRT": "0.000001"}, "pricePrecisions": {...},
        #                "minOrders": {"rls": "500000", "usdt": "0.5"}, "maxOrders": {...},
        #                "tradingFees": {"makerFees": ["0.25", ...], "makerFeesTether": [...], ...},
        #                "activeCurrencies": ["rls", "btc", ...]}}
        #
        stats = self.safe_dict(statsResponse, 'stats', {})
        settings = self.safe_dict(optionsResponse, 'nobitex', {})
        amountPrecisions = self.safe_dict(settings, 'amountPrecisions', {})
        pricePrecisions = self.safe_dict(settings, 'pricePrecisions', {})
        minOrders = self.safe_dict(settings, 'minOrders', {})
        maxOrders = self.safe_dict(settings, 'maxOrders', {})
        tradingFees = self.safe_dict(settings, 'tradingFees', {})
        activeCurrencies = self.safe_list(settings, 'activeCurrencies')
        result = []
        for key in list(stats.keys()):
            parts = key.split('-')
            if len(parts) != 2:
                continue
            baseId = parts[0]
            quoteId = parts[1]
            id = self._market_id(baseId, quoteId)
            base = self.safe_currency_code(baseId)
            quote = self.safe_currency_code(quoteId)
            ticker = stats[key]
            active = not self.safe_bool(ticker, 'isClosed', False)
            if active and (activeCurrencies is not None):
                active = self.in_array(baseId, activeCurrencies)
            feeSuffix = 'Tether' if quoteId == 'usdt' else ''
            maker = self.safe_string(self.safe_list(tradingFees, 'makerFees' + feeSuffix, []), 0)
            taker = self.safe_string(self.safe_list(tradingFees, 'takerFees' + feeSuffix, []), 0)
            amountTick = self.safe_string(amountPrecisions, id)
            result.append(self.safe_market_structure({
                'id': id,
                'symbol': base + '/' + quote,
                'base': base,
                'quote': quote,
                'settle': None,
                'baseId': baseId,
                'quoteId': quoteId,
                'settleId': None,
                'type': 'spot',
                'spot': True,
                'margin': False,
                'swap': False,
                'future': False,
                'option': False,
                'active': active,
                'contract': False,
                'linear': None,
                'inverse': None,
                'taker': self.parse_number(Precise.string_div(taker, '100')) if taker is not None else None,
                'maker': self.parse_number(Precise.string_div(maker, '100')) if maker is not None else None,
                'contractSize': None,
                'expiry': None,
                'expiryDatetime': None,
                'strike': None,
                'optionType': None,
                'precision': {
                    'amount': self.parse_number(amountTick),
                    'price': self.parse_number(self.safe_string(pricePrecisions, id)),
                },
                'limits': {
                    'leverage': {'min': None, 'max': None},
                    'amount': {'min': self.parse_number(amountTick), 'max': None},
                    'price': {'min': None, 'max': None},
                    'cost': {
                        'min': self.safe_number(minOrders, quoteId),
                        'max': self.safe_number(maxOrders, quoteId),
                    },
                },
                'created': None,
                'info': {'pair': key, 'stats': ticker},
            }))
        return result

    def parse_currencies_response(self, optionsResponse) -> Currencies:
        #
        #     {"coins": [{"coin": "usdt", "name": "Tether", "displayPrecision": "0.01", "defaultNetwork": "TRX",
        #       "networkList": {"TRX": {"network": "TRX", "depositEnable": true, "withdrawEnable": true,
        #         "withdrawFee": "1", "withdrawMin": "5", "withdrawMax": "50000",
        #         "withdrawIntegerMultiple": "0.000001", "depositMin": "0.01", ...}}}]}
        #
        coins = self.safe_list(optionsResponse, 'coins', [])
        result = {}
        for coin in coins:
            id = self.safe_string(coin, 'coin')
            if id is None:
                continue
            code = self.safe_currency_code(id)
            networkList = self.safe_dict(coin, 'networkList', {})
            defaultNetwork = self.safe_string(coin, 'defaultNetwork')
            networks = {}
            for networkId in list(networkList.keys()):
                network = networkList[networkId]
                depositEnable = self.safe_bool(network, 'depositEnable')
                withdrawEnable = self.safe_bool(network, 'withdrawEnable')
                networks[networkId] = {
                    'id': networkId,
                    'network': networkId,
                    'active': depositEnable and withdrawEnable,
                    'deposit': depositEnable,
                    'withdraw': withdrawEnable,
                    'fee': self.safe_number(network, 'withdrawFee'),
                    'precision': self.safe_number(network, 'withdrawIntegerMultiple'),
                    'limits': {
                        'withdraw': {'min': self.safe_number(network, 'withdrawMin'), 'max': self.safe_number(network, 'withdrawMax')},
                        'deposit': {'min': self.safe_number(network, 'depositMin'), 'max': None},
                    },
                    'info': network,
                }
            default = self.safe_dict(networks, defaultNetwork, {})
            result[code] = self.safe_currency_structure({
                'id': id,
                'code': code,
                'name': self.safe_string(coin, 'name'),
                'type': 'crypto',
                'active': None,
                'deposit': None,
                'withdraw': None,
                'fee': self.safe_number(default, 'fee'),
                'precision': self.safe_number(coin, 'displayPrecision'),
                'limits': {
                    'amount': {'min': None, 'max': None},
                    'withdraw': self.safe_dict(self.safe_dict(default, 'limits', {}), 'withdraw', {'min': None, 'max': None}),
                    'deposit': self.safe_dict(self.safe_dict(default, 'limits', {}), 'deposit', {'min': None, 'max': None}),
                },
                'networks': networks,
                'info': coin,
            })
        if 'RLS' not in result:
            result['RLS'] = self.safe_currency_structure({
                'id': 'rls',
                'code': 'RLS',
                'name': 'Iranian Rial',
                'type': 'fiat',
                'precision': self.parse_number('1'),
                'networks': {},
                'info': {},
            })
        return result

    # --------------------------------------------------------------- parsers

    def parse_ticker(self, ticker: dict, market: Market = None) -> Ticker:
        #
        #     {"isClosed": false, "bestSell": "85566.78", "bestBuy": "85503.24", "volumeSrc": "13.78",
        #      "volumeDst": "1183454.42", "latest": "85543.15", "mark": "85462.25", "dayLow": "84800",
        #      "dayHigh": "86500", "dayOpen": "85700", "dayClose": "85543.15", "dayChange": "-0.18"}
        #
        last = self.safe_string(ticker, 'latest')
        return self.safe_ticker({
            'symbol': self.safe_symbol(None, market),
            'timestamp': None,  # market/stats has no timestamp
            'datetime': None,
            'high': self.safe_string(ticker, 'dayHigh'),
            'low': self.safe_string(ticker, 'dayLow'),
            'bid': self.safe_string(ticker, 'bestBuy'),
            'bidVolume': None,
            'ask': self.safe_string(ticker, 'bestSell'),
            'askVolume': None,
            'vwap': None,
            'open': self.safe_string(ticker, 'dayOpen'),
            'close': last,
            'last': last,
            'previousClose': None,
            'change': None,
            'percentage': self.safe_string(ticker, 'dayChange'),
            'average': None,
            'baseVolume': self.safe_string(ticker, 'volumeSrc'),
            'quoteVolume': self.safe_string(ticker, 'volumeDst'),
            'markPrice': self.safe_string(ticker, 'mark'),
            'info': ticker,
        }, market)

    def parse_tickers_response(self, response, symbols: Strings = None) -> Tickers:
        stats = self.safe_dict(response, 'stats', {})
        result = {}
        for pair in list(stats.keys()):
            market = self._safe_market_from_pair(pair)
            if market is None:
                continue
            ticker = self.parse_ticker(stats[pair], market)
            result[ticker['symbol']] = ticker
        return self.filter_by_array_tickers(result, 'symbol', symbols)

    def parse_trade(self, trade: dict, market: Market = None) -> Trade:
        #
        # public (v2/trades/{symbol})
        #
        #     {"time": 1588689375067, "price": "1470000110", "volume": "0.002", "type": "buy"}
        #
        # private (market/trades/list)
        #
        #     {"id": 123412, "orderId": 1231222, "market": "USDT-RLS", "timestamp": "2022-07-05T09:57:38.560820+00:00",
        #      "type": "sell", "price": "316800", "amount": "57.3605", "total": "18171806.4", "fee": "27257.7096"}
        #
        market = self._safe_market_from_pair(self.safe_string(trade, 'market'), market)
        timestamp = self.safe_integer(trade, 'time')
        if timestamp is None:
            timestamp = self.parse8601(self.safe_string(trade, 'timestamp'))
        side = self.safe_string(trade, 'type')
        fee = None
        feeCost = self._safe_num_string(trade, 'fee')
        if feeCost is not None and market is not None:
            # Nobitex charges the fee in the currency the user receives
            fee = {
                'cost': feeCost,
                'currency': market['base'] if side == 'buy' else market['quote'],
            }
        return self.safe_trade({
            'id': self.safe_string(trade, 'id'),
            'order': self.safe_string(trade, 'orderId'),
            'timestamp': timestamp,
            'datetime': self.iso8601(timestamp),
            'symbol': self.safe_symbol(None, market),
            'type': None,
            'side': side,
            'takerOrMaker': None,
            'price': self._safe_num_string(trade, 'price'),
            'amount': self._normalize_number_string(self.safe_string_2(trade, 'amount', 'volume')),
            'cost': self._safe_num_string(trade, 'total'),
            'fee': fee,
            'info': trade,
        }, market)

    def parse_order_status(self, status: Str):
        statuses = {
            'new': 'open',
            'active': 'open',
            'inactive': 'open',  # stop order waiting for its trigger
            'done': 'closed',
            'canceled': 'canceled',
        }
        return self.safe_string(statuses, status, status)

    def parse_order(self, order: dict, market: Market = None) -> Order:
        #
        #     {"id": 26, "type": "sell", "execution": "StopMarket", "market": "DOGE-RLS", "srcCurrency": "Dogecoin",
        #      "dstCurrency": "﷼", "price": "market", "amount": "64", "param1": "47500", "totalPrice": "0",
        #      "totalOrderPrice": "3008000", "matchedAmount": "0", "unmatchedAmount": "64", "status": "Inactive",
        #      "partial": false, "fee": 0, "created_at": "2022-01-17T12:14:18.005896+00:00",
        #      "averagePrice": "0", "clientOrderId": "order1", "tradeType": "Spot"}
        #
        market = self._safe_market_from_pair(self.safe_string(order, 'market'), market)
        timestamp = self.parse8601(self.safe_string(order, 'created_at'))
        execution = self.safe_string_lower(order, 'execution')
        types = {
            'limit': 'limit',
            'market': 'market',
            'stopmarket': 'market',
            'stoplimit': 'limit',
        }
        price = self.safe_string(order, 'price')
        if price == 'market':
            price = None
        average = self._safe_num_string(order, 'averagePrice')
        if average is not None and Precise.string_eq(average, '0'):
            average = None
        side = self.safe_string(order, 'type')
        fee = None
        feeCost = self._safe_num_string(order, 'fee')
        if feeCost is not None and market is not None:
            fee = {
                'cost': self.parse_number(feeCost),  # safe_order does not parse a single fee
                'currency': market['base'] if side == 'buy' else market['quote'],
            }
        return self.safe_order({
            'id': self.safe_string(order, 'id'),
            'clientOrderId': self.safe_string(order, 'clientOrderId'),
            'timestamp': timestamp,
            'datetime': self.iso8601(timestamp),
            'lastTradeTimestamp': None,
            'lastUpdateTimestamp': None,
            'symbol': self.safe_symbol(None, market),
            'type': self.safe_string(types, execution, execution),
            'timeInForce': None,
            'postOnly': None,
            'reduceOnly': None,
            'side': side,
            'price': self._normalize_number_string(price),
            'triggerPrice': self._safe_num_string(order, 'param1'),
            'amount': self._safe_num_string(order, 'amount'),
            'filled': self._safe_num_string(order, 'matchedAmount'),
            'remaining': self._safe_num_string(order, 'unmatchedAmount'),
            'average': average,
            'cost': None,  # computed by safe_order from filled * average
            'status': self.parse_order_status(self.safe_string_lower(order, 'status')),
            'fee': fee,
            'trades': None,
            'info': order,
        }, market)

    def parse_balance(self, response) -> Balances:
        #
        #     {"status": "ok", "wallets": [{"id": 2693280, "currency": "rls", "balance": "746212980",
        #       "blockedBalance": "0", "activeBalance": "746212980", "rialBalance": 746212980, ...}]}
        #
        result = {'info': response}
        wallets = self.safe_list(response, 'wallets', [])
        for wallet in wallets:
            code = self.safe_currency_code(self.safe_string(wallet, 'currency'))
            account = self.account()
            account['total'] = self._safe_num_string(wallet, 'balance')
            account['used'] = self._safe_num_string(wallet, 'blockedBalance')
            account['free'] = self._safe_num_string(wallet, 'activeBalance')
            result[code] = account
        return self.safe_balance(result)

    def parse_ohlcvs_response(self, response, market: Market = None, since: Int = None, limit: Int = None) -> List[list]:
        #
        #     {"s": "ok", "t": [1562095800], "o": [146272500], "h": [155869600], "l": [140062400],
        #      "c": [151440200], "v": [18.221362316]}
        #     {"s": "no_data"}
        #
        if self.safe_string(response, 's') != 'ok':
            return []
        times = self.safe_list(response, 't', [])
        opens = self.safe_list(response, 'o', [])
        highs = self.safe_list(response, 'h', [])
        lows = self.safe_list(response, 'l', [])
        closes = self.safe_list(response, 'c', [])
        volumes = self.safe_list(response, 'v', [])
        result = []
        for i in range(0, len(times)):
            result.append([
                self.safe_integer(times, i) * 1000,
                self.safe_number(opens, i),
                self.safe_number(highs, i),
                self.safe_number(lows, i),
                self.safe_number(closes, i),
                self.safe_number(volumes, i),
            ])
        result = self.sort_by(result, 0)
        return self.filter_by_since_limit(result, since, limit, 0)

    # ------------------------------------------------------ request builders

    def _ohlcv_request(self, market: Market, timeframe, since: Int, limit: Int, params):
        maxLimit = 500  # Nobitex returns at most 500 candles per request
        limit = maxLimit if limit is None else min(limit, maxLimit)
        duration = self.parse_timeframe(timeframe)
        until = self.safe_integer(params, 'until')
        params = self.omit(params, 'until')
        end = self.seconds() if until is None else self.parse_to_int(until / 1000)
        request = {
            'symbol': market['id'],
            'resolution': self.safe_string(self.timeframes, timeframe, timeframe),
        }
        if since is None:
            request['to'] = end
            request['countback'] = limit
        else:
            start = self.parse_to_int(since / 1000)
            request['from'] = start
            request['to'] = min(start + duration * limit - 1, end)
        return self.extend(request, params)

    def _create_order_request(self, market: Market, type: OrderType, side: OrderSide, amount: float, price: Num = None, params={}):
        symbol = market['symbol']
        request = {
            'type': side,
            'srcCurrency': market['baseId'],
            'dstCurrency': market['quoteId'],
            'amount': self.amount_to_precision(symbol, amount),
        }
        triggerPrice = self.safe_string_n(params, ['triggerPrice', 'stopPrice', 'stopLossPrice'])
        clientOrderId = self.safe_string(params, 'clientOrderId')
        mode = self.safe_string(params, 'mode')
        params = self.omit(params, ['triggerPrice', 'stopPrice', 'stopLossPrice', 'clientOrderId', 'mode'])
        if mode == 'oco':
            stopLimitPrice = self.safe_string(params, 'stopLimitPrice')
            if price is None or triggerPrice is None or stopLimitPrice is None:
                raise ArgumentsRequired(self.id + ' createOrder() OCO orders require price, a triggerPrice and params["stopLimitPrice"]')
            params = self.omit(params, 'stopLimitPrice')
            request['mode'] = 'oco'
            request['price'] = self.price_to_precision(symbol, price)
            request['stopPrice'] = self.price_to_precision(symbol, triggerPrice)
            request['stopLimitPrice'] = self.price_to_precision(symbol, stopLimitPrice)
        elif triggerPrice is not None:
            request['stopPrice'] = self.price_to_precision(symbol, triggerPrice)
            if type == 'limit':
                if price is None:
                    raise ArgumentsRequired(self.id + ' createOrder() requires a price for stop-limit orders')
                request['execution'] = 'stop_limit'
                request['price'] = self.price_to_precision(symbol, price)
            elif type == 'market':
                request['execution'] = 'stop_market'
            else:
                raise InvalidOrder(self.id + ' createOrder() does not support order type ' + type)
        elif type == 'limit':
            if price is None:
                raise ArgumentsRequired(self.id + ' createOrder() requires a price for limit orders')
            request['execution'] = 'limit'
            request['price'] = self.price_to_precision(symbol, price)
        elif type == 'market':
            request['execution'] = 'market'
            if price is not None:
                # optional: bounds the execution range (strongly recommended by Nobitex)
                request['price'] = self.price_to_precision(symbol, price)
        else:
            raise InvalidOrder(self.id + ' createOrder() does not support order type ' + type)
        if clientOrderId is not None:
            request['clientOrderId'] = clientOrderId
        return self.extend(request, params)

    def _order_id_request(self, idKey: str, id: Str, params={}):
        clientOrderId = self.safe_string(params, 'clientOrderId')
        params = self.omit(params, 'clientOrderId')
        request = {}
        if clientOrderId is not None:
            request['clientOrderId'] = clientOrderId
        elif id is not None:
            request[idKey] = self.parse_to_int(id)
        else:
            raise ArgumentsRequired(self.id + ' requires an order id or params["clientOrderId"]')
        return self.extend(request, params)

    def _parse_order_response(self, response, market: Market = None) -> Order:
        order = self.safe_dict(response, 'order')
        if order is None:
            orders = self.safe_list(response, 'orders', [])  # OCO returns the order pair
            order = self.safe_dict(orders, 0, {})
        return self.parse_order(order, market)

    def _orders_list_request(self, status: str, market: Market = None, limit: Int = None, params={}):
        request = {
            'status': status,
            'details': 2,  # includes id, status, fee, created_at and averagePrice
            'tradeType': 'spot',
        }
        if market is not None:
            request['srcCurrency'] = market['baseId']
            request['dstCurrency'] = market['quoteId']
        pageSize = self.safe_integer(self.options, 'fetchOrdersPageSize', 100)
        request['pageSize'] = pageSize if limit is None else min(limit, pageSize)
        return self.extend(request, params)

    def _my_trades_request(self, market: Market = None, limit: Int = None, params={}):
        request = {}
        if market is not None:
            request['srcCurrency'] = market['baseId']
            request['dstCurrency'] = market['quoteId']
        pageSize = self.safe_integer(self.options, 'fetchMyTradesPageSize', 100)
        request['pageSize'] = min(pageSize if limit is None else limit, 500)
        return self.extend(request, params)

    def _cancel_all_orders_request(self, market: Market = None, params={}):
        request = {}
        if market is not None:
            request['srcCurrency'] = market['baseId']
            request['dstCurrency'] = market['quoteId']
        return self.extend(request, params)


class nobitex(NobitexCommon, Exchange, ImplicitAPI):

    def request(self, path, api: Any = 'public', method='GET', params={}, headers: Any = None, body: Any = None, config={}):
        if api == 'private' and self._auth_method() == 'login' and not self._has_valid_token():
            self.sign_in()
        return self.fetch2(path, api, method, params, headers, body, config)

    def sign_in(self, params={}):
        """
        obtain an API token with username/password(/TOTP) and cache it in options['token']
        :param dict [params]: extra login fields; params['otp'] overrides the generated TOTP
        """
        path, request, headers = self._login_request(params)
        response = self.request(path, 'public', 'POST', request, headers, None, {'cost': 100})
        self._store_login_response(response)
        return response

    def fetch_system_options(self, params={}):
        cached = self._cached_system_options()
        if cached is not None and not params:
            return cached
        return self._store_system_options(self.publicGetV2Options(params))

    def fetch_currencies(self, params={}) -> Currencies:
        """
        fetches all available currencies
        :see: https://apidocs.nobitex.ir/options/get-system-options
        """
        return self.parse_currencies_response(self.fetch_system_options(params))

    def fetch_markets(self, params={}) -> List[Market]:
        """
        retrieves data on all markets for nobitex
        :see: https://apidocs.nobitex.ir/market_data/آمار-بازار
        :see: https://apidocs.nobitex.ir/options/get-system-options
        """
        stats = self.publicGetMarketStats(params)
        return self.parse_markets_response(stats, self.fetch_system_options())

    def fetch_ticker(self, symbol: str, params={}) -> Ticker:
        """
        :see: https://apidocs.nobitex.ir/market_data/آمار-بازار
        """
        self.load_markets()
        market = self.market(symbol)
        request = {
            'srcCurrency': market['baseId'],
            'dstCurrency': market['quoteId'],
        }
        response = self.publicGetMarketStats(self.extend(request, params))
        stats = self.safe_dict(response, 'stats', {})
        ticker = self.safe_dict(stats, market['baseId'] + '-' + market['quoteId'])
        if ticker is None:
            raise BadSymbol(self.id + ' fetchTicker() returned no data for ' + symbol)
        return self.parse_ticker(ticker, market)

    def fetch_tickers(self, symbols: Strings = None, params={}) -> Tickers:
        """
        :see: https://apidocs.nobitex.ir/market_data/آمار-بازار
        """
        self.load_markets()
        symbols = self.market_symbols(symbols)
        response = self.publicGetMarketStats(params)
        return self.parse_tickers_response(response, symbols)

    def fetch_order_book(self, symbol: str, limit: Int = None, params={}) -> OrderBook:
        """
        :see: https://apidocs.nobitex.ir/market_data/دریافت-دفتر-سفارشات-نسخه-۳
        """
        self.load_markets()
        market = self.market(symbol)
        response = self.publicGetV3OrderbookSymbol(self.extend({'symbol': market['id']}, params))
        orderbook = self.parse_order_book(response, market['symbol'], self.safe_integer(response, 'lastUpdate'))
        if limit is not None:
            orderbook['bids'] = orderbook['bids'][:limit]
            orderbook['asks'] = orderbook['asks'][:limit]
        return orderbook

    def fetch_trades(self, symbol: str, since: Int = None, limit: Int = None, params={}) -> List[Trade]:
        """
        most recent public trades (Nobitex returns at most the last 20)
        :see: https://apidocs.nobitex.ir/market_data/دریافت-معاملات-اخیر
        """
        self.load_markets()
        market = self.market(symbol)
        response = self.publicGetV2TradesSymbol(self.extend({'symbol': market['id']}, params))
        return self.parse_trades(self.safe_list(response, 'trades', []), market, since, limit)

    def fetch_ohlcv(self, symbol: str, timeframe='1h', since: Int = None, limit: Int = None, params={}) -> List[list]:
        """
        :see: https://apidocs.nobitex.ir/market_data/دریافت-داده-های-ohlc
        :param int [limit]: max 500 per request
        :param int [params.until]: end of the range in ms
        """
        self.load_markets()
        market = self.market(symbol)
        request = self._ohlcv_request(market, timeframe, since, limit, params)
        response = self.publicGetMarketUdfHistory(request)
        return self.parse_ohlcvs_response(response, market, since, limit)

    def fetch_balance(self, params={}) -> Balances:
        """
        :see: https://apidocs.nobitex.ir/user_data/لیست-کیف-پول-های-کاربر
        :param str [params.type]: 'spot' (default) or 'margin'
        """
        self.load_markets()
        response = self.privatePostUsersWalletsList(self.extend({'type': 'spot'}, params))
        return self.parse_balance(response)

    def create_order(self, symbol: str, type: OrderType, side: OrderSide, amount: float, price: Num = None, params={}) -> Order:
        """
        :see: https://apidocs.nobitex.ir/spot_trade/ثبت-سفارش-جدید-اسپات
        :param float amount: in base currency
        :param float [price]: required for limit orders; optional slippage bound for market orders
        :param float [params.triggerPrice]: makes it a stop_limit/stop_market order
        :param str [params.mode]: 'oco' (requires price, triggerPrice and params.stopLimitPrice)
        :param str [params.clientOrderId]: up to 32 chars [A-Za-z0-9-]
        """
        self.load_markets()
        market = self.market(symbol)
        request = self._create_order_request(market, type, side, amount, price, params)
        response = self.privatePostMarketOrdersAdd(request)
        return self._parse_order_response(response, market)

    def cancel_order(self, id: str, symbol: Str = None, params={}):
        """
        :see: https://apidocs.nobitex.ir/spot_trade/لغو-سفارش
        """
        self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        request = self.extend(self._order_id_request('order', id, params), {'status': 'canceled'})
        response = self.privatePostMarketOrdersUpdateStatus(request)
        return self._parse_order_response(response, market)

    def cancel_all_orders(self, symbol: Str = None, params={}):
        """
        cancels all active orders (inactive non-OCO stop orders are not affected)
        :see: https://apidocs.nobitex.ir/spot_trade/لغو-جمعی-سفارشات-قدیمی
        :param float [params.hours]: only cancel orders older than this many hours
        """
        self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = self.privatePostMarketOrdersCancelOld(self._cancel_all_orders_request(market, params))
        return [self.safe_order({'info': response})]

    def fetch_order(self, id: str, symbol: Str = None, params={}) -> Order:
        """
        :see: https://apidocs.nobitex.ir/spot_trade/مشاهده-وضعیت-سفارش
        """
        self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = self.privatePostMarketOrdersStatus(self._order_id_request('id', id, params))
        return self._parse_order_response(response, market)

    def fetch_orders_by_status(self, status: str, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = self.privateGetMarketOrdersList(self._orders_list_request(status, market, limit, params))
        return self.parse_orders(self.safe_list(response, 'orders', []), market, since, limit)

    def fetch_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        """
        :see: https://apidocs.nobitex.ir/spot_trade/فهرست-سفارش-های-کاربر
        """
        return self.fetch_orders_by_status('all', symbol, since, limit, params)

    def fetch_open_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        """
        :see: https://apidocs.nobitex.ir/spot_trade/فهرست-سفارش-های-کاربر
        """
        return self.fetch_orders_by_status('open', symbol, since, limit, params)

    def fetch_closed_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        """
        orders that are Done or Canceled
        :see: https://apidocs.nobitex.ir/spot_trade/فهرست-سفارش-های-کاربر
        """
        return self.fetch_orders_by_status('close', symbol, since, limit, params)

    def fetch_my_trades(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Trade]:
        """
        trades of the last 180 days
        :see: https://apidocs.nobitex.ir/spot_trade/فهرست-معاملات-کاربر
        """
        self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = self.privateGetMarketTradesList(self._my_trades_request(market, limit, params))
        return self.parse_trades(self.safe_list(response, 'trades', []), market, since, limit)
