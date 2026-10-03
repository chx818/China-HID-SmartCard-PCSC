# DeCard T6 / T10 Contact Smart Card PC/SC Bridge
# Connects to BixVReader / VPCD via TCP Port 35963

param(
    [string]$VpcdHost = "127.0.0.1",
    [int]$VpcdPort = 35963
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
    $driverDir = $scriptDir
}

$src = @'
using System;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public class DecardT6ContactBridge {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern bool SetDllDirectory(string lpPathName);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern IntPtr IC_InitCommAdvanced(short port);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_ExitComm(IntPtr idComDev);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_DevBeep(IntPtr idComDev, byte beeptime);

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
    public static extern short IC_CpuApduSourceEXT(IntPtr idComDev, short slen, byte[] sendbuffer, out short rlen, byte[] databuffer);

    private static IntPtr dev = IntPtr.Zero;
    private static short contactProtocol = 0; // 0=T=0, 1=T=1

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

    public static void StartBridge(string driverPath, string host, int port) {
        Console.WriteLine("=============================================================");
        Console.WriteLine("  DeCard T6 / T10 Contact Smart Card Bridge (VPCD TCP " + port + ")");
        Console.WriteLine("  Hardware : DeCard T6 / T10 ISO 7816-3 T=0/T=1 Contact");
        Console.WriteLine("=============================================================");

        if (!string.IsNullOrEmpty(driverPath) && Directory.Exists(driverPath)) {
            SetDllDirectory(driverPath);
        }

        Console.WriteLine("\n[Bridge] Connecting to DeCard reader via dcic32.dll (Port 100)...");
        bool printedWait = false;
        while (dev.ToInt64() <= 0) {
            dev = IC_InitCommAdvanced(100);
            if (dev.ToInt64() <= 0) {
                if (!printedWait) {
                    Console.WriteLine("[Bridge] Waiting for DeCard (T6 / T10) USB connection...");
                    printedWait = true;
                }
                Thread.Sleep(1000);
            }
        }
        long devVal = dev.ToInt64();
        Console.WriteLine("[Bridge] Connected to hardware. Handle: " + devVal + " (0x" + devVal.ToString("X") + ")");
        IC_DevBeep(dev, 10);

        bool cardPresent = false;
        byte[] currentAtr = new byte[0];
        TcpClient client = null;
        NetworkStream stream = null;

        Console.WriteLine("[Bridge] Card Detection Loop active. Insert card to begin...\n");

        while (true) {
            if (!cardPresent) {
                // Check if card is physically present in slot (IC_Status == 0)
                short st = IC_Status(dev);
                if (st == 0) {
                    IC_InitType(dev, 0x0C); // Main card slot
                    byte rlen = 0;
                    byte[] atrBuf = new byte[256];
                    short rst = IC_CpuReset(dev, out rlen, atrBuf);
                    if (rst == 0 && rlen > 0) {
                        currentAtr = new byte[rlen];
                        Array.Copy(atrBuf, currentAtr, rlen);
                        contactProtocol = IC_CpuGetProtocol(dev);

                        try {
                            client = new TcpClient(host, port);
                            client.NoDelay = true;
                            stream = client.GetStream();
                            cardPresent = true;
                            IC_DevBeep(dev, 10);
                            Console.WriteLine(string.Format("[Bridge] Card INSERTED! ATR: {0} ({1} bytes) [Protocol T={2}]", 
                                BitConverter.ToString(currentAtr), currentAtr.Length, contactProtocol));
                        } catch (Exception ex) {
                            Console.WriteLine("[Bridge] VPCD connection error: " + ex.Message);
                            Thread.Sleep(500);
                        }
                    } else {
                        Thread.Sleep(200);
                    }
                } else {
                    Thread.Sleep(200);
                }
            } else {
                DateTime lastPoll = DateTime.Now;
                byte[] hdr = new byte[2];

                try {
                    while (cardPresent) {
                        if (stream.DataAvailable) {
                            int read = 0;
                            while (read < 2) {
                                int r = stream.Read(hdr, read, 2 - read);
                                if (r <= 0) throw new IOException("Socket disconnected");
                                read += r;
                            }

                            int len = (hdr[0] << 8) | hdr[1];
                            if (len == 0) continue;

                            byte[] payload = new byte[len];
                            read = 0;
                            while (read < len) {
                                int r = stream.Read(payload, read, len - read);
                                if (r <= 0) throw new IOException("Socket disconnected");
                                read += r;
                            }

                            if (len == 1) {
                                byte cmd = payload[0];
                                if (cmd == 4) {
                                    // VPCD_CTRL_ATR (PC/SC driver ATR request)
                                    byte[] respHdr = new byte[] { (byte)(currentAtr.Length >> 8), (byte)(currentAtr.Length & 0xFF) };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(currentAtr, 0, currentAtr.Length);
                                    stream.Flush();
                                } else if (cmd == 1 || cmd == 2) {
                                    // Cold / Warm Reset
                                    Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Host requested Reset (cmd={1})", DateTime.Now, cmd));
                                    if (cmd == 1) IC_InitType(dev, 0x0C);
                                    byte rlen = 0;
                                    byte[] atrBuf = new byte[256];
                                    if (IC_CpuReset(dev, out rlen, atrBuf) == 0 && rlen > 0) {
                                        currentAtr = new byte[rlen];
                                        Array.Copy(atrBuf, currentAtr, rlen);
                                        contactProtocol = IC_CpuGetProtocol(dev);
                                    }
                                }
                            } else if (len > 1) {
                                Console.WriteLine(string.Format("[APDU In  {0:HH:mm:ss.fff}] len={1} {2}", 
                                    DateTime.Now, payload.Length, BitConverter.ToString(payload)));

                                byte[] cardResp = TransmitContactApdu(payload);

                                if (cardResp != null && cardResp.Length >= 2) {
                                    Console.WriteLine(string.Format("[APDU Out {0:HH:mm:ss.fff}] len={1} {2}", 
                                        DateTime.Now, cardResp.Length, BitConverter.ToString(cardResp)));
                                    byte[] respHdr = new byte[] { (byte)(cardResp.Length >> 8), (byte)(cardResp.Length & 0xFF) };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(cardResp, 0, cardResp.Length);
                                    stream.Flush();
                                } else {
                                    Console.WriteLine("[Bridge] APDU execution returned error from reader!");
                                    if (IC_Status(dev) != 0) {
                                        throw new IOException("Card removed during APDU");
                                    }
                                    byte[] errResp = new byte[] { 0x6F, 0x00 };
                                    byte[] respHdr = new byte[] { 0x00, 0x02 };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(errResp, 0, 2);
                                    stream.Flush();
                                }
                            }
                        } else {
                            if ((DateTime.Now - lastPoll).TotalMilliseconds >= 300) {
                                lastPoll = DateTime.Now;
                                if (IC_Status(dev) != 0) {
                                    Console.WriteLine("[Bridge] Contact card REMOVED!");
                                    throw new IOException("Card removed");
                                }
                            }
                            Thread.Sleep(10);
                        }
                    }
                } catch (Exception ex) {
                    Console.WriteLine("[Bridge] Disconnected: " + ex.Message);
                    try { if (stream != null) stream.Close(); } catch {}
                    try { if (client != null) client.Close(); } catch {}
                    cardPresent = false;
                    try { IC_Down(dev); } catch {}
                    Console.WriteLine("[Bridge] >>> Card REMOVED. Waiting for card... <<<\n");
                }
            }
        }
    }
}
'@

Add-Type -TypeDefinition $src
[DecardT6ContactBridge]::StartBridge($driverDir, $VpcdHost, $VpcdPort)
