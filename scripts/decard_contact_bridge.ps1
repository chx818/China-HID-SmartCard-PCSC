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
    public static extern short IC_InitType(IntPtr idComDev, short type);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuReset(IntPtr idComDev, out byte rlen, byte[] databuffer);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuApdu(IntPtr idComDev, byte slen, byte[] sendbuffer, out byte rlen, byte[] databuffer);

    [DllImport("dcic32.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern short IC_CpuApduEXT(IntPtr idComDev, short slen, byte[] sendbuffer, out short rlen, byte[] databuffer);

    public static void StartBridge(string driverPath, string host, int port) {
        Console.WriteLine("=============================================================");
        Console.WriteLine("  DeCard T6 / T10 Contact Smart Card Bridge (VPCD TCP " + port + ")");
        Console.WriteLine("  Hardware : DeCard T6 / T10 ISO 7816-3 T=0 Contact Interface");
        Console.WriteLine("=============================================================");

        if (!string.IsNullOrEmpty(driverPath) && Directory.Exists(driverPath)) {
            SetDllDirectory(driverPath);
        }

        Console.WriteLine("\n[Bridge] Connecting to DeCard reader via dcic32.dll (Port 100)...");
        IntPtr dev = IntPtr.Zero;
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
        byte[] rapdu = new byte[4096];

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

                        try {
                            client = new TcpClient(host, port);
                            client.NoDelay = true;
                            stream = client.GetStream();
                            cardPresent = true;
                            IC_DevBeep(dev, 10);
                            Console.WriteLine(string.Format("[Bridge] Card INSERTED! ATR: {0} ({1} bytes)", 
                                BitConverter.ToString(currentAtr), currentAtr.Length));
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
                                    byte rlen = 0;
                                    byte[] atrBuf = new byte[256];
                                    if (IC_CpuReset(dev, out rlen, atrBuf) == 0 && rlen > 0) {
                                        currentAtr = new byte[rlen];
                                        Array.Copy(atrBuf, currentAtr, rlen);
                                    }
                                }
                            } else if (len > 1) {
                                Console.WriteLine(string.Format("[APDU In  {0:HH:mm:ss.fff}] {1}", DateTime.Now, BitConverter.ToString(payload)));
                                byte[] cardResp = null;

                                if (payload.Length <= 255) {
                                    byte rlen = 0;
                                    short apduRet = IC_CpuApdu(dev, (byte)payload.Length, payload, out rlen, rapdu);
                                    if (apduRet == 0 && rlen > 0) {
                                        cardResp = new byte[rlen];
                                        Array.Copy(rapdu, cardResp, rlen);
                                    }
                                } else {
                                    short rlen = 0;
                                    short apduRet = IC_CpuApduEXT(dev, (short)payload.Length, payload, out rlen, rapdu);
                                    if (apduRet == 0 && rlen > 0) {
                                        cardResp = new byte[rlen];
                                        Array.Copy(rapdu, cardResp, rlen);
                                    }
                                }

                                if (cardResp != null) {
                                    Console.WriteLine(string.Format("[APDU Out {0:HH:mm:ss.fff}] {1}", DateTime.Now, BitConverter.ToString(cardResp)));
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
                            if ((DateTime.Now - lastPoll).TotalMilliseconds >= 400) {
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
                    Console.WriteLine("[Bridge] >>> Card REMOVED. Waiting for card... <<<\n");
                }
            }
        }
    }
}
'@

Add-Type -TypeDefinition $src
[DecardT6ContactBridge]::StartBridge($driverDir, $VpcdHost, $VpcdPort)
