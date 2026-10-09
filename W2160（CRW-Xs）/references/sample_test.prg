/ Watchdata W2160 / CRW-X Sample PRG Script
/ Format: APDU [R expected_data] SW expected_sw

/ 1. 切换至非接触射频卡槽 (NFC / CPU)
NAD=15

/ 2. 射频卡复位寻卡
0012000000 SW 9000

/ 3. 选择主文件 (Select MF 3F00)
00A40000023F00 SW FFFF

/ 4. 尝试选择 YubiKey Management Applet
00A4040008A000000527471117 SW FFFF

/ 5. 尝试选择 FIDO2 Applet
00A4040008A0000006472F0001 SW FFFF

/ 6. 蜂鸣器控制 (短鸣一声)
NAD=00
B0F2010000 SW 9000

/ 7. 射频场关场 (释放射频天线供电)
NAD=15
B0150E000100 SW 9000
