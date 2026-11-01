"""Conservative ownership display: source month token -> reported calendar quarter.
No day, owner identity, exact boundary, end date, or owner count is inferred.
"""
import re


def ownership_quarter(raw):
    if raw in (None, ''):
        return None
    if not isinstance(raw, str) or not re.fullmatch(r'[0-9]{4}(0[1-9]|1[0-2])', raw) or raw[:4]=='0000':
        raise ValueError('ownership_period_format')
    return f'{raw[:4]}-Q{(int(raw[4:]) - 1) // 3 + 1}'


def derive_ownership(payload, config):
    for target, rule in config.get('derived_fields', {}).items():
        if rule.get('transform') != 'ownership_quarter' or config.get('kind') != 'ownership':
            raise ValueError('Unverified derived ownership transform')
        payload[target] = ownership_quarter(payload.get(rule['source']))
        payload[target + '_precision'] = 'quarter'
    return payload
