# Generic failed-kernel task snapshot. Do not alter execution success criteria.
set pagination off
set confirm off
set print elements 64
set language c
info registers
bt 20
python
import gdb
try:
    count = min(int(gdb.parse_and_eval('g_npidhash')), 256)
except gdb.error as error:
    print('Unable to read g_npidhash:', error)
else:
    for i in range(count):
        try:
            t = gdb.parse_and_eval('g_pidhash[%d]' % i)
            if int(t) == 0:
                continue
            print('\n=== NuttX task slot %d ===' % i)
            gdb.execute('p *g_pidhash[%d]' % i)
        except gdb.error as error:
            print('Task slot %d unavailable: %s' % (i, error))
end
detach
quit
