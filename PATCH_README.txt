PCBM PATCH: ADHD_OneStep_PCBM_DirectDB_Admin_LATEST(2) -> current version
=======================================================================

Base expected:
  ADHD_OneStep_PCBM_DirectDB_Admin_LATEST(2).zip

Copy/extract this patch OVER the folder:
  ADHD_OneStep_PCBM_DirectDB_Admin_UPDATED/

Files replaced/added:
  - cau_hinh.py
  - dich_vu/dich_vu_doc_giong_noi.py
  - dich_vu/dich_vu_nhan_dang_giong_noi.py
  - dich_vu/quan_ly_am_thanh.py
  - tro_ly/ung_dung.py
  - requirements.txt
  - install_vieneu_tts.sh

Main changes accumulated from the base version:
  - default Ubuntu microphone + native sample-rate recording
  - resample microphone audio to 16 kHz before STT
  - RMS/Peak monitoring and red audio-wave indicator
  - Face <-> Chat view switch
  - keyboard chat input
  - face zoom/layout fix
  - polished chat bubbles/layout
  - Exit button
  - F1 shortcut: Face <-> Chat
  - Ctrl+Q shortcut: exit application
  - VieNeu-TTS v3 Turbo streaming integration
  - Edge TTS and pyttsx3 fallback path
  - TTS timing/debug logs

No files need to be deleted from the base version.

After patching, install/update dependencies if needed:
  pip install -r requirements.txt

For VieNeu setup, you can also run:
  chmod +x install_vieneu_tts.sh
  ./install_vieneu_tts.sh
