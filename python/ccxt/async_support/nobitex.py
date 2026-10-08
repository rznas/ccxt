# -*- coding: utf-8 -*-

"""Nobitex - async variant (used by Freqtrade). Shared logic lives in ccxt.nobitex.NobitexCommon."""

import asyncio

from ccxt.async_support.base.exchange import Exchange
from ccxt.abstract.nobitex import ImplicitAPI
from ccxt.nobitex import NobitexCommon
from ccxt.base.types import Any, Balances, Currencies, Int, Market, Num, Order, OrderBook, OrderSide, OrderType, Str, Strings, Ticker, Tickers, Trade
from typing import List
from ccxt.base.errors import BadSymbol


class nobitex(NobitexCommon, Exchange, ImplicitAPI):

    _sign_in_lock = None

    async def request(self, path, api: Any = 'public', method='GET', params={}, headers: Any = None, body: Any = None, config={}):
        if api == 'private' and self._auth_method() == 'login' and not self._has_valid_token():
            await self.sign_in()
        return await self.fetch2(path, api, method, params, headers, body, config)

    async def sign_in(self, params={}):
        """
        obtain an API token with username/password(/TOTP) and cache it in options['token']
        :param dict [params]: extra login fields; params['otp'] overrides the generated TOTP
        """
        if self._sign_in_lock is None:
            self._sign_in_lock = asyncio.Lock()
        async with self._sign_in_lock:
            if self._has_valid_token() and not params:
                return None  # another coroutine already signed in
            path, request, headers = self._login_request(params)
            response = await self.request(path, 'public', 'POST', request, headers, None, {'cost': 100})
            self._store_login_response(response)
            return response

    async def fetch_system_options(self, params={}):
        cached = self._cached_system_options()
        if cached is not None and not params:
            return cached
        return self._store_system_options(await self.publicGetV2Options(params))

    async def fetch_currencies(self, params={}) -> Currencies:
        return self.parse_currencies_response(await self.fetch_system_options(params))

    async def fetch_markets(self, params={}) -> List[Market]:
        stats = await self.publicGetMarketStats(params)
        return self.parse_markets_response(stats, await self.fetch_system_options())

    async def fetch_ticker(self, symbol: str, params={}) -> Ticker:
        await self.load_markets()
        market = self.market(symbol)
        request = {
            'srcCurrency': market['baseId'],
            'dstCurrency': market['quoteId'],
        }
        response = await self.publicGetMarketStats(self.extend(request, params))
        stats = self.safe_dict(response, 'stats', {})
        ticker = self.safe_dict(stats, market['baseId'] + '-' + market['quoteId'])
        if ticker is None:
            raise BadSymbol(self.id + ' fetchTicker() returned no data for ' + symbol)
        return self.parse_ticker(ticker, market)

    async def fetch_tickers(self, symbols: Strings = None, params={}) -> Tickers:
        await self.load_markets()
        symbols = self.market_symbols(symbols)
        response = await self.publicGetMarketStats(params)
        return self.parse_tickers_response(response, symbols)

    async def fetch_order_book(self, symbol: str, limit: Int = None, params={}) -> OrderBook:
        await self.load_markets()
        market = self.market(symbol)
        response = await self.publicGetV3OrderbookSymbol(self.extend({'symbol': market['id']}, params))
        orderbook = self.parse_order_book(response, market['symbol'], self.safe_integer(response, 'lastUpdate'))
        if limit is not None:
            orderbook['bids'] = orderbook['bids'][:limit]
            orderbook['asks'] = orderbook['asks'][:limit]
        return orderbook

    async def fetch_trades(self, symbol: str, since: Int = None, limit: Int = None, params={}) -> List[Trade]:
        await self.load_markets()
        market = self.market(symbol)
        response = await self.publicGetV2TradesSymbol(self.extend({'symbol': market['id']}, params))
        return self.parse_trades(self.safe_list(response, 'trades', []), market, since, limit)

    async def fetch_ohlcv(self, symbol: str, timeframe='1h', since: Int = None, limit: Int = None, params={}) -> List[list]:
        await self.load_markets()
        market = self.market(symbol)
        request = self._ohlcv_request(market, timeframe, since, limit, params)
        response = await self.publicGetMarketUdfHistory(request)
        return self.parse_ohlcvs_response(response, market, since, limit)

    async def fetch_balance(self, params={}) -> Balances:
        await self.load_markets()
        response = await self.privatePostUsersWalletsList(self.extend({'type': 'spot'}, params))
        return self.parse_balance(response)

    async def create_order(self, symbol: str, type: OrderType, side: OrderSide, amount: float, price: Num = None, params={}) -> Order:
        await self.load_markets()
        market = self.market(symbol)
        request = self._create_order_request(market, type, side, amount, price, params)
        response = await self.privatePostMarketOrdersAdd(request)
        return self._parse_order_response(response, market)

    async def cancel_order(self, id: str, symbol: Str = None, params={}):
        await self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        request = self.extend(self._order_id_request('order', id, params), {'status': 'canceled'})
        response = await self.privatePostMarketOrdersUpdateStatus(request)
        return self._parse_order_response(response, market)

    async def cancel_all_orders(self, symbol: Str = None, params={}):
        await self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = await self.privatePostMarketOrdersCancelOld(self._cancel_all_orders_request(market, params))
        return [self.safe_order({'info': response})]

    async def fetch_order(self, id: str, symbol: Str = None, params={}) -> Order:
        await self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = await self.privatePostMarketOrdersStatus(self._order_id_request('id', id, params))
        return self._parse_order_response(response, market)

    async def fetch_orders_by_status(self, status: str, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        await self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = await self.privateGetMarketOrdersList(self._orders_list_request(status, market, limit, params))
        return self.parse_orders(self.safe_list(response, 'orders', []), market, since, limit)

    async def fetch_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        return await self.fetch_orders_by_status('all', symbol, since, limit, params)

    async def fetch_open_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        return await self.fetch_orders_by_status('open', symbol, since, limit, params)

    async def fetch_closed_orders(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Order]:
        return await self.fetch_orders_by_status('close', symbol, since, limit, params)

    async def fetch_my_trades(self, symbol: Str = None, since: Int = None, limit: Int = None, params={}) -> List[Trade]:
        await self.load_markets()
        market = self.market(symbol) if symbol is not None else None
        response = await self.privateGetMarketTradesList(self._my_trades_request(market, limit, params))
        return self.parse_trades(self.safe_list(response, 'trades', []), market, since, limit)
