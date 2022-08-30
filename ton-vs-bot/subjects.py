subjects_dict = {
    'airdrop': None,
    'bridges': {
        'ETH': {
            'TON -> ETH': None,
            'ETH -> TON': None,
        },
        'BSC': {
            'TON -> BSC': None,
            'BSC -> TON': None,
        }
    },
    'exchanges': {
        'EXMO': None,
        'FTX': None,
        'OKX': None,
    },
    'TON DNS': None,
    'validation': {
        'mytonctrl': None,
        'nominators': None
    },
    'wallets': {
        'standard wallets': {
            'android': None,
            'ios': None,
            'windows': None,
            'macos': None,
            'linux': None,
        },
        'web wallet': {
            'wallet.ton.org': None,
            'chrome extension': None
        },
        'Tonkeeper': {
            'android': None,
            'ios': None
        },
    },
}


################################################################
# check

def check_subjects_dict(gaga, l=None):
    if l is None:
        l = []
    if isinstance(gaga, dict):
        for key in gaga:
            if len(key) > 32:
                raise Exception(f'Check fail. Key length > 32: "{key}"')
            check_subjects_dict(gaga[key], l + [key])
    elif gaga is None:
        # print('/'.join(l))
        pass
    else:
        raise Exception(f'Check fail. "{"/".join(l)}" {gaga.__class__}')


check_subjects_dict(subjects_dict)

if __name__ == '__main__':
    gag = 'wallets/standard wallets'

    gag = get_subjects_list(gag)
    print(gag)
