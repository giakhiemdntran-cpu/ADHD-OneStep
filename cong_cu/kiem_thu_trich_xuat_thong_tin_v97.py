from datetime import datetime
from zoneinfo import ZoneInfo
from dich_vu.trich_xuat_thong_tin import trich_xuat_thong_tin_nhiem_vu
base=datetime(2026,9,13,14,50,tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
cases=[
("nhắc mình vào lúc 14:57 mình sẽ đi uống nước",{"title":"Đi uống nước","scheduled_time":"14:57","schedule_type":"once"}),
("muốn bạn đặt lịch giúp mình vào lúc 14:56 mình sẽ đi uống nước",{"title":"Đi uống nước","scheduled_time":"14:56","schedule_type":"once"}),
("vào lúc 14:56 mình sẽ đi uống nước",{"title":"Đi uống nước","scheduled_time":"14:56","schedule_type":"once"}),
("nhắc mình 10 phút nữa đứng dậy",{"title":"Đứng dậy","scheduled_time":"15:00","schedule_type":"once"}),
("thứ hai thứ tư thứ sáu lúc 6:30 nhắc mình tập thể dục",{"scheduled_time":"06:30","schedule_type":"weekly","repeat_days":["mon","wed","fri"]}),
]
for text,exp in cases:
    got=trich_xuat_thong_tin_nhiem_vu(text,base=base)
    print(text,"=>",got)
    for k,v in exp.items(): assert got.get(k)==v,(text,k,got.get(k),v)
print("ALL SLOT TESTS PASSED")
