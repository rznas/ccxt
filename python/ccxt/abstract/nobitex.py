from ccxt.base.types import Entry


# Costs are relative to rateLimit = 200ms (300 requests/minute, the most permissive
# Nobitex limit). cost = 300 / documented-requests-per-minute.
# Source: https://apidocs.nobitex.ir (per-endpoint "محدودیت فراخوانی").
class ImplicitAPI:
    # public: market data
    public_get_v3_orderbook_symbol = publicGetV3OrderbookSymbol = Entry('v3/orderbook/{symbol}', 'public', 'GET', {'cost': 1})
    public_get_v2_depth_symbol = publicGetV2DepthSymbol = Entry('v2/depth/{symbol}', 'public', 'GET', {'cost': 1})
    public_get_v2_trades_symbol = publicGetV2TradesSymbol = Entry('v2/trades/{symbol}', 'public', 'GET', {'cost': 5})
    public_get_market_stats = publicGetMarketStats = Entry('market/stats', 'public', 'GET', {'cost': 15})
    public_get_market_udf_history = publicGetMarketUdfHistory = Entry('market/udf/history', 'public', 'GET', {'cost': 5})
    public_get_v2_options = publicGetV2Options = Entry('v2/options', 'public', 'GET', {'cost': 5})
    # public: authentication (30 requests / 10 minutes)
    public_post_v2_auth_login = publicPostV2AuthLogin = Entry('v2/auth/login', 'public', 'POST', {'cost': 100})
    public_post_auth_login = publicPostAuthLogin = Entry('auth/login/', 'public', 'POST', {'cost': 100})
    # private: account
    private_post_auth_logout = privatePostAuthLogout = Entry('auth/logout/', 'private', 'POST', {'cost': 10})
    private_get_users_profile = privateGetUsersProfile = Entry('users/profile', 'private', 'GET', {'cost': 10})
    private_get_users_limitations = privateGetUsersLimitations = Entry('users/limitations', 'private', 'GET', {'cost': 10})
    private_post_users_wallets_list = privatePostUsersWalletsList = Entry('users/wallets/list', 'private', 'POST', {'cost': 15})
    private_post_v2_wallets = privatePostV2Wallets = Entry('v2/wallets', 'private', 'POST', {'cost': 20})
    private_post_users_wallets_balance = privatePostUsersWalletsBalance = Entry('users/wallets/balance', 'private', 'POST', {'cost': 10})
    private_get_users_wallets_transactions_list = privateGetUsersWalletsTransactionsList = Entry('users/wallets/transactions/list', 'private', 'GET', {'cost': 10})
    private_get_users_transactions_history = privateGetUsersTransactionsHistory = Entry('users/transactions-history', 'private', 'GET', {'cost': 300})
    private_get_users_wallets_deposits_list = privateGetUsersWalletsDepositsList = Entry('users/wallets/deposits/list', 'private', 'GET', {'cost': 10})
    private_get_users_wallets_withdraws_list = privateGetUsersWalletsWithdrawsList = Entry('users/wallets/withdraws/list', 'private', 'GET', {'cost': 10})
    # private: spot trading (order placement shares 300 requests / 10 minutes with margin)
    private_post_market_orders_add = privatePostMarketOrdersAdd = Entry('market/orders/add', 'private', 'POST', {'cost': 10})
    private_post_market_orders_status = privatePostMarketOrdersStatus = Entry('market/orders/status', 'private', 'POST', {'cost': 1})
    private_get_market_orders_list = privateGetMarketOrdersList = Entry('market/orders/list', 'private', 'GET', {'cost': 10})
    private_post_market_orders_update_status = privatePostMarketOrdersUpdateStatus = Entry('market/orders/update-status', 'private', 'POST', {'cost': 3.3333333333333335})
    private_post_market_orders_cancel_old = privatePostMarketOrdersCancelOld = Entry('market/orders/cancel-old', 'private', 'POST', {'cost': 10})
    private_get_market_trades_list = privateGetMarketTradesList = Entry('market/trades/list', 'private', 'GET', {'cost': 10})
