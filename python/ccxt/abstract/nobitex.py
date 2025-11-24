"""Nobitex Abstract API - Minimal implementation"""

from ccxt.base.types import Entry


class ImplicitAPI:
    """Nobitex implicit API methods"""
    # Public API
    public_get_market_stats = publicGetMarketStats = Entry('market/stats', 'public', 'GET', {})
    public_get_market_globalstats = publicGetMarketGlobalstats = Entry('market/global-stats', 'public', 'GET', {})
    public_get_v3_orderbook_symbol = publicGetV3OrderbookSymbol = Entry('v3/orderbook/{symbol}', 'public', 'GET', {})
    public_get_market_udf_history = publicGetMarketUdfHistory = Entry('market/udf/history', 'public', 'GET', {})

    # Private API
    private_post_auth_login = privatePostAuthLogin = Entry('auth/login', 'private', 'POST', {})
    private_post_market_orders_add = privatePostMarketOrdersAdd = Entry('market/orders/add', 'private', 'POST', {})
    private_post_market_orders_status = privatePostMarketOrdersStatus = Entry('market/orders/status', 'private', 'POST', {})
    private_post_market_orders_updatestatus = privatePostMarketOrdersUpdateStatus = Entry('market/orders/update-status', 'private', 'POST', {})
    private_get_market_orders_list = privateGetMarketOrdersList = Entry('market/orders/list', 'private', 'GET', {})
    private_get_market_trades_list = privateGetMarketTradesList = Entry('market/trades/list', 'private', 'GET', {})
    private_get_users_wallets_list = privateGetUsersWalletsList = Entry('users/wallets/list', 'private', 'GET', {})