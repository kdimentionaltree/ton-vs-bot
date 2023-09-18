heroku = True

if heroku:
    channel_chat_id = -1001794964683
    channel_link = 'https://t.me/c/1794964683'
    group_chat_id = -1001798942353
    log_chat_id = -1001428065293

    subjects_channels = {
        '': -1001728100350,
        'bridges': -1001662417884,
        'validation/mytonctrl': -1001725731982,
        'wallets/web wallet': -1001763943139,
        'sites/ton.org': -1001812605218,
    }

else:
    channel_chat_id = -1001763631201
    channel_link = 'https://t.me/c/1763631201'
    group_chat_id = -1001712905492
    log_chat_id = -1001387082835

    subjects_channels = {
        '': -1001614180555,
        'wallets': -1001659482788,
        'wallets/web wallet': -1001605159188,
        'wallets/web wallet/wallet.ton.org': -1001790705152,
        'bridges': -1001519524113,
        'validation/mytonctrl': -1001751686660
    }

DG_user_id = -1
tg_delays = True

tg_wallet_bots_dict = {
    1622808649: '@CryptoTestnetBot',
    1559501630: '@CryptoBot',
    1985737506: '@wallet'
}
