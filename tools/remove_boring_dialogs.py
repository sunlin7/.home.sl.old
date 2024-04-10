'''
Tools for removing the boring dialog.
globals().update("MANUAL_START_THREAD=True") will suppress auto start the thread.
'''
import cv2
import numpy as np
import re
import sys
import time
import ctypes
import logging
import threading
import win32api
import win32con
import win32gui
import copy
from ctypes import windll, wintypes
from PIL import ImageGrab as igrab
from tesserocr import PyTessBaseAPI


def get_rectangles(img, mode=cv2.RETR_EXTERNAL):
    imgCv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    imgBlur = cv2.GaussianBlur(imgCv, (3, 3), 0)
    imgGray = cv2.cvtColor(imgBlur, cv2.COLOR_BGR2GRAY)
    imgBin = cv2.Canny(imgGray, 30, 100, apertureSize=3)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (6,3))
    dilate = cv2.dilate(imgBin, kernel, iterations=4)
    contours, _hierarchy = cv2.findContours(dilate, mode, cv2.CHAIN_APPROX_SIMPLE)
    return [cv2.boundingRect(x) for x in contours]  # ordered in buttom to up

def mouse_click(pos, evt=win32con.MOUSEEVENTF_LEFTDOWN):
    cInfo = win32gui.GetCursorInfo()  # save the Cursor pos
    win32api.SetCursor(None)          # hide the Cursor
    win32api.SetCursorPos(pos)
    win32api.mouse_event(evt, 0, 0, 0, 0)
    win32api.mouse_event(evt<<1, 0, 0, 0, 0)
    win32api.SetCursorPos(cInfo[2])  # restore the Cursor
    win32api.SetCursor(cInfo[1])


def apply_1st_auto_fill(pos):
    cInfo = win32gui.GetCursorInfo()  # save the Cursor pos
    win32api.SetCursor(None)          # hide the Cursor
    win32api.SetCursorPos(pos)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.5)
    win32api.keybd_event(win32con.VK_DOWN, 0, 0, 0)
    win32api.keybd_event(win32con.VK_DOWN, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.1)
    win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
    win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.1)
    win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
    win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.SetCursorPos(cInfo[2])  # restore the Cursor
    win32api.SetCursor(cInfo[1])


class ITimerExec(object):
    '''Interface for executable object'''
    def run():
        '''Run the action. Return True for done, False for need another try'''
        return True


class TimerExecSecurityDlg(ITimerExec):
    hwnd = None
    def __init__(self, hwnd):
        self.hwnd = hwnd

    def run(self):
        if (win32gui.GetForegroundWindow() != self.hwnd  # foreground switched
            or not win32gui.IsWindowVisible(self.hwnd)):  # invisible
            logging.debug(f"SecrityDlg:foreground changed or invisible window {self.hwnd}")
            return True

        tess = PyTessBaseAPI()
        titleH = win32api.GetSystemMetrics(win32con.SM_CYCAPTION)
        wRect = win32gui.GetWindowRect(self.hwnd)
        pad = titleH//4         # remove window pad, 1/4 of caption height
        img = igrab.grab(tuple(np.add(wRect, [pad, pad, -pad, -pad])))

        # tesserocr has problem on "OK" with background color
        # re-split "OK" button into exactly rectangle and search text
        okBtnVector = (img.width//8, img.height - 3*titleH, img.width//2, img.height - titleH)
        imgBtnOK = img.crop(okBtnVector)
        rectList = get_rectangles(imgBtnOK)
        tess.SetImage(imgBtnOK)
        for x in rectList:
            tess.SetRectangle(*x)
            txt = tess.GetUTF8Text()
            if txt == "OK\n":
                pos = np.add(okBtnVector[:2], x[:2])  # btn pos to window pos
                logging.debug(f"Click the OK button: {pos} : {okBtnVector}")
                mouse_click(win32gui.ClientToScreen(self.hwnd, tuple(pos)))
                return True  # discontinue

        tess.SetImage(img)
        rectList = get_rectangles(img)
        for x in rectList:
            tess.SetRectangle(*x)
            txt = tess.GetUTF8Text()
            # try search the "Face" option first
            if txt == "Face\n":
                r0, r1 = x[1] - x[3], x[1] + x[3]  # range in [-h, +h]
                res = [x for x in rectList if r0 < x[1] < r1]
                logging.debug(f"'Face' column has rectangles count={len(res)}")
                if len(res) < 3:  # not click on "Face"
                    mouse_click(win32gui.ClientToScreen(self.hwnd, x[:2]))

                return False     # to the next round

            # try click the "More choices"
            if txt == "More choices\n":
                logging.debug("Click the 'More choices' and retry immediately")
                mouse_click(win32gui.ClientToScreen(self.hwnd, x[:2]))
                time.sleep(0.2)
                return self.run()  # retry after expanded choices

        return False            # will check the window on next cycle


class TimerExecGlobalProDlg(ITimerExec):
    hwnd = None
    lastTime = None
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.lastTime = time.time()

    def sWinEnumHandler(self, hwnd, res):
        if win32gui.GetWindowText(hwnd) == "Connected":
            res.append(hwnd)
            return False        # discontinue the loop

    def run(self):
        if not win32gui.IsWindowVisible(self.hwnd):
            return True

        fhwnd = win32gui.GetForegroundWindow()
        if fhwnd and (fhwnd == self.hwnd  # still foreground
                      or '#32770' == win32gui.GetClassName(fhwnd)):  # list popup
            return False

        ntime = time.time()
        if ntime - self.lastTime <= 3.0:
            return False         # will let the UI show 3+ seconds

        self.lastTime = ntime

        res = []
        win32gui.EnumChildWindows(self.hwnd, self.sWinEnumHandler, res)
        if len(res) > 0:
            win32gui.ShowWindow(self.hwnd, win32con.SW_HIDE)
            return True

        return False


class TimerExecLoginPage(ITimerExec):
    ''' Login Page automation. It rely on the follow packages:
    tesserocr: https://github.com/simonflueckiger/tesserocr-windows_build/,
      install by pipenv install <RELEASE_URL/package.whl>
    tesserocr-data: https://github.com/tesseract-ocr/tessdata/blob/main/eng.traineddata
      download and put on the work directoy.
    '''
    def __init__(self, hwnd, searchTitle):
        self.hwnd = hwnd
        self.searchTitle = searchTitle

    def run(self, fn = lambda txt, rect: None):
        if (win32gui.GetForegroundWindow() != self.hwnd  # foreground switched
            or not win32gui.IsWindowVisible(self.hwnd)):  # invisible
            logging.debug("discontinue for foreground or invisible changed")
            return True

        title = win32gui.GetWindowText(self.hwnd)
        if not re.search(self.searchTitle, title):
            logging.debug(f"Title changed: {self.searchTitle} -> {title}, try other routines")
            res = evtCB(win32con.EVENT_SYSTEM_FOREGROUND, self.hwnd, title)
            return False if res else True  # res is True for continue with new procedual

        titleH = win32api.GetSystemMetrics(win32con.SM_CYCAPTION)
        wRect = win32gui.GetWindowRect(self.hwnd)
        img = igrab.grab(wRect)
        rectList = get_rectangles(img, cv2.RETR_CCOMP)
        rectList.sort(key=lambda x: x[1]+x[3])  # sort by right-bottom
        preY = 0
        tess = PyTessBaseAPI()
        tess.SetImage(img)
        for x in rectList:
            Y = x[1]+x[3]
            if (Y < titleH*4    # skip browser tab head and address line
                or Y <= preY):  # skip same line
                continue

            preY = Y
            tess.SetRectangle(*x)
            txt = tess.GetUTF8Text()
            res = fn(txt, x)
            if not res is None:
                return res

            if txt in ["Username\n", "Password\n"]:
                pos0 = (x[0], x[1]+int(x[3]*2))
                pos = win32gui.ClientToScreen(self.hwnd, pos0)
                logging.debug(f'try input on: {pos}')
                apply_1st_auto_fill(pos)
                return False
            elif any([txt == "Unable to sign in\n",
                      re.match("We found some errors", txt)]):
                logging.debug(f"incorrect login credits, stopping auto script: {txt}")
                return True

        logging.debug(f"Nothing to do, will try next round.")
        return False


class TimerExecGLogin(TimerExecLoginPage):
    '''Gmail Page'''
    def run(self):
        '''routin'''
        def handler(txt, rect):
            if re.search('@zoom.us\n', txt):  # logouted, click to login again
                mouse_click(pos = win32gui.ClientToScreen(self.hwnd, rect[:2]))
                return False    # next round
            elif re.search('Email or phone\n', txt):
                pos = (rect[0], rect[1]+rect[3])
                apply_1st_auto_fill(win32gui.ClientToScreen(self.hwnd, pos))
                return False    # next round
            elif any([txt == 'Verification timed out. Please try again\n',
                     re.search('Refresh or return', txt)]):
                logging.debug(f'try refresh page for: {txt}')
                win32api.keybd_event(win32con.VK_F5, 0, 0, 0)
                win32api.keybd_event(win32con.VK_F5, 0, win32con.KEYEVENTF_KEYUP, 0)
                return False
            else:
                return None

        return super().run(handler)


def listen_foreground(cb=lambda *args:None):
    WinEventProcType = ctypes.WINFUNCTYPE(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        wintypes.LONG,
        wintypes.LONG,
        wintypes.DWORD,
        wintypes.DWORD
    )

    WinEventProc = WinEventProcType(
        lambda hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime:\
        cb(event, hwnd, win32gui.GetWindowText(hwnd)))

    hook = windll.user32.SetWinEventHook(
        win32con.EVENT_SYSTEM_FOREGROUND,
        win32con.EVENT_SYSTEM_FOREGROUND,
        0, WinEventProc, 0, 0,
        win32con.WINEVENT_OUTOFCONTEXT | win32con.WINEVENT_SKIPOWNPROCESS
    )
    if hook == 0:
        logging.error('SetWinEventHook failed', file=sys.stderr)
        exit(1)

    msg = wintypes.MSG()
    while windll.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
        windll.user32.TranslateMessageW(msg)
        windll.user32.DispatchMessageW(msg)

    # Stopped receiving events, so clear up the winevent hook and uninitialise.
    logging.error('Stopped receiving new window change events. Exiting...')
    windll.user32.UnhookWinEvent(hook)


class RepeatTimer(threading.Timer):
    def run(self):
        while not self.finished.wait(self.interval):
            self.function(*self.args, **self.kwargs)

_timer_thread = None
_listen_thread = None

def stop():
    '''Stop the plugin'''
    if _timer_thread:
        _timer_thread.cancel()
    if _listen_thread:
        win32api.PostThreadMessage(_listen_thread.ident, win32con.WM_QUIT, 0, 0)

if not globals().get('MANUAL_START_THREAD'):
    '''The main function when running as a plugin'''
    windll.user32.SetProcessDpiAwarenessContext(wintypes.HANDLE(-2))  # Toggle ON

    eObjs = dict()
    def evtCB(e,hwnd,title):
        # overwrite the eObjs if the title changed
        eobj = None
        if title == "Windows Security":
            eobj = TimerExecSecurityDlg(hwnd)
            eobj.run()
        elif title == "GlobalProtect" and '#32770' == win32gui.GetClassName(hwnd):
            eobj = TimerExecGlobalProDlg(hwnd)
        elif re.search("Communications - Sign In", title):
            eobj = TimerExecLoginPage(hwnd, "Communications - Sign In")
        elif re.match("Sign in - Google Accounts", title):
            eobj = TimerExecGLogin(hwnd, "^Sign in - Google Accounts")
        elif title == "Gmail":
            eobj = TimerExecGLogin(hwnd, "^Gmail$")

        if eobj:
            eObjs[hwnd] = eobj
            return True         # True for intresting on the window

    _listen_thread = threading.Thread(target=listen_foreground, args=(evtCB,), daemon=True)
    _listen_thread.start()

    def timerCB(eObjs):
        rkeys = []
        objs = copy.copy(eObjs)
        for key,obj in objs.items():
            if obj.run():
                rkeys.append(key)

        for key in rkeys:
            del eObjs[key]

    _timer_thread = RepeatTimer(1, timerCB, (eObjs,))
    _timer_thread.start()

    win32api.SetConsoleCtrlHandler(
        # always return False to continue signal chain
        lambda ct: [False, ct == win32con.CTRL_C_EVENT and stop()][0],
        True)

if __name__ == '__main__':
    logging.basicConfig(format='%(asctime)s %(filename)s:%(lineno)d %(message)s', level=logging.DEBUG)
    win32api.SetConsoleCtrlHandler(
        # return True to avoid backtrace, discontinue the signal hander chain
        lambda ct: [True, ct == win32con.CTRL_C_EVENT and stop()][0], True)
    _listen_thread.join()
