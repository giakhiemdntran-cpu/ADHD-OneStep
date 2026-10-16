import threading
import time

from may_chu_web.may_chu import tao_ung_dung_web
from tro_ly.ung_dung import chay_tro_ly
from cau_hinh import HOST, PORT

def chay_web():
    app = tao_ung_dung_web()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)

if __name__ == "__main__":
    threading.Thread(target=chay_web, daemon=True).start()
    time.sleep(0.8)
    chay_tro_ly()
