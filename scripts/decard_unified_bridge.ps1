# DeCard Dual-Interface (T6 / T10) Unified Contact & Contactless PC/SC Bridge
# Supports both Contact (ISO 7816) and Contactless (ISO 14443-4 T=CL) smart cards
# Compatible with: DeCard T6 Dual-Interface, DeCard T6 Single-Contact, DeCard T10
# Connects to BixVReader / VPCD via TCP Port 35963

param(
    [string]$VpcdHost = "127.0.0.1",
    [int]$VpcdPort = 35963,
    [ValidateSet("ContactFirst", "RfFirst")]
    [string]$Priority = "ContactFirst"
)

# 1. Ensure 32-bit PowerShell for dcic32.dll x86 compatibility
if ([Environment]::Is64BitProcess) {
    Write-Host "[Launcher] Relaunching in 32-bit PowerShell (SysWOW64) for dcic32.dll..." -ForegroundColor Cyan
    $syswow64PS = Join-Path $env:SystemRoot "SysWOW64\WindowsPowerShell\v1.0\powershell.exe"
    if (Test-Path $syswow64PS) {
        & $syswow64PS -NoProfile -ExecutionPolicy Bypass -File $PSCommandPath @args
        exit $LASTEXITCODE
    } else {
        Write-Error "32-bit PowerShell not found at $syswow64PS!"
        exit 1
    }
}

# 2. Add driver directory to DLL search path
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$driverDir = Join-Path (Split-Path -Parent $scriptDir) "drivers"
if (-not (Test-Path (Join-Path $driverDir "dcic32.dll"))) {
    $driverDir = Join-Path $scriptDir "drivers"
}
if (-not (Test-Path (Join-Path $driverDir "dcic32.dll"))) {
    $driverDir = $scriptDir
}

$src = @'
using System;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public class DecardUnifiedBridge {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern bool SetDllDirectory(string lpPathName);

    // Common
    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern IntPtr IC_InitCommAdvanced(short port);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_ExitComm(IntPtr idComDev);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_DevBeep(IntPtr idComDev, byte beeptime);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_ReadVer(IntPtr idComDev, byte[] ver);

    // Contact Slot (ISO 7816)
    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Status(IntPtr idComDev);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Down(IntPtr idComDev);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_InitType(IntPtr idComDev, short type);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuReset(IntPtr idComDev, out byte rlen, byte[] databuffer);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuGetProtocol(IntPtr idComDev);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuApdu(IntPtr idComDev, byte slen, byte[] sendbuffer, out byte rlen, byte[] databuffer);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuApduEXT(IntPtr idComDev, short slen, byte[] sendbuffer, out short rlen, byte[] databuffer);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuApduSourceEXT(IntPtr idComDev, short slen, byte[] sendbuffer, out short rlen, byte[] databuffer);

    // Contactless RF (ISO 14443 Type A / T=CL)
    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_ResetMifare(IntPtr idComDev, short _wMsec);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Request(IntPtr icdev, byte _Mode, out ushort _TagType);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Anticoll(IntPtr icdev, byte _bBcnt, out uint _dwSnr);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Select(IntPtr icdev, uint _dwSnr, out byte _bSize);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Anticoll2(IntPtr idComDev, byte _bBcnt, out uint _dwSnr);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Select2(IntPtr idComDev, uint _dwSnr, out byte _bSize);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Pro_Reset(IntPtr icdev, out byte rlen, byte[] receive_data);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_Pro_Commandsource(IntPtr idComDev, byte slen, byte[] sendbuffer, out byte rlen, byte[] databuffer, byte timeout);

    public enum CardMedium {
        None,
        Contact,
        Contactless
    }

    private static IntPtr dev = IntPtr.Zero;
    private static CardMedium activeMedium = CardMedium.None;
    private static byte rfBlockNum = 0;
    private static byte[] currentAtr = new byte[0];
    private static bool isCpuCard = false;

    private static short contactProtocol = 0; // 0=T=0, 1=T=1

    public static bool PreferContact = true;

    // Contact Card Helpers
    public static bool ActivateContactCard() {
        if (IC_Status(dev) != 0) return false;
        IC_InitType(dev, 0x0C);
        byte rlen = 0;
        byte[] atrBuf = new byte[256];
        short ret = IC_CpuReset(dev, out rlen, atrBuf);
        if (ret == 0 && rlen > 0) {
            currentAtr = new byte[rlen];
            Array.Copy(atrBuf, currentAtr, rlen);
            contactProtocol = IC_CpuGetProtocol(dev);
            return true;
        }
        return false;
    }

    private static byte[] SendRawContact(byte[] apdu) {
        short rlen = 0;
        byte[] rapdu = new byte[4096];
        short ret = IC_CpuApduSourceEXT(dev, (short)apdu.Length, apdu, out rlen, rapdu);
        if (ret == 0 && rlen > 0) {
            byte[] res = new byte[rlen];
            Array.Copy(rapdu, res, rlen);
            return res;
        }
        return null;
    }

    public static byte[] TransmitContactApdu(byte[] apdu) {
        if (apdu == null || apdu.Length < 4) return null;

        // If card operates in T=1: send directly via IC_CpuApduSourceEXT
        if (contactProtocol == 1) {
            return SendRawContact(apdu);
        }

        // T=0 Engine:
        // 1. Intercept GET RESPONSE (00 C0 00 00 Le) when Le == 0x00 (256 bytes)
        // DeCard T6 USB HID FIFO overruns when retrieving 256 bytes at once.
        // Retrieve in chunks <= 128 bytes.
        if (apdu.Length == 5 && apdu[0] == 0x00 && apdu[1] == 0xC0 && apdu[2] == 0x00 && apdu[3] == 0x00 && apdu[4] == 0x00) {
            byte[] r1 = SendRawContact(new byte[] { 0x00, 0xC0, 0x00, 0x00, 0x80 }); // 128 bytes
            if (r1 == null || r1.Length < 2) return r1;
            if (r1.Length > 2 && r1[r1.Length - 2] == 0x61) {
                byte remain = r1[r1.Length - 1];
                byte chunk2 = (byte)Math.Min((int)(remain == 0 ? 128 : remain), 128);
                byte[] r2 = SendRawContact(new byte[] { 0x00, 0xC0, 0x00, 0x00, chunk2 });
                if (r2 != null && r2.Length >= 2) {
                    MemoryStream ms = new MemoryStream();
                    ms.Write(r1, 0, r1.Length - 2);
                    ms.Write(r2, 0, r2.Length);
                    return ms.ToArray();
                }
            }
            return r1;
        }

        // 2. Case 1 APDU normalization: T=0 TPDU requires 5-byte header [CLA, INS, P1, P2, 00]
        byte[] cmdToSend = apdu;
        if (cmdToSend.Length == 4) {
            byte[] cmd5 = new byte[5];
            Array.Copy(cmdToSend, 0, cmd5, 0, 4);
            cmd5[4] = 0x00;
            cmdToSend = cmd5;
        }
        // 3. Case 4 APDU normalization:
        // In T=0, Case 4 short APDU (CLA INS P1 P2 Lc Data... Le) has length = 5 + Lc + 1.
        // Strip trailing Le byte to send as Case 3 TPDU; response data is retrieved via 61 loop.
        else if (cmdToSend.Length >= 6) {
            int lc = cmdToSend[4];
            if (cmdToSend.Length == 5 + lc + 1) {
                byte[] c3 = new byte[5 + lc];
                Array.Copy(cmdToSend, 0, c3, 0, 5 + lc);
                cmdToSend = c3;
            }
        }

        byte[] resp = SendRawContact(cmdToSend);
        if (resp == null || resp.Length < 2) return resp;

        // 4. Handle 6C xx (Wrong Le -> replay command with correct Le)
        if (resp.Length == 2 && resp[0] == 0x6C) {
            byte correctLe = resp[1];
            byte[] replay = new byte[cmdToSend.Length];
            Array.Copy(cmdToSend, replay, cmdToSend.Length);
            replay[replay.Length - 1] = correctLe;
            resp = SendRawContact(replay);
            if (resp == null || resp.Length < 2) return resp;
        }

        // 5. Handle 61 xx (Response data available -> GET RESPONSE loop with safe chunk size <= 128)
        if (resp.Length == 2 && resp[0] == 0x61) {
            MemoryStream ms = new MemoryStream();
            byte sw1 = resp[0];
            byte sw2 = resp[1];

            int round = 0;
            while (sw1 == 0x61 && round < 64) {
                round++;
                int want = (sw2 == 0) ? 256 : sw2;
                int chunk = Math.Min(want, 128); // Safe chunk size <= 128
                byte le = (byte)(chunk & 0xFF);

                byte[] getResp = new byte[] { 0x00, 0xC0, 0x00, 0x00, le };
                byte[] r = SendRawContact(getResp);
                if (r == null || r.Length < 2) break;

                if (r.Length > 2) {
                    ms.Write(r, 0, r.Length - 2);
                }

                sw1 = r[r.Length - 2];
                sw2 = r[r.Length - 1];
            }

            ms.WriteByte(sw1);
            ms.WriteByte(sw2);
            return ms.ToArray();
        }

        return resp;
    }

    // Contactless Card Helpers
    public static byte[] BuildAtrFromAts(byte[] ats, int atslen) {
        if (ats == null || atslen < 2) {
            return new byte[] { 
                0x3B, 0x8E, 0x80, 0x01, 0x80, 0x31, 0x80, 0x66, 0xB0, 0x84, 0x0C, 0x01, 0x6E, 0x01, 0x83, 0x00, 0x90, 0x00, 0x1D 
            };
        }
        byte tl = ats[0];
        byte t0 = ats[1];
        int offset = 2;
        if ((t0 & 0x10) != 0 && offset < atslen) offset++;
        if ((t0 & 0x20) != 0 && offset < atslen) offset++;
        if ((t0 & 0x40) != 0 && offset < atslen) offset++;

        int k = atslen - offset;
        if (k < 0) k = 0;
        if (k > 15) k = 15;

        byte[] atr = new byte[4 + k + 1];
        atr[0] = 0x3B;
        atr[1] = (byte)(0x80 | (k & 0x0F));
        atr[2] = 0x80;
        atr[3] = 0x01;
        for (int i = 0; i < k; i++) atr[4 + i] = ats[offset + i];
        byte tck = 0;
        for (int i = 1; i < 4 + k; i++) tck ^= atr[i];
        atr[4 + k] = tck;
        return atr;
    }

    public static bool ActivateRfCard() {
        ushort tagType = 0;
        short rReq = IC_Request(dev, 1, out tagType); // WUPA
        if (rReq != 0) {
            rReq = IC_Request(dev, 0, out tagType); // REQA
        }
        if (rReq != 0) return false;

        uint snr1 = 0;
        short rAnti1 = IC_Anticoll(dev, 0, out snr1);
        if (rAnti1 != 0) return false;

        byte sak1 = 0;
        short rSel1 = IC_Select(dev, snr1, out sak1);
        if (rSel1 != 0) return false;

        byte finalSak = sak1;

        if ((sak1 & 0x04) != 0) {
            uint snr2 = 0;
            short rAnti2 = IC_Anticoll2(dev, 0, out snr2);
            if (rAnti2 != 0) return false;

            byte sak2 = 0;
            short rSel2 = IC_Select2(dev, snr2, out sak2);
            if (rSel2 != 0) return false;

            finalSak = sak2;
        }

        byte rlen = 0;
        byte[] atsBuf = new byte[128];
        short rPro = IC_Pro_Reset(dev, out rlen, atsBuf);
        if (rPro == 0 && rlen > 0) {
            currentAtr = BuildAtrFromAts(atsBuf, rlen);
            rfBlockNum = 0;
            isCpuCard = true;
            return true;
        }

        if ((finalSak & 0x20) == 0) {
            currentAtr = new byte[] { 
                0x3B, 0x8F, 0x80, 0x01, 0x80, 0x4F, 0x0C, 0xA0, 0x00, 0x00, 0x03, 0x06, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x68 
            };
            rfBlockNum = 0;
            isCpuCard = false;
            return true;
        }

        IC_ResetMifare(dev, 10);
        return false;
    }

    public static bool CheckRfCardPresent() {
        if (isCpuCard) {
            byte emptyPcb = (byte)(0x02 | (rfBlockNum & 1));
            byte rlen = 0;
            byte[] rbuf = new byte[64];
            short ret = IC_Pro_Commandsource(dev, 1, new byte[] { emptyPcb }, out rlen, rbuf, 2);
            if (ret == 0 && rlen >= 1) {
                rfBlockNum ^= 1;
                return true;
            }
            // Debounce once after 40ms to avoid transient RF disturbance
            Thread.Sleep(40);
            emptyPcb = (byte)(0x02 | (rfBlockNum & 1));
            ret = IC_Pro_Commandsource(dev, 1, new byte[] { emptyPcb }, out rlen, rbuf, 2);
            if (ret == 0 && rlen >= 1) {
                rfBlockNum ^= 1;
                return true;
            }
            return false;
        } else {
            ushort tagType = 0;
            short r = IC_Request(dev, 1, out tagType);
            if (r == 0) return true;
            Thread.Sleep(40);
            r = IC_Request(dev, 1, out tagType);
            return (r == 0);
        }
    }

    // Production ISO 14443-4 T=CL Transceiver with Full Tx & Rx Chaining
    public static byte[] TransmitRfApdu(byte[] apdu, byte timeout = 10) {
        int maxChunk = 250;
        int offset = 0;
        byte respLen = 0;
        byte[] rawResp = new byte[256];

        // 1. Tx Phase: Chaining if APDU > maxChunk
        while (offset < apdu.Length) {
            int chunkLen = Math.Min(maxChunk, apdu.Length - offset);
            bool isLast = (offset + chunkLen == apdu.Length);

            byte pcb = (byte)((isLast ? 0x02 : 0x12) | (rfBlockNum & 1));
            byte[] frame = new byte[1 + chunkLen];
            frame[0] = pcb;
            Array.Copy(apdu, offset, frame, 1, chunkLen);

            short ret = IC_Pro_Commandsource(dev, (byte)frame.Length, frame, out respLen, rawResp, timeout);
            if (ret != 0 || respLen < 1) {
                return null;
            }

            // Handle S(WTX) during Tx
            while ((rawResp[0] & 0xF2) == 0xF2 && respLen >= 2) {
                byte[] wtxFrame = new byte[] { rawResp[0], rawResp[1] };
                ret = IC_Pro_Commandsource(dev, (byte)wtxFrame.Length, wtxFrame, out respLen, rawResp, timeout);
                if (ret != 0 || respLen < 1) return null;
            }

            if (!isLast) {
                // Expect R(ACK) block
                byte rxPcb = rawResp[0];
                if ((rxPcb & 0xF2) == 0xA2) {
                    rfBlockNum ^= 1;
                    offset += chunkLen;
                } else {
                    return null;
                }
            } else {
                offset += chunkLen;
            }
        }

        // 2. Rx Phase: Reassemble Response with Rx Chaining & WTX Handling
        MemoryStream fullResp = new MemoryStream();
        while (true) {
            byte rxPcb = rawResp[0];

            // WTX Request from card
            if ((rxPcb & 0xF2) == 0xF2 && respLen >= 2) {
                byte[] wtxFrame = new byte[] { rxPcb, rawResp[1] };
                short ret = IC_Pro_Commandsource(dev, (byte)wtxFrame.Length, wtxFrame, out respLen, rawResp, timeout);
                if (ret != 0 || respLen < 1) return null;
                continue;
            }

            // Chained I-Block from card
            if ((rxPcb & 0x10) != 0) {
                fullResp.Write(rawResp, 1, respLen - 1);
                rfBlockNum ^= 1;
                byte rAckPcb = (byte)(0xA2 | (rfBlockNum & 1));
                byte[] rAckFrame = new byte[] { rAckPcb };
                short ret = IC_Pro_Commandsource(dev, (byte)rAckFrame.Length, rAckFrame, out respLen, rawResp, timeout);
                if (ret != 0 || respLen < 1) return null;
                continue;
            }

            // Final I-Block from card
            fullResp.Write(rawResp, 1, respLen - 1);
            rfBlockNum ^= 1;
            break;
        }

        return fullResp.ToArray();
    }

    public static void StartBridge(string driverPath, string host, int port) {
        Console.Title = "DeCard Dual-Interface (T6 / T10) Unified PC/SC Bridge";
        Console.WriteLine("=============================================================");
        Console.WriteLine("  DeCard Unified Dual-Interface Bridge (VPCD TCP " + port + ")");
        Console.WriteLine("  Hardware : DeCard T6 / T10 (VID_0471&PID_A112)");
        Console.WriteLine("  Channels : Contact (ISO 7816) + Contactless RF (ISO 14443-4)");
        Console.WriteLine(string.Format("  Priority : {0}", PreferContact ? "Contact First" : "Contactless First"));
        Console.WriteLine("=============================================================\n");

        if (!string.IsNullOrEmpty(driverPath) && Directory.Exists(driverPath)) {
            SetDllDirectory(driverPath);
        }

        Console.WriteLine("[Bridge] Connecting to DeCard reader via dcic32.dll (Port 100)...");
        bool printedWait = false;
        while (dev.ToInt64() <= 0) {
            dev = IC_InitCommAdvanced(100);
            if (dev.ToInt64() <= 0) {
                if (!printedWait) {
                    Console.WriteLine("[Bridge] Waiting for DeCard reader USB connection...");
                    printedWait = true;
                }
                Thread.Sleep(1000);
            }
        }

        byte[] verBuf = new byte[128];
        IC_ReadVer(dev, verBuf);
        string verStr = Encoding.ASCII.GetString(verBuf).TrimEnd('\0', ' ', '\r', '\n');
        Console.WriteLine("[Bridge] Hardware connected. Handle: " + dev.ToInt64() + " (Firmware: " + verStr + ")");

        IC_DevBeep(dev, 10);
        IC_ResetMifare(dev, 20);
        Thread.Sleep(50);

        TcpClient client = null;
        NetworkStream stream = null;

        Console.WriteLine("[Bridge] Detection Loop Active: Insert contact card OR tap contactless card...\n");

        while (true) {
            if (activeMedium == CardMedium.None) {
                bool detected = false;

                if (PreferContact) {
                    if (ActivateContactCard()) {
                        activeMedium = CardMedium.Contact;
                        detected = true;
                    } else if (ActivateRfCard()) {
                        activeMedium = CardMedium.Contactless;
                        detected = true;
                    }
                } else {
                    if (ActivateRfCard()) {
                        activeMedium = CardMedium.Contactless;
                        detected = true;
                    } else if (ActivateContactCard()) {
                        activeMedium = CardMedium.Contact;
                        detected = true;
                    }
                }

                if (detected) {
                    try {
                        client = new TcpClient(host, port);
                        client.NoDelay = true;
                        stream = client.GetStream();
                        IC_DevBeep(dev, 10);
                        Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] >>> [{1} CARD INSERTED] ATR: {2}", 
                            DateTime.Now, activeMedium.ToString().ToUpper(), BitConverter.ToString(currentAtr)));
                    } catch (Exception ex) {
                        Console.WriteLine("[Bridge] VPCD connect error: " + ex.Message);
                        activeMedium = CardMedium.None;
                        Thread.Sleep(500);
                    }
                } else {
                    Thread.Sleep(50); // Snappy 50ms detection loop
                }
            } else {
                DateTime lastContactPoll = DateTime.Now;
                DateTime lastRfPoll = DateTime.Now;
                DateTime lastActivity = DateTime.Now;
                byte[] hdr = new byte[2];

                try {
                    while (activeMedium != CardMedium.None) {
                        if (stream.DataAvailable) {
                            lastActivity = DateTime.Now;
                            int read = 0;
                            while (read < 2) {
                                int r = stream.Read(hdr, read, 2 - read);
                                if (r <= 0) throw new IOException("Socket closed");
                                read += r;
                            }

                            int len = (hdr[0] << 8) | hdr[1];
                            if (len == 0) continue;

                            byte[] payload = new byte[len];
                            read = 0;
                            while (read < len) {
                                int r = stream.Read(payload, read, len - read);
                                if (r <= 0) throw new IOException("Socket closed");
                                read += r;
                            }

                            if (len == 1) {
                                byte cmd = payload[0];
                                if (cmd == 4) { // VPCD_CTRL_ATR
                                    byte[] respHdr = new byte[] { (byte)(currentAtr.Length >> 8), (byte)(currentAtr.Length & 0xFF) };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(currentAtr, 0, currentAtr.Length);
                                    stream.Flush();
                                } else if (cmd == 1 || cmd == 2) { // COLD RESET (1) or WARM RESET (2)
                                    Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Host requested {1} reset ({2})", 
                                        DateTime.Now, cmd == 1 ? "COLD" : "WARM", activeMedium));
                                    if (activeMedium == CardMedium.Contact) {
                                        if (cmd == 1) IC_InitType(dev, 0x0C);
                                        byte rlen = 0;
                                        byte[] atrBuf = new byte[256];
                                        short ret = IC_CpuReset(dev, out rlen, atrBuf);
                                        if (ret == 0 && rlen > 0) {
                                            currentAtr = new byte[rlen];
                                            Array.Copy(atrBuf, currentAtr, rlen);
                                            contactProtocol = IC_CpuGetProtocol(dev);
                                        }
                                    } else if (activeMedium == CardMedium.Contactless) {
                                        IC_ResetMifare(dev, 20);
                                        Thread.Sleep(30);
                                        ActivateRfCard();
                                    }
                                }
                            } else {
                                Console.WriteLine(string.Format("[APDU In  {0:HH:mm:ss.fff}] [{1}] (len={2}) {3}", 
                                    DateTime.Now, activeMedium, payload.Length, BitConverter.ToString(payload)));

                                byte[] cardResp = null;
                                if (activeMedium == CardMedium.Contact) {
                                    cardResp = TransmitContactApdu(payload);
                                } else if (activeMedium == CardMedium.Contactless) {
                                    cardResp = TransmitRfApdu(payload, 10);
                                }

                                if (cardResp == null || cardResp.Length < 2) {
                                    Thread.Sleep(20);
                                    if (activeMedium == CardMedium.Contact) {
                                        cardResp = TransmitContactApdu(payload);
                                        if (cardResp == null && IC_Status(dev) != 0) {
                                            Console.WriteLine("[Bridge] Contact card REMOVED during APDU!");
                                            throw new IOException("Contact card removed during APDU");
                                        }
                                    } else if (activeMedium == CardMedium.Contactless) {
                                        cardResp = TransmitRfApdu(payload, 5);
                                        if (cardResp == null) {
                                            Console.WriteLine("[Bridge] Contactless card lost/removed during APDU!");
                                            throw new IOException("Contactless card lost/removed during APDU");
                                        }
                                    }
                                }

                                if (cardResp != null && cardResp.Length >= 2) {
                                    Console.WriteLine(string.Format("[APDU Out {0:HH:mm:ss.fff}] [{1}] {2}", 
                                        DateTime.Now, activeMedium, BitConverter.ToString(cardResp)));
                                    byte[] respHdr = new byte[] { (byte)(cardResp.Length >> 8), (byte)(cardResp.Length & 0xFF) };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(cardResp, 0, cardResp.Length);
                                    stream.Flush();
                                } else {
                                    Console.WriteLine(string.Format("[APDU Err {0:HH:mm:ss.fff}] Failed. Returning SW 6F 00", DateTime.Now));
                                    byte[] errResp = new byte[] { 0x6F, 0x00 };
                                    byte[] respHdr = new byte[] { 0x00, 0x02 };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(errResp, 0, 2);
                                    stream.Flush();
                                }
                            }
                            lastActivity = DateTime.Now;
                        } else {
                            if (client.Client.Poll(0, SelectMode.SelectRead) && client.Client.Available == 0) {
                                throw new IOException("VPCD socket closed by host");
                            }

                            DateTime now = DateTime.Now;

                            // Contact slot physical microswitch monitoring
                            if (activeMedium == CardMedium.Contact) {
                                if ((now - lastContactPoll).TotalMilliseconds >= 250) {
                                    lastContactPoll = now;
                                    if (IC_Status(dev) != 0) {
                                        Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Contact card physically pulled from slot!", now));
                                        throw new IOException("Contact card removed");
                                    }
                                }
                            }
                            // Contactless RF field presence monitoring
                            else if (activeMedium == CardMedium.Contactless) {
                                if ((now - lastActivity).TotalMilliseconds >= 400 && (now - lastRfPoll).TotalMilliseconds >= 400) {
                                    lastRfPoll = now;
                                    if (!CheckRfCardPresent()) {
                                        Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Contactless card removed from RF field!", now));
                                        throw new IOException("Contactless card removed");
                                    }
                                }
                            }

                            Thread.Sleep(10);
                        }
                    }
                } catch (Exception ex) {
                    Console.WriteLine("[Bridge] Disconnected: " + ex.Message);
                    try { if (stream != null) stream.Close(); } catch {}
                    try { if (client != null) client.Close(); } catch {}
                    client = null;
                    stream = null;
                    CardMedium removedMedium = activeMedium;
                    activeMedium = CardMedium.None;
                    isCpuCard = false;
                    if (removedMedium == CardMedium.Contact) {
                        try { IC_Down(dev); } catch {}
                    } else if (removedMedium == CardMedium.Contactless) {
                        try { IC_ResetMifare(dev, 20); } catch {}
                    }
                    Console.WriteLine(string.Format("[Bridge] >>> [{0} CARD REMOVED]. Windows PC/SC notified (EMPTY). Waiting for card... <<<\n", 
                        removedMedium.ToString().ToUpper()));
                    Thread.Sleep(100);
                }
            }
        }
    }
}
'@

Add-Type -TypeDefinition $src

if ($Priority -eq "RfFirst") {
    [DecardUnifiedBridge]::PreferContact = $false
} else {
    [DecardUnifiedBridge]::PreferContact = $true
}

[DecardUnifiedBridge]::StartBridge($driverDir, $VpcdHost, $VpcdPort)
