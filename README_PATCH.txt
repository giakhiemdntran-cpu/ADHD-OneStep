ADHD OneStep v10.5 -> v10.6 PATCH

Cach ap dung:
1. Giai nen ADHD_OneStep_v10.5(2).zip.
2. Chep de thu muc tro_ly/ trong patch nay vao thu muc project v10.5.
3. Co the chep VERSION.txt vao thu muc goc project.
4. Chay lai: python khoi_dong.py

File code thay doi:
- tro_ly/ung_dung.py
  + Top bar lui vao trong va ha xuong nhe.
  + Thu nho font/nut User, Chat, Cai dat, Tro giup, Thoat.
  + Chuyen PCBM status len tren khuon mat.
  + Giu showFullScreen() de phu kin man hinh robot.
  + Doi title thanh OneStep Buddy v10.6 PCBM.
- tro_ly/cua_so_tro_giup.py
  + Compact theo kich thuoc man hinh nho.
  + Hang nut duoi khong bi khuất.
- tro_ly/cua_so_cai_dat.py
  + Compact theo man hinh nho.
  + Noi dung Settings cuon doc duoc.
  + Hang nut duoi luon thay.

Khong thay doi:
- cau_hinh.py
- PCBM models/logic
- TTS/Vision/STT
- Database va du lieu
