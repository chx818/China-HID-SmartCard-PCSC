# DeCard Dual-Interface T6 / T10 Contactless (ISO 14443 Type A / T=CL) PC/SC Bridge
# Bridges DeCard T6 (VID_0471&PID_A112) Contactless Smart Card to Windows PC/SC via BixVReader (port 35963)
# Uses dcic32.dll (32-bit x86 stdcall) with hardware T=CL framing, Chaining, and Cascade Level 2 support

param(
    [switch]$NoWatchdog,
    [double]$IdleSeconds = 1.2,
    [string]$VpcdHost = "127.0.0.1",
    [int]$VpcdPort = 35963
)

# 1. Ensure 32-bit PowerShell for dcic32.dll x86 stdcall compatibility
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

public class DecardT6RfBridge {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern bool SetDllDirectory(string lpPathName);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern IntPtr IC_InitCommAdvanced(short port);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_ExitComm(IntPtr idComDev);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_DevBeep(IntPtr idComDev, byte beeptime);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_ReadVer(IntPtr idComDev, byte[] ver);

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

    private static IntPtr dev = IntPtr.Zero;
    private static byte blockNum = 0;
    private static byte[] currentAtr = new byte[] {
        0x3B, 0x8E, 0x80, 0x01, 0x80, 0x31, 0x80, 0x66, 0xB0, 0x84, 0x0C, 0x01, 0x6E, 0x01, 0x83, 0x00, 0x90, 0x00, 0x1D
    };

    public static bool EnableWatchdog = true;
    public static int IdleThresholdMs = 1200;
    public static int ProbeIntervalMs = 800;

    public static byte[] BuildAtrFromAts(byte[] ats, int atslen) {
        if (ats == null || atslen < 2) return currentAtr;
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

        // Cascade Level 2 for 7-byte / 10-byte UID cards (Bit 3, mask 0x04)
        if ((sak1 & 0x04) != 0) {
            uint snr2 = 0;
            short rAnti2 = IC_Anticoll2(dev, 0, out snr2);
            if (rAnti2 != 0) return false;

            byte sak2 = 0;
            short rSel2 = IC_Select2(dev, snr2, out sak2);
            if (rSel2 != 0) return false;

            finalSak = sak2;
        }

        // ISO 14443-4 T=CL activation (Bit 6, mask 0x20)
        byte rlen = 0;
        byte[] atsBuf = new byte[128];
        short rPro = IC_Pro_Reset(dev, out rlen, atsBuf);
        if (rPro == 0 && rlen > 0) {
            currentAtr = BuildAtrFromAts(atsBuf, rlen);
            blockNum = 0;
            return true;
        }

        // Fallback for storage cards without ATS (Mifare Classic / Plus SL1)
        if ((finalSak & 0x20) == 0) {
            currentAtr = new byte[] { 
                0x3B, 0x8F, 0x80, 0x01, 0x80, 0x4F, 0x0C, 0xA0, 0x00, 0x00, 0x03, 0x06, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x68 
            };
            blockNum = 0;
            return true;
        }

        return false;
    }

    public static byte[] TransmitApdu(byte[] apdu) {
        MemoryStream fullResp = new MemoryStream();
        byte pcb = (byte)(0x02 | (blockNum & 1));
        byte[] frame = new byte[1 + apdu.Length];
        frame[0] = pcb;
        Array.Copy(apdu, 0, frame, 1, apdu.Length);

        byte respLen = 0;
        byte[] rawResp = new byte[256];
        byte timeout = 0; // Fast response (~60ms) for snappy card detection/removal
        short ret = IC_Pro_Commandsource(dev, (byte)frame.Length, frame, out respLen, rawResp, timeout);

        if (ret != 0 || respLen < 1) {
            return null;
        }

        // Loop to handle WTX and Chaining
        while (true) {
            byte rxPcb = rawResp[0];

            // 1. WTX (Waiting Time Extension) S-Block (PCB = 0xF2)
            if ((rxPcb & 0xF2) == 0xF2 && respLen >= 2) {
                byte[] wtxResp = new byte[] { 0xF2, rawResp[1] };
                ret = IC_Pro_Commandsource(dev, (byte)wtxResp.Length, wtxResp, out respLen, rawResp, timeout);
                if (ret != 0 || respLen < 1) return null;
                continue;
            }

            // 2. Chaining: Chaining bit 0x10 is set in I-Block
            if ((rxPcb & 0x10) != 0) {
                // Append payload (excluding PCB byte 0)
                fullResp.Write(rawResp, 1, respLen - 1);
                blockNum ^= 1; // Toggle block number

                // Send R(ACK) block: 0xA2 | (next block number: 0 or 1)
                byte rAckPcb = (byte)(0xA2 | (blockNum & 1));
                byte[] rAckFrame = new byte[] { rAckPcb };
                ret = IC_Pro_Commandsource(dev, (byte)rAckFrame.Length, rAckFrame, out respLen, rawResp, timeout);
                if (ret != 0 || respLen < 1) return null;
                continue;
            }

            // 3. Final block: Chaining bit is NOT set
            fullResp.Write(rawResp, 1, respLen - 1);
            blockNum ^= 1; // Toggle block number for next transaction
            break;
        }

        return fullResp.ToArray();
    }

    public static bool CheckCardStillPresent() {
        byte[] probeApdu = new byte[] { 0x00, 0xC0, 0x00, 0x00, 0x00 };
        byte[] resp = TransmitApdu(probeApdu);
        if (resp != null && resp.Length >= 2) return true;

        Thread.Sleep(80);
        resp = TransmitApdu(probeApdu);
        return (resp != null && resp.Length >= 2);
    }

    public static void StartBridge(string driverPath, string host, int port) {
        Console.Title = "DeCard T6 Contactless (RF) PC/SC Bridge";
        Console.WriteLine("=============================================================");
        Console.WriteLine("  DeCard T6 Dual-Interface Contactless Bridge (VPCD TCP " + port + ")");
        Console.WriteLine("  Hardware : DeCard T6 (VID_0471&PID_A112) ISO 14443 Type A T=CL");
        Console.WriteLine(string.Format("  Watchdog : {0} (Idle: {1}ms, Interval: {2}ms)", 
            EnableWatchdog ? "ENABLED" : "DISABLED", IdleThresholdMs, ProbeIntervalMs));
        Console.WriteLine("=============================================================\n");

        if (!string.IsNullOrEmpty(driverPath) && Directory.Exists(driverPath)) {
            SetDllDirectory(driverPath);
        }

        Console.WriteLine("[Bridge] Connecting to DeCard T6 reader (Port 100)...");
        bool printedWait = false;
        while (dev.ToInt64() <= 0) {
            dev = IC_InitCommAdvanced(100);
            if (dev.ToInt64() <= 0) {
                if (!printedWait) {
                    Console.WriteLine("[Bridge] Waiting for DeCard T6 (VID_0471&PID_A112) USB connection...");
                    printedWait = true;
                }
                Thread.Sleep(1000);
            }
        }

        byte[] verBuf = new byte[128];
        IC_ReadVer(dev, verBuf);
        string verStr = Encoding.ASCII.GetString(verBuf).TrimEnd('\0', ' ', '\r', '\n');
        Console.WriteLine("[Bridge] Hardware connected. Handle: " + dev.ToInt64() + " (Firmware: " + verStr + ")");

        IC_ResetMifare(dev, 20);
        Thread.Sleep(50);

        bool cardPresent = false;
        TcpClient client = null;
        NetworkStream stream = null;

        Console.WriteLine("[Bridge] Contactless Card Detection Loop ready. Place card on reader...\n");

        while (true) {
            if (!cardPresent) {
                if (ActivateRfCard()) {
                    cardPresent = true;
                    try {
                        client = new TcpClient(host, port);
                        client.NoDelay = true;
                        stream = client.GetStream();
                        IC_DevBeep(dev, 10);
                        Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] RF Card INSERTED! ATR: {1}", 
                            DateTime.Now, BitConverter.ToString(currentAtr)));
                    } catch (Exception ex) {
                        Console.WriteLine("[Bridge] VPCD connect error: " + ex.Message);
                        cardPresent = false;
                        Thread.Sleep(500);
                    }
                } else {
                    Thread.Sleep(150);
                }
            } else {
                DateTime lastAppActivity = DateTime.Now;
                DateTime lastProbeTime = DateTime.MinValue;
                byte[] hdr = new byte[2];

                try {
                    while (cardPresent) {
                        if (stream.DataAvailable) {
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
                                } else if (cmd == 1) { // COLD RESET / POWER_ON
                                    Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Host requested COLD reset (cmd=1)", DateTime.Now));
                                    IC_ResetMifare(dev, 20);
                                    Thread.Sleep(30);
                                    ActivateRfCard();
                                } else if (cmd == 2) { // WARM RESET
                                    Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Host requested WARM reset (cmd=2)", DateTime.Now));
                                } else if (cmd == 0) { // POWER_OFF
                                    // Ignored
                                }
                            } else if (len > 1) {
                                Console.WriteLine(string.Format("[APDU In  {0:HH:mm:ss.fff}] {1}", DateTime.Now, BitConverter.ToString(payload)));
                                byte[] cardResp = TransmitApdu(payload);

                                if (cardResp == null || cardResp.Length < 2) {
                                    Thread.Sleep(20);
                                    cardResp = TransmitApdu(payload);
                                    if (cardResp == null || cardResp.Length < 2) {
                                        if (!CheckCardStillPresent()) {
                                            Console.WriteLine("[Bridge] Contactless card REMOVED during APDU! Disconnecting VPCD...");
                                            throw new IOException("Card removed during APDU");
                                        }
                                    }
                                }

                                if (cardResp != null && cardResp.Length >= 2) {
                                    Console.WriteLine(string.Format("[APDU Out {0:HH:mm:ss.fff}] {1}", DateTime.Now, BitConverter.ToString(cardResp)));
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

                                lastAppActivity = DateTime.Now;
                            }
                        } else {
                            if (client.Client.Poll(0, SelectMode.SelectRead) && client.Client.Available == 0) {
                                throw new IOException("VPCD socket closed by host");
                            }

                            if (EnableWatchdog) {
                                double idleMs = (DateTime.Now - lastAppActivity).TotalMilliseconds;
                                if (idleMs >= IdleThresholdMs) {
                                    double sinceLastProbe = (DateTime.Now - lastProbeTime).TotalMilliseconds;
                                    if (sinceLastProbe >= ProbeIntervalMs) {
                                        lastProbeTime = DateTime.Now;
                                        if (!CheckCardStillPresent()) {
                                            Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Watchdog: Card physically removed! Disconnecting...", DateTime.Now));
                                            throw new IOException("Card removed during idle");
                                        }
                                    }
                                }
                            }
                            Thread.Sleep(15);
                        }
                    }
                } catch (Exception ex) {
                    Console.WriteLine("[Bridge] Disconnected: " + ex.Message);
                    try { if (stream != null) stream.Close(); } catch {}
                    try { if (client != null) client.Close(); } catch {}
                    client = null;
                    stream = null;
                    cardPresent = false;
                    try { IC_ResetMifare(dev, 20); } catch {}
                    Console.WriteLine("[Bridge] >>> Card REMOVED. Windows PC/SC notified (EMPTY). Waiting for card... <<<\n");
                    Thread.Sleep(200);
                }
            }
        }
    }
}
'@

Add-Type -TypeDefinition $src

if ($NoWatchdog) {
    [DecardT6RfBridge]::EnableWatchdog = $false
} else {
    [DecardT6RfBridge]::EnableWatchdog = $true
    if ($IdleSeconds -gt 0) {
        [DecardT6RfBridge]::IdleThresholdMs = [int]($IdleSeconds * 1000)
    }
}

[DecardT6RfBridge]::StartBridge($driverDir, $VpcdHost, $VpcdPort)
