VERSION 5.00
Object = "{F9043C88-F6F2-101A-A3C9-08002B2F49FB}#1.2#0"; "COMDLG32.OCX"
Object = "{3B7C8863-D78F-101B-B9B5-04021C009402}#1.2#0"; "RICHTX32.OCX"
Begin VB.Form CRWXDemo 
   AutoRedraw      =   -1  'True
   BorderStyle     =   1  'Fixed Single
   Caption         =   "CRWXDemo"
   ClientHeight    =   5655
   ClientLeft      =   45
   ClientTop       =   435
   ClientWidth     =   11745
   LinkTopic       =   "Form1"
   MaxButton       =   0   'False
   MinButton       =   0   'False
   ScaleHeight     =   5655
   ScaleWidth      =   11745
   StartUpPosition =   3  'Windows Default
   Begin RichTextLib.RichTextBox Response 
      Height          =   5175
      Left            =   5520
      TabIndex        =   25
      Top             =   240
      Width           =   6135
      _ExtentX        =   10821
      _ExtentY        =   9128
      _Version        =   393217
      BorderStyle     =   0
      ScrollBars      =   3
      TextRTF         =   $"CRWXDemo.frx":0000
   End
   Begin VB.Frame Frame2 
      Caption         =   "命令操作"
      Height          =   3135
      Left            =   120
      TabIndex        =   1
      Top             =   2280
      Width           =   5175
      Begin MSComDlg.CommonDialog CommonDialog1 
         Left            =   4200
         Top             =   1200
         _ExtentX        =   847
         _ExtentY        =   847
         _Version        =   393216
      End
      Begin VB.CommandButton OpenPrgFile 
         Caption         =   "打开"
         Height          =   375
         Left            =   4320
         TabIndex        =   24
         Top             =   2160
         Width           =   735
      End
      Begin VB.TextBox PrgFile 
         Height          =   405
         Left            =   600
         TabIndex        =   23
         Top             =   2160
         Width           =   3615
      End
      Begin VB.TextBox NewNad 
         Height          =   285
         Left            =   4320
         TabIndex        =   20
         Text            =   "12"
         Top             =   360
         Width           =   615
      End
      Begin VB.CommandButton SendPrg 
         Caption         =   "发送PRG"
         Enabled         =   0   'False
         Height          =   375
         Left            =   1440
         TabIndex        =   17
         Top             =   2640
         Width           =   1215
      End
      Begin VB.CommandButton SendCommand 
         Caption         =   "发送命令"
         Default         =   -1  'True
         Enabled         =   0   'False
         Height          =   375
         Left            =   1440
         TabIndex        =   15
         Top             =   1680
         Width           =   1215
      End
      Begin VB.TextBox Command 
         Height          =   1215
         Left            =   600
         MultiLine       =   -1  'True
         TabIndex        =   14
         Top             =   360
         Width           =   3135
      End
      Begin VB.Label command_len 
         Caption         =   "0"
         Height          =   255
         Left            =   4320
         TabIndex        =   22
         Top             =   840
         Width           =   495
      End
      Begin VB.Label Label8 
         Caption         =   "长度"
         Height          =   255
         Left            =   3840
         TabIndex        =   21
         Top             =   840
         Width           =   375
      End
      Begin VB.Label Label7 
         Caption         =   "NAD"
         Height          =   255
         Left            =   3840
         TabIndex        =   19
         Top             =   360
         Width           =   495
      End
      Begin VB.Label Label6 
         Caption         =   "命令"
         Height          =   255
         Left            =   120
         TabIndex        =   18
         Top             =   480
         Width           =   375
      End
      Begin VB.Label Label5 
         Caption         =   "PRG"
         Height          =   375
         Left            =   120
         TabIndex        =   16
         Top             =   2280
         Width           =   495
      End
   End
   Begin VB.Frame Frame1 
      Caption         =   "设备管理"
      Height          =   2055
      Left            =   120
      TabIndex        =   0
      Top             =   120
      Width           =   5175
      Begin VB.CommandButton ClosePort 
         Caption         =   "关闭"
         Enabled         =   0   'False
         Height          =   375
         Left            =   3960
         TabIndex        =   13
         Top             =   1320
         Width           =   975
      End
      Begin VB.CommandButton OpenPort 
         Caption         =   "打开"
         Height          =   375
         Left            =   2760
         TabIndex        =   12
         Top             =   1320
         Width           =   975
      End
      Begin VB.ComboBox Parity 
         Height          =   315
         ItemData        =   "CRWXDemo.frx":0098
         Left            =   3240
         List            =   "CRWXDemo.frx":00A2
         TabIndex        =   11
         Text            =   "E"
         Top             =   840
         Width           =   1455
      End
      Begin VB.ComboBox Rate 
         Height          =   315
         Left            =   3240
         TabIndex        =   9
         Text            =   "9600"
         Top             =   360
         Width           =   1455
      End
      Begin VB.ComboBox PortIndex 
         Height          =   315
         Left            =   1080
         TabIndex        =   6
         Text            =   "COM1"
         Top             =   1320
         Width           =   1455
      End
      Begin VB.ComboBox PortMode 
         Height          =   315
         ItemData        =   "CRWXDemo.frx":00BA
         Left            =   1080
         List            =   "CRWXDemo.frx":00C4
         TabIndex        =   5
         Text            =   "COM"
         Top             =   840
         Width           =   1455
      End
      Begin VB.ComboBox ReaderType 
         Enabled         =   0   'False
         Height          =   315
         Left            =   1080
         TabIndex        =   2
         Text            =   "CRW-X"
         Top             =   360
         Width           =   1455
      End
      Begin VB.Label Label4 
         Caption         =   "校验"
         Height          =   255
         Left            =   2760
         TabIndex        =   10
         Top             =   840
         Width           =   375
      End
      Begin VB.Label Label3 
         Caption         =   "速率"
         Height          =   255
         Left            =   2760
         TabIndex        =   8
         Top             =   360
         Width           =   495
      End
      Begin VB.Label Label2 
         Caption         =   "端口号"
         Height          =   255
         Left            =   360
         TabIndex        =   7
         Top             =   1320
         Width           =   615
      End
      Begin VB.Label Label1 
         Caption         =   "通讯方式"
         Height          =   255
         Left            =   240
         TabIndex        =   4
         Top             =   840
         Width           =   735
      End
      Begin VB.Label 读卡器类型 
         Caption         =   "读卡器型号"
         Height          =   255
         Left            =   120
         TabIndex        =   3
         Top             =   360
         Width           =   1095
      End
   End
End
Attribute VB_Name = "CRWXDemo"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Private Sub ClosePort_Click()
If fd > 0 Then
    CT_close (fd)   'close reader
    fd = -1
End If
SendCommand.Enabled = False
SendPrg.Enabled = False
ClosePort.Enabled = False
OpenPort.Enabled = True
End Sub
Private Sub Command_Change()
command_len = Len(Command.Text)
End Sub
Private Sub Command7_Click()
End Sub
Private Sub Form_Load()
Response.RightMargin = 10000
ShowScrollBar Response.hwnd, SB_HORZ, 1
Call SendMessage(Response.hwnd, EM_SETTARGETDEVICE, 0, 1)
fd = -1
End Sub
Private Sub Form_Unload(Cancel As Integer)
ClosePort_Click
End Sub
Private Sub OpenPort_Click()
Dim intRate As Integer
Dim bytParity As Byte
fd = -1
If PortMode = "COM" Then    '先做COM的参数变换和检查
    intRate = Val(Rate.Text)
    If intRate = 9600 Or intRate = 19200 Or intRate = 38400 Or intRate = 57600 Or intRate = 115200 Then
        bytParity = Asc(Parity.Text)
        If bytParity = Asc("N") Or bytParity = Asc("E") Then
            fd = CT_open(PortIndex.Text, intRate, bytParity) '打开COM设备
        End If
    End If
 Else
    fd = CT_open(PortIndex.Text, 0, 0) '打开USB设备
 End If
 
If fd = -1 Then
    MsgBox ("打开读卡器失败!")
    Exit Sub
End If
SendCommand.Enabled = True
SendPrg.Enabled = True
ClosePort.Enabled = True
OpenPort.Enabled = False
End Sub
Private Sub OpenPrgFile_Click()
CommonDialog1.Filter = "脚本文件(*.prg)|*.prg"
CommonDialog1.ShowOpen
If CommonDialog1.FileName <> "" Then
    PrgFile.Text = CommonDialog1.FileName
End If
End Sub
Private Sub Parity_DropDown()
Dim i As Integer
Dim count As Integer
count = Parity.ListCount
If count > 0 Then
    For i = 1 To count
        Parity.RemoveItem (0)
    Next
End If
If PortMode.Text = "COM" Then
    Parity.AddItem ("E 偶校验")
    Parity.AddItem ("N 无校验")
    
Else
    If PortMode.Text = "USB" Then
        Parity.AddItem ("0")
    End If
End If
End Sub
Private Sub PortIndex_DropDown()
Dim i As Integer
Dim count As Integer
count = PortIndex.ListCount
If count > 0 Then
    For i = 1 To count
        PortIndex.RemoveItem (0)
    Next
End If
If PortMode.Text = "COM" Then
    PortIndex.AddItem ("COM1")
    PortIndex.AddItem ("COM2")
    PortIndex.AddItem ("COM3")
    PortIndex.AddItem ("COM4")
Else
    If PortMode.Text = "USB" Then
        PortIndex.AddItem ("USB1")
        PortIndex.AddItem ("USB2")
        PortIndex.AddItem ("USB3")
        PortIndex.AddItem ("USB4")
    End If
End If
End Sub
Private Sub Rate_DropDown()
Dim i As Integer
Dim count As Integer
count = Rate.ListCount
If count > 0 Then
    For i = 1 To count
        Rate.RemoveItem (0)
    Next
End If
If PortMode.Text = "COM" Then
    Rate.AddItem ("9600")
    Rate.AddItem ("19200")
    Rate.AddItem ("57600")
    Rate.AddItem ("115200")
Else
    If PortMode.Text = "USB" Then
        Rate.AddItem ("0 共享模式")
        Rate.AddItem ("1 独占模式")
    End If
End If
End Sub
Private Sub Text3_Click()
End Sub
Private Sub SendCommand_Click()
Dim binComm(512) As Byte  '命令缓总区
Dim binResp(512) As Byte '接收数据缓冲区
Dim strComm As String * 512
Dim strResp As String * 512
Dim strTmp As String * 512
Dim lens As Long '发送数据长度
Dim lenr As Long '接收响应长度
Dim sw As Long               '状态字节
Dim bytLenr As Byte
Dim bytLens As Byte
Dim nad As Byte
Dim tmp As Long
lens = Len(Command.Text)
If lens >= 10 And lens < 512 Then
     Call CHexToBin(binComm(0), Command.Text, lens)
Else
    Exit Sub
End If
    lens = lens / 2
    bytLens = lens
    
If fd > 0 Then
    
    tmp = CLng("&H" + NewNad.Text)
    nad = tmp
    Call ICC_set_NAD(fd, nad)
    'sw = ICC_TransmitAPDU32(fd, lens, comm, lenr, resp)
    sw = ICC_tsi_api(fd, bytLens, binComm(0), bytLenr, binResp(0))
    If sw = CLng("&H9000") Then
        lenr = bytLenr
    Else
        lenr = 0
     End If
Else
    Exit Sub
End If
If sw = -1 Then
    MsgBox ("与读卡器通讯错误")
    Exit Sub
End If
Call BinToCHex(strResp, binResp(0), lenr)
Response.Text = Left(strResp, lenr * 2) + "SW" + Hex(sw)
End Sub
Private Sub SendPrg_Click()
Dim binComm(512) As Byte  '命令缓总区
Dim binResp(512) As Byte '接收数据缓冲区
Dim strComm As String
Dim strResp As String * 512
Dim strTmp As String   '临时字符串
Dim strSW As String    '用于比较的SW字符串
Dim strData As String  '用于比较的数据
Dim lens As Long            '发送数据长度
Dim lenr As Long            '接收响应长度
Dim sw As Long              '状态字节
Dim bytLenr As Byte
Dim bytLens As Byte
Dim nad As Byte
Dim tmp As Long
Dim prgFileName As String
Dim xx As Variant
'PRG 文件格式
'APDU [R resp] SW sw1 sw2
'sw1sw2=ffff,不作检查
prgFileName = PrgFile.Text
lens = Len(prgFileName)
If lens = 0 Then
    Exit Sub
End If
If fd > 0 Then  '设置nad
    tmp = CLng("&H" + NewNad.Text)
    nad = tmp
    Call ICC_set_NAD(fd, nad)
End If
Response.SelStart = 1
Response.Text = ""
Response.Enabled = False
Open prgFileName For Input As #1
Do While Not EOF(1) ' 循环至文件尾。
Line Input #1, strTmp ' 读入一行数据并将其赋予某变量。
    Trim (strTmp) '去掉可能存在多余的空格
    If Left(strTmp, 1) = "/" Then GoTo nextline   '跳过注释行
    If Left(strTmp, 3) = "NAD" Then
        xx = Split(strTmp, "=")
        strTmp = xx(1)
        Call CHexToBin(binComm(0), strTmp, 2)
        Call ICC_set_NAD(fd, binComm(0))
        GoTo nextline    '跳过设置NAD
    End If
    
    Response.SelColor = vbBlack
    Response.SelText = strTmp + vbCrLf
    'Response.SelStart = Response.SelStart + Len(strTmp)
    
    xx = Split(strTmp, "SW")
    strTmp = xx(0)
    If UBound(xx) = 1 Then
        strSW = xx(1)
    Else
        strSW = ""
    End If
    xx = Split(strTmp, "R")
    strComm = xx(0) '命令字符串
    If UBound(xx) = 1 Then
        strData = xx(1) '比较字符串
    Else
        strData = ""
    End If
    
lens = Len(strComm)
If lens >= 10 And lens < 512 Then
     Call CHexToBin(binComm(0), strComm, lens)
Else
    'Next
    
    GoTo nextline
End If
    lens = lens / 2
    bytLens = lens
    sw = ICC_tsi_api(fd, bytLens, binComm(0), bytLenr, binResp(0))
    If sw = -1 Then
        MsgBox ("与读卡器通讯错误")
        Exit Do
    End If
    If sw = CLng("&H9000") Then
        lenr = bytLenr
    Else
        lenr = 0
     End If
     If strData <> "" Then
        Call BinToCHex(strResp, binResp(0), lenr)
        strTmp = Left(strResp, lenr * 2)
        If strData <> strTmp Then
            strTmp = strTmp + "SW" + Hex(sw)
            Response.SelColor = vbRed
            Response.SelText = strTmp + vbCrLf
            Response.SelStart = Response.SelStart + Len(strTmp)
            Exit Do
        End If
     End If
     
    If strSW <> "" Then
    If sw <> CLng("&H" + strSW) Then
        strTmp = "SW" + Hex(sw)
        Response.SelColor = vbRed
        Response.SelText = strTmp + vbCrLf
        Response.SelStart = Response.SelStart + Len(strTmp)
        Exit Do
    End If
    End If
   
nextline:
DoEvents
Loop
Close #1 ' 关闭文件。
Response.Enabled = True
Exit Sub
    
End Sub
