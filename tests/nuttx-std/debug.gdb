# Read stopped task state only after the execution oracle has failed.
set pagination off
set confirm off
set print elements 32
set language c
info registers
bt 16
python
import gdb
registers = ['pc', 'ra', 'sp', 's0']
original = {r: int(gdb.parse_and_eval('$' + r)) for r in registers}
try:
    count = min(int(gdb.parse_and_eval('g_npidhash')), 256)
    for i in range(count):
        t = gdb.parse_and_eval('g_pidhash[%d]' % i)
        if int(t) == 0:
            continue
        print('\n=== NuttX task slot %d ===' % i)
        gdb.execute('p *g_pidhash[%d]' % i)
        try:
            tcb = t.dereference()
            saved = tcb['xcp']['regs']
            if int(saved) == 0:
                continue
            # RISC-V NuttX saves EPC/RA/SP/S0 at indices 0/1/2/8.
            # This is a failed, disposable kernel. Restore CPU registers below.
            for name, index in [('pc', 0), ('ra', 1), ('sp', 2), ('s0', 8)]:
                gdb.execute('set $%s = %s' % (name, int(saved[index])))
            gdb.execute('bt 20')
        except gdb.error as error:
            print('Task backtrace unavailable:', error)
finally:
    for name, value in original.items():
        gdb.execute('set $%s = %s' % (name, value))
end
