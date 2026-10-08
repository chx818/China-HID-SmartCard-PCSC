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
