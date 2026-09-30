"""Independent oracle for real NuttX file bytes and injected syscall witnesses."""
import struct

# Counters: write attempts, EINTR, other errors/zero progress, bytes actually
# written, truncate attempts, seek attempts, fsync attempts. Baseline record 1
# precedes fault arming and is deliberately excluded from these counters.
CASES = (
    ('short_eintr', 88, 88, (8, 1, 0, 44, 0, 1, 0), (8, 1, 0, 44, 0, 1, 1)),
    ('header_full', 44, 88, (2, 0, 1, 5, 1, 2, 0), (4, 0, 1, 49, 1, 3, 1)),
    ('payload_io', 44, 88, (3, 0, 1, 42, 1, 2, 0), (5, 0, 1, 86, 1, 3, 1)),
    ('zero_write', 44, 88, (2, 0, 1, 5, 1, 2, 0), (4, 0, 1, 49, 1, 3, 1)),
    ('seek_end', 44, 88, (0, 0, 1, 0, 0, 1, 0), (2, 0, 1, 44, 0, 2, 1)),
    ('rollback_truncate', 86, 86, (3, 0, 2, 42, 1, 1, 0), (3, 0, 2, 42, 1, 1, 0)),
    ('rollback_seek', 44, 44, (3, 0, 2, 42, 1, 2, 0), (3, 0, 2, 42, 1, 2, 0)),
    ('flush_retry', 88, 88, (2, 0, 1, 44, 0, 1, 1), (2, 0, 1, 44, 0, 1, 2)),
)


def expected_lines():
    # No Rust/C serializer is used to construct the expected byte stream.
    records = b''.join(
        struct.pack('<8sHHB3xQQQ', b'RCAMREC1', 2, 2, 0,
                    seq, 0x1122334455660000 + seq, 4) + bytes(range(seq, seq + 4))
        for seq in (1, 2)
    )
    result = []
    for name, before_len, after_len, before_calls, after_calls in CASES:
        for phase, length, calls in (('before', before_len, before_calls),
                                     ('after', after_len, after_calls)):
            result.append(f'RC_STORAGE case={name} phase={phase} '
                          f'data={records[:length].hex()} calls={",".join(map(str, calls))}')
        result.append(f'RC_STORAGE_DONE case={name} closed=1 control=rejected OK')
    return result


def validate_storage(text):
    actual = [line for line in text.replace('\r', '').splitlines()
              if line.startswith('RC_STORAGE')]
    expected = expected_lines()
    assert len(actual) == len(expected), f'incomplete/duplicate storage evidence: {len(actual)} lines'
    for got, want in zip(actual, expected):
        assert got == want, f'storage evidence mismatch:\nactual: {got}\nexpected: {want}'


def self_test():
    lines = expected_lines()
    valid = '\n'.join(lines)
    validate_storage(valid)
    # Require every stage of every case, actual byte identity, syscall counts,
    # descriptor cleanup, and rejection of real on-target file corruption.
    for index, line in enumerate(lines):
        corrupt = line.replace('data=5243', 'data=0043') if 'data=' in line else line.replace('closed=1', 'closed=0')
        for bad in ('\n'.join(lines[:index] + lines[index + 1:]),
                    valid + '\n' + line, valid.replace(line, corrupt)):
            try:
                validate_storage(bad)
            except AssertionError:
                continue
            raise AssertionError('storage oracle accepted missing/duplicate/corrupt evidence')
    for bad in (valid.replace('control=rejected', 'control=accepted'),
                valid.replace('calls=3,0,2,42,1,1,0', 'calls=4,0,2,42,1,1,0'),
                valid.replace('calls=4,0,1,49,1,3,1', 'calls=6,0,1,93,1,4,1')):
        try:
            validate_storage(bad)
        except AssertionError:
            continue
        raise AssertionError('storage oracle accepted writes after poison or a broken negative control')
    print('PASS: storage oracle rejects incomplete, corrupt, duplicate and invalid retry evidence')


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('This assertion-based oracle must not run with Python -O')
    self_test()
