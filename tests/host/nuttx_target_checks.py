"""Target ABI, preemption and descriptor-lifetime evidence for the NSH oracle."""
import re
from nuttx_storage_checks import validate_storage, self_test as storage_self_test

CLOSE = 'RC_TARGET_CLOSE attempts=1 reused=1 survivor=1 control=closed OK'


def _validate_target(text, pointer_bits):
    lines = text.replace('\r', '').splitlines()
    abi = [line for line in lines if line.startswith('RC_TARGET_ABI')]
    assert abi == [f'RC_TARGET_ABI bits={pointer_bits} OK'], abi
    close = [line for line in lines if line.startswith('RC_TARGET_CLOSE')]
    assert close == [CLOSE], 'missing, duplicate or invalid descriptor-lifetime evidence'
    preemption = [line for line in lines if line.startswith('RC_TARGET_PREEMPT')]
    if pointer_bits == 32:
        assert len(preemption) == 1, 'missing or duplicated target preemption evidence'
    else:
        assert len(preemption) <= 1, preemption
    for line in preemption:
        match = re.fullmatch(r'RC_TARGET_PREEMPT wakes=4 control_wakes=0 work=([0-9]+) OK', line)
        assert match and 0 < int(match[1]) <= 500000000, line


def self_test():
    valid = ('RC_TARGET_ABI bits=32 OK\n'
             'RC_TARGET_PREEMPT wakes=4 control_wakes=0 work=123 OK\n' + CLOSE)
    valid64 = 'RC_TARGET_ABI bits=64 OK\n' + CLOSE
    _validate_target(valid, 32)
    _validate_target(valid64, 64)
    for bad in [valid.replace('bits=32', 'bits=64'), valid.splitlines()[0],
                valid.splitlines()[1], valid + '\n' + valid.splitlines()[0],
                valid + '\n' + valid.splitlines()[1], valid.replace('work=123', 'work=0'),
                valid.replace('wakes=4', 'wakes=0'), valid.replace('control_wakes=0', 'control_wakes=4')]:
        try:
            _validate_target(bad, 32)
        except AssertionError:
            continue
        raise AssertionError('target oracle accepted missing/incorrect ABI or preemption evidence')
    for text, bits in [(valid, 32), (valid64, 64)]:
        for bad in [text.replace(CLOSE, ''), text + '\n' + CLOSE,
                    text.replace('attempts=1', 'attempts=2'),
                    text.replace('reused=1', 'reused=0'),
                    text.replace('survivor=1', 'survivor=0'),
                    text.replace('control=closed', 'control=open')]:
            try:
                _validate_target(bad, bits)
            except AssertionError:
                continue
            raise AssertionError('target oracle accepted invalid descriptor-lifetime evidence')
    storage_self_test()
    print('PASS: target oracle rejects invalid ABI, preemption and close-lifetime evidence')


def validate_target(text, pointer_bits):
    _validate_target(text, pointer_bits)
    validate_storage(text)


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('This assertion-based oracle must not run with Python -O')
    self_test()
