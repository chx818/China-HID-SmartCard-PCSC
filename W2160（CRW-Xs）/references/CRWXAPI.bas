Attribute VB_Name = "CRWXAPI"
'Windows API,函数说明，请参考MSDN
Public Declare Function WritePrivateProfileSection Lib "kernel32" Alias "WritePrivateProfileSectionA" (ByVal lpAppName As String, ByVal lpString As String, ByVal lpFileName As String) As Long
Public Declare Function WritePrivateProfileString Lib "kernel32" Alias "WritePrivateProfileStringA" (ByVal lpApplicationName As String, ByVal lpKeyName As Any, ByVal lpString As Any, ByVal lpFileName As String) As Long
Public Declare Function GetPrivateProfileInt Lib "kernel32" Alias "GetPrivateProfileIntA" (ByVal lpApplicationName As String, ByVal lpKeyName As String, ByVal nDefault As Long, ByVal lpFileName As String) As Long
Public Declare Function GetPrivateProfileSection Lib "kernel32" Alias "GetPrivateProfileSectionA" (ByVal lpAppName As String, ByVal lpReturnedString As String, ByVal nSize As Long, ByVal lpFileName As String) As Long
Public Declare Function GetPrivateProfileString Lib "kernel32" Alias "GetPrivateProfileStringA" (ByVal lpApplicationName As String, ByVal lpKeyName As Any, ByVal lpDefault As String, ByVal lpReturnedString As String, ByVal nSize As Long, ByVal lpFileName As String) As Long
Public Declare Function ShowScrollBar Lib "user32" (ByVal hwnd As Long, ByVal wBar As Long, ByVal bShow As Long) As Long
Public Declare Function SendMessage Lib "user32" Alias "SendMessageA" (ByVal hwnd As Long, ByVal wMsg As Long, ByVal wParam As Long, lParam As Any) As Long
'Windows 声明的常数,说明参考MSDN
Public Const SB_HORZ = 0
Public Const WM_USER = &H400
Public Const EM_SETTARGETDEVICE = (WM_USER + 72)
    
'CRW-X API声明
'CRW-X VB 函数与WDCRWX.H函数的参数类型对应关系
'char x -> byval x as byte
'char *x -> byref x as byte
'char x(5)->byval x as string           '要求传字符串
'unsigned char  *x ->byref x as byte    '要求传二进制数组,调用时，参数为数组的第一字节
'int x-> byval x as long                'C中的int对应VB是long
'int *x ->byref x as long
'声明中的参数为aXXX时，要求输入参数为数组
'1 打开设备
Public Declare Function CT_open Lib "wdcrwx.dll" (ByVal PortName As String, ByVal Rate As Long, ByVal Parity As Byte) As Long
'Portname deivce name it is maybe COM1/COM2/COM3/COM4,USB1/USB2/USB3/USB4
'rate 波特率 9600,19200,38400,57600,115200
'Parity 校验位 'N'或'E'
'打开USB设备时,rate,Parity都置0
'返回设备句柄
'2 关闭设备
Public Declare Function CT_close Lib "wdcrwx.dll" (ByVal fd As Long) As Long
'fd 已经打开的设备句柄，以函数中的fd相同
'3 设置NAD
Public Declare Sub ICC_set_NAD Lib "wdcrwx.dll" (ByVal fd As Long, ByVal bNewNad As Byte)
'bNewNad 设置的nad
'nad =00/12/13/14/15 对应是用户卡/读卡器/SAM卡/ESAM卡/非接触卡
'4 发送命令和接收响应数据,支持大于255字节命令和响应
Public Declare Function ICC_TransmitAPDU32 Lib "wdcrwx.dll" (ByVal fd As Long, ByVal lLens As Long, ByRef aComm As Byte, ByRef lLenr As Long, ByRef aResp As Byte) As Long
'lLens 命令长度
'bComm 命令
'lLenr 返回响应长度
'bResp 返回响应
'返回sw
'5发送命令和接收响应数据,小于255字节命令和响应,兼容CRW系列读卡器
Public Declare Function ICC_tsi_api Lib "wdcrwx.dll" (ByVal fd As Long, ByVal bLens As Byte, ByRef aComm As Byte, ByRef bLenr As Byte, ByRef aResp As Byte) As Long
'bLens 命令长度
'bComm 命令
'bLenr 返回响应长度
'bResp 返回响应
'返回sw
'6 字符串转换成二进制数组
Public Declare Sub CHexToBin Lib "wdcrwx.dll" (ByRef aBin As Byte, ByVal strAsc As String, ByVal lLenc As Long)
'aBin 返回的数组
'strAsc 输入的字符串
'lLenc 字符串的长度
'7 二进制转换成字符串
Public Declare Sub BinToCHex Lib "wdcrwx.dll" (ByVal strAsc As String, ByRef aBin As Byte, ByVal lLenc As Long)
'strAsc 返回的字符串
'aBin 输入的数组
'lLenc 数组的长度
'8 3Des加密
Public Declare Function TripleDES Lib "wdcrwx.dll" (ByVal bDESType As Byte, ByRef aTripleDESKey As Byte, ByVal bSourDataLen As Byte, ByRef aSourData As Byte, ByRef aDestData As Byte) As Long
'      DESType: =1 加密
'                 =2 解密
'        TripleDESKey: 16字节密钥 K1K2
'        SourDataLen:  源数据长度
'        SourData:     源数据
'        DestData:     目标数据
'
'     说明:
'        加密时,当明文长度不时8的倍数时,该函数在明文数据的后面
'        加上16进制数字串"80 00 00...", 使其为8的倍数后加密
'        加解密过程如下:
'        DES3-E({K1,K2},P)=E(K1,D(K2,E(K1,P)))
'        DES3-D({K1,K2},C)=D(K1,E(K2,D(K1,P)))
'
'    返回值：
'        目标数据的长度
9. 3DES认证码
Public Declare Function TripleMAC Lib "wdcrwx.dll" (ByRef aSingleMACKey As Byte, ByRef aInitData As Byte, ByVal lSourDataLen As Long, ByRef aSourData As Byte, ByRef aMACData As Byte) As Long
'        SingleMACKey: 16字节密钥
'        InitData:     8字节的初始值
'        SourDataLen:  用来产生mac码的原文长度
'        SourData:     用来产生mac码的原文
'        MactData:     计算出的认证码
'    返回值：
'        认证码的长度为8
'CRW-X 公用变量
Public fd As Long               '设备句柄
