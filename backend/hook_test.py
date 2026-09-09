import ctypes, ctypes.wintypes, win32gui, win32process, time, psutil
import comtypes.client

UIAClient = comtypes.client.GetModule('UIAutomationCore.dll')
uia = comtypes.client.CreateObject('{ff48dba4-60ef-4201-aa87-54103eef594e}', interface=UIAClient.IUIAutomation)

log = open('C:/Users/HONG/Desktop/hook_test.txt', 'w')

# Find ShellExperienceHost PID
shell_pid = None
for p in psutil.process_iter(['pid', 'name']):
    if 'ShellExperienceHost' in p.info['name']:
        shell_pid = p.info['pid']
        log.write(f'ShellExperienceHost PID: {shell_pid}\n')
        break

if not shell_pid:
    log.write('ShellExperienceHost not found!\n')

seen = set()

def scan():
    def cb(hwnd, _):
        if hwnd in seen:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            cls = win32gui.GetClassName(hwnd)
            title = win32gui.GetWindowText(hwnd)
            seen.add(hwnd)
            if pid == shell_pid or 'Toast' in cls or 'Notif' in cls:
                log.write(f'cls={cls!r} title={title!r} pid={pid}\n')
                try:
                    el = uia.ElementFromHandle(hwnd)
                    tc = uia.CreatePropertyCondition(UIAClient.UIA_ControlTypePropertyId, UIAClient.UIA_TextControlTypeId)
                    texts = el.FindAll(UIAClient.TreeScope_Descendants, tc)
                    for i in range(min(texts.Length, 6)):
                        log.write(f'  text[{i}]: {texts.GetElement(i).CurrentName!r}\n')
                except:
                    pass
                log.flush()
        except:
            pass
    # Enum all including hidden
    ctypes.windll.user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)(cb), 0)

scan()
log.write(f'Pre-scan done: {len(seen)} windows\n'); log.flush()
print('Waiting 15s - snip NOW!', flush=True)

start = time.time()
while time.time() - start < 15:
    scan()
    time.sleep(0.2)

log.write('Done.\n'); log.close()
print('Done.', flush=True)
