import sys, pathlib, threading, unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from bridge import Bridge

class FastReplyTests(unittest.TestCase):
 def test_multiline_waits_for_terminal_even_with_zero_quiet(self):
  b=Bridge(auto=False); b.connected=True
  def write(cmd):
   def reply():
    for i in range(6):
     b._push('SLOT slot=%d id=%d online=1 pos=100'%(i,i+1))
    b._push('OK STATUS_ALL profile=SCS range=1023 armed=0 online=6')
   threading.Timer(.01,reply).start()
   return True
  b._write=write
  result=b.send('STATUS_ALL',timeout_ms=500,quiet_ms=0)
  self.assertEqual(len(result['lines']),7)
  self.assertTrue(result['lines'][-1].startswith('OK STATUS_ALL '))
 def test_single_line_returns_without_quiet_delay(self):
  b=Bridge(auto=False); b.connected=True
  b._write=lambda cmd:(b._push('OK POSALL 1 2 3 4 5 6') or True)
  result=b.send('POSALL',timeout_ms=300,quiet_ms=200)
  self.assertEqual(result['lines'],['OK POSALL 1 2 3 4 5 6'])
 def test_scan_waits_for_final_count_and_returns_without_quiet_delay(self):
  b=Bridge(auto=False); b.connected=True
  def write(cmd):
   b._push('SCAN_BEGIN profile=SCS max=20')
   threading.Timer(.015,lambda:b._push('SCAN id=1 pos=100')).start()
   threading.Timer(.035,lambda:b._push('SCAN_END count=1')).start()
   return True
  b._write=write
  import time
  before=time.monotonic()
  result=b.send('SCAN',timeout_ms=800,quiet_ms=500)
  elapsed=time.monotonic()-before
  self.assertEqual(result['lines'],['SCAN_BEGIN profile=SCS max=20','SCAN id=1 pos=100','SCAN_END count=1'])
  self.assertLess(elapsed,.3)
 def test_arm_check_waits_for_all_rows_despite_zero_quiet(self):
  b=Bridge(auto=False); b.connected=True
  def write(cmd):
   b._push('ARM_CHECK_SLOT slot=0 id=1 ok=1')
   def finish():
    for slot in range(1,6): b._push('ARM_CHECK_SLOT slot=%d id=%d ok=1'%(slot,slot+1))
    b._push('OK ARM CHECK armed=0 profile=SCS range=1023 read_only=1')
   threading.Timer(.02,finish).start()
   return True
  b._write=write
  result=b.send('ARM CHECK',timeout_ms=500,quiet_ms=0)
  self.assertEqual(len(result['lines']),7)
  self.assertTrue(result['lines'][-1].startswith('OK ARM CHECK '))
 def test_scan_error_is_terminal_without_quiet_delay(self):
  b=Bridge(auto=False); b.connected=True
  b._write=lambda cmd:(b._push('ERR SCAN bus_unavailable') or True)
  result=b.send('SCAN',timeout_ms=600,quiet_ms=500)
  self.assertEqual(result['lines'],['ERR SCAN bus_unavailable'])
 def test_reader_drains_available_bytes_and_preserves_split_lines(self):
  b=Bridge(auto=False); b.connected=True
  requests=[]
  class Serial:
   data=bytearray(b'OK POSALL 1 2 3 4 5 6\r\nOK INFO armed=0\r\n')
   @property
   def in_waiting(self):return min(9,len(self.data))
   def read(self,n):
    requests.append(n)
    if not self.data:b._stop=True;return b''
    out=bytes(self.data[:n]);del self.data[:n];return out
  b.ser=Serial();b._read_loop()
  self.assertLess(max(requests),4096)
  self.assertEqual([x['line'] for x in b.lines_since(0)[0]],['OK POSALL 1 2 3 4 5 6','OK INFO armed=0'])

if __name__=='__main__':unittest.main()