import asyncio
import os
import tempfile
import threading

from cau_hinh import EDGE_TTS_VOICE, EDGE_TTS_RATE
from dich_vu.quan_ly_am_thanh import audio_lock, sau_dau_ra_giai_phong

class DichVuDocGiongNoi:
    def __init__(self):
        self.lock=threading.Lock()
        self._pygame=None

    def noi(self,text,on_done=None):
        threading.Thread(
            target=self._tien_trinh,
            args=(text,on_done),
            daemon=True
        ).start()

    def _tien_trinh(self,text,on_done):
        try:
            # Khóa riêng của dịch vụ + khóa dùng chung toàn tiến trình:
            # chỉ cho phép một tác vụ TTS và không để TTS chồng lấn với STT.
            with self.lock:
                with audio_lock:
                    try:
                        self._bien(text)
                    except Exception as e:
                        print("[EDGE TTS ERROR]",e)
                        self._pyttsx3(text)
        finally:
            # Cho ALSA một khoảng ngắn để giải phóng thiết bị đầu ra
            # trước khi Buddy mở lại microphone.
            sau_dau_ra_giai_phong()
            if on_done:
                on_done()

    def _bien(self,text):
        import edge_tts
        import pygame

        f=tempfile.NamedTemporaryFile(
            suffix=".mp3",
            delete=False
        )
        name=f.name
        f.close()

        async def sinh():
            await edge_tts.Communicate(
                text=text,
                voice=EDGE_TTS_VOICE,
                rate=EDGE_TTS_RATE
            ).save(name)

        try:
            asyncio.run(gen())

            # Chỉ khởi tạo cho lượt phát hiện tại. Trên Jetson cách này an toàn hơn việc
            # để pygame.mixer giữ ALSA xuyên suốt các chu kỳ STT/TTS.
            if pygame.mixer.get_init():
                try:
                    pygame.mixer.quit()
                except Exception:
                    pass

            pygame.mixer.init()
            self._pygame=pygame
            pygame.mixer.music.load(name)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(20)

            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass

        finally:
            try:
                if pygame.mixer.get_init():
                    pygame.mixer.quit()
            except Exception as e:
                print("[AUDIO MIXER QUIT WARN]", e)

            self._pygame=None

            try:
                os.remove(name)
            except Exception:
                pass

    def _pyttsx3(self,text):
        import pyttsx3

        e=pyttsx3.init()
        e.setProperty("rate",155)

        for v in e.getProperty("voices"):
            blob=(
                str(v.id)
                +str(v.name)
                +str(getattr(v,"languages",""))
            ).lower()

            if "vietnam" in blob or "vi-vn" in blob:
                e.setProperty("voice",v.id)
                break

        try:
            e.say(text)
            e.runAndWait()
        finally:
            try:
                e.stop()
            except Exception:
                pass
            del e
