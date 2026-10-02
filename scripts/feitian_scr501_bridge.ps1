# Feitian SCR501 Contactless & Contact Dual-Interface PC/SC Bridge
# Bridges Feitian SCR501 (VID_096E&PID_0603) Contactless Smart Card (ISO 14443 Type A / T=CL)
# and Contact Smart Card (ISO 7816) to Windows PC/SC via BixVReader (port 35963)

param(
    [switch]$NoWatchdog,
    [double]$IdleSeconds = 1.2,
    [string]$VpcdHost = "127.0.0.1",
    [int]$VpcdPort = 35963
)

# 1. Ensure 32-bit PowerShell for RK501API.dll x86 stdcall compatibility
if ([Environment]::Is64BitProcess) {
    Write-Host "[Launcher] Relaunching in 32-bit PowerShell (SysWOW64) for RK501API.dll..." -ForegroundColor Cyan
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
if (-not (Test-Path (Join-Path $driverDir "RK501API.dll"))) {
    $driverDir = Join-Path $scriptDir "drivers"
}
if (-not (Test-Path (Join-Path $driverDir "RK501API.dll"))) {
    $driverDir = $scriptDir
}

$src = @'
using System;
using System.IO;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public class FeitianSCR501Bridge {
    [DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern bool SetDllDirectory(string lpPathName);

    // Core Device Management
    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_dev_init(int port, int baud);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_dev_exit(int hDev);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_dev_beep(int hDev, byte time, byte cnt, byte type);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_dev_rfield(int hDev, byte mode, byte time);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_dev_check_card(int hDev, ref byte status);

    // Contact Card (ISO 7816)
    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_cpu_setslot(int hDev, byte slot);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_cpu_reset(int hDev, byte mode, ref int atrlen, byte[] atr, byte autoPPS);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_cpu_poweroff(int hDev);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_cpu_apdu(int hDev, byte protocol, int slen, byte[] sdata, ref int rlen, byte[] rdata, byte flag);

    // Contactless (ISO 14443 Type A / T=CL)
    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_typeA_request(int hDev, byte mode, ref ushort atqa);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_typeA_anticoll(int hDev, byte bcnt, byte[] uid);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_typeA_select(int hDev, byte bcnt, byte[] uid, ref byte sak);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_typeA_rats(int hDev, byte rate, ref int atslen, byte[] ats);

    [DllImport("RK501API.dll", CallingConvention = CallingConvention.StdCall)]
    public static extern int ft_iso14443_4_command(int hDev, byte[] sdata, int slen, byte[] rdata, ref int rlen, byte flag);

    public enum CardMedium { None, Contact, Contactless }

    private static int hDev = 0;
    private static CardMedium currentMedium = CardMedium.None;
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

    public static bool ActivateCard() {
        // 1. Check Contact Card Slot 0 first
        byte contactStatus = 0;
        int retChk = ft_dev_check_card(hDev, ref contactStatus);
        if (retChk == 0 && contactStatus != 0) {
            ft_cpu_setslot(hDev, 0);
            byte[] atrBuf = new byte[64];
            int atrLen = atrBuf.Length;
            int retReset = ft_cpu_reset(hDev, 0, ref atrLen, atrBuf, 0);
            if (retReset == 0 && atrLen > 0) {
                currentAtr = new byte[atrLen];
                Array.Copy(atrBuf, currentAtr, atrLen);
                currentMedium = CardMedium.Contact;
                return true;
            }
        }

        // 2. Check Contactless RF Pad
        ft_dev_rfield(hDev, 1, 0);
        ushort atqa = 0;
        int ret = ft_typeA_request(hDev, 0x52, ref atqa);
        if (ret != 0) {
            ret = ft_typeA_request(hDev, 0x26, ref atqa);
        }
        if (ret != 0) {
            currentMedium = CardMedium.None;
            return false;
        }

        // Cascade level 1
        byte[] uid1 = new byte[4];
        if (ft_typeA_anticoll(hDev, 1, uid1) != 0) {
            currentMedium = CardMedium.None;
            return false;
        }
        byte sak1 = 0;
        if (ft_typeA_select(hDev, 1, uid1, ref sak1) != 0) {
            currentMedium = CardMedium.None;
            return false;
        }

        byte finalSak = sak1;
        // Check Cascade Bit (Bit 3, mask 0x04) for 7-byte / 10-byte UID cards
        if ((sak1 & 0x04) != 0) {
            byte[] uid2 = new byte[4];
            if (ft_typeA_anticoll(hDev, 2, uid2) != 0) {
                currentMedium = CardMedium.None;
                return false;
            }
            byte sak2 = 0;
            if (ft_typeA_select(hDev, 2, uid2, ref sak2) != 0) {
                currentMedium = CardMedium.None;
                return false;
            }
            finalSak = sak2;
        }

        // Check if card supports ISO 14443-4 T=CL (Bit 6, mask 0x20)
        if ((finalSak & 0x20) != 0) {
            byte[] ats = new byte[64];
            int atslen = ats.Length;
            ret = ft_typeA_rats(hDev, 0, ref atslen, ats);
            if (ret == 0 && atslen > 0) {
                currentAtr = BuildAtrFromAts(ats, atslen);
            }
            currentMedium = CardMedium.Contactless;
            return true;
        } else {
            // Standard contactless storage card (Mifare Classic / Ultralight / Plus SL1)
            currentAtr = new byte[] { 
                0x3B, 0x8F, 0x80, 0x01, 0x80, 0x4F, 0x0C, 0xA0, 0x00, 0x00, 0x03, 0x06, 0x03, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x68 
            };
            currentMedium = CardMedium.Contactless;
            return true;
        }
    }

    public static bool CheckCardStillPresent() {
        if (currentMedium == CardMedium.Contact) {
            byte status = 0;
            int ret = ft_dev_check_card(hDev, ref status);
            return (ret == 0 && status != 0);
        } else if (currentMedium == CardMedium.Contactless) {
            byte[] probeApdu = new byte[] { 0x00, 0xC0, 0x00, 0x00, 0x00 };
            byte[] probeResp = new byte[32];
            int probeRlen = probeResp.Length;

            int ret = ft_iso14443_4_command(hDev, probeApdu, probeApdu.Length, probeResp, ref probeRlen, 0);
            if (ret == 0 && probeRlen >= 2) return true;

            Thread.Sleep(80);
            probeRlen = probeResp.Length;
            ret = ft_iso14443_4_command(hDev, probeApdu, probeApdu.Length, probeResp, ref probeRlen, 0);
            return (ret == 0 && probeRlen >= 2);
        }
        return false;
    }

    public static void StartBridge(string driverPath, string host, int port) {
        Console.Title = "Feitian SCR501 Contactless & Contact PC/SC Bridge";
        Console.WriteLine("=============================================================");
        Console.WriteLine("  Feitian SCR501 Dual-Interface PC/SC Bridge (VPCD TCP " + port + ")");
        Console.WriteLine("  Hardware : Feitian SCR501 (VID_096E&PID_0603)");
        Console.WriteLine("  Contactless (ISO 14443 Type A T=CL / MIFARE) + Contact (ISO 7816)");
        Console.WriteLine(string.Format("  Watchdog : {0} (Idle: {1}ms, Interval: {2}ms)", 
            EnableWatchdog ? "ENABLED" : "DISABLED", IdleThresholdMs, ProbeIntervalMs));
        Console.WriteLine("=============================================================\n");

        if (!string.IsNullOrEmpty(driverPath) && Directory.Exists(driverPath)) {
            SetDllDirectory(driverPath);
        }

        Console.WriteLine("[Bridge] Initializing Feitian SCR501 hardware...");
        bool printedWait = false;
        while (hDev <= 0) {
            hDev = ft_dev_init(100, 0);
            if (hDev <= 0) {
                if (!printedWait) {
                    Console.WriteLine("[Bridge] Waiting for Feitian SCR501 (VID_096E&PID_0603) USB connection...");
                    printedWait = true;
                }
                Thread.Sleep(1000);
            }
        }
        Console.WriteLine("[Bridge] Hardware initialized. Handle: " + hDev);
        ft_dev_rfield(hDev, 1, 0);

        bool cardPresent = false;
        TcpClient client = null;
        NetworkStream stream = null;
        byte[] rapdu = new byte[2048];

        Console.WriteLine("[Bridge] Dynamic Card Detection Loop ready.\n");

        while (true) {
            if (!cardPresent) {
                if (ActivateCard()) {
                    cardPresent = true;
                    try {
                        client = new TcpClient(host, port);
                        client.NoDelay = true;
                        stream = client.GetStream();
                        ft_dev_beep(hDev, 10, 1, 0);
                        Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Card INSERTED ({1})! ATR: {2}", 
                            DateTime.Now, currentMedium, BitConverter.ToString(currentAtr)));
                    } catch (Exception ex) {
                        Console.WriteLine("[Bridge] VPCD connect error: " + ex.Message);
                        cardPresent = false;
                        currentMedium = CardMedium.None;
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
                                if (cmd == 4) { 
                                    // VPCD_CTRL_ATR (Card Presence Poll from VPCD driver)
                                    byte[] respHdr = new byte[] { (byte)(currentAtr.Length >> 8), (byte)(currentAtr.Length & 0xFF) };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(currentAtr, 0, currentAtr.Length);
                                    stream.Flush();
                                } else if (cmd == 1) { // COLD RESET / POWER_ON
                                    Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Host requested COLD reset (cmd=1)", DateTime.Now));
                                    if (currentMedium == CardMedium.Contactless) {
                                        ft_dev_rfield(hDev, 0, 0);
                                        Thread.Sleep(20);
                                        ft_dev_rfield(hDev, 1, 0);
                                        Thread.Sleep(20);
                                        ActivateCard();
                                    } else if (currentMedium == CardMedium.Contact) {
                                        ft_cpu_setslot(hDev, 0);
                                        byte[] atrBuf = new byte[64];
                                        int atrLen = atrBuf.Length;
                                        ft_cpu_reset(hDev, 0, ref atrLen, atrBuf, 0);
                                    }
                                } else if (cmd == 2) { // WARM RESET
                                    Console.WriteLine(string.Format("[Bridge {0:HH:mm:ss.fff}] Host requested WARM reset (cmd=2)", DateTime.Now));
                                    if (currentMedium == CardMedium.Contact) {
                                        ft_cpu_setslot(hDev, 0);
                                        byte[] atrBuf = new byte[64];
                                        int atrLen = atrBuf.Length;
                                        ft_cpu_reset(hDev, 1, ref atrLen, atrBuf, 0);
                                    }
                                } else if (cmd == 0) { // POWER_OFF
                                    // Ignored
                                }
                            } else if (len > 1) {
                                Console.WriteLine(string.Format("[APDU In  {0:HH:mm:ss.fff}] {1}", DateTime.Now, BitConverter.ToString(payload)));
                                int rlen = rapdu.Length;
                                int retApdu = -1;

                                if (currentMedium == CardMedium.Contactless) {
                                    retApdu = ft_iso14443_4_command(hDev, payload, payload.Length, rapdu, ref rlen, 0);
                                    if (retApdu != 0 || rlen <= 0) {
                                        Thread.Sleep(20);
                                        rlen = rapdu.Length;
                                        retApdu = ft_iso14443_4_command(hDev, payload, payload.Length, rapdu, ref rlen, 0);
                                        if (retApdu != 0 || rlen <= 0) {
                                            if (!CheckCardStillPresent()) {
                                                Console.WriteLine("[Bridge] Contactless card REMOVED during APDU! Disconnecting VPCD...");
                                                throw new IOException("Card removed during APDU");
                                            }
                                        }
                                    }
                                } else if (currentMedium == CardMedium.Contact) {
                                    retApdu = ft_cpu_apdu(hDev, 0, payload.Length, payload, ref rlen, rapdu, 0);
                                    if (retApdu != 0 || rlen <= 0) {
                                        byte status = 0;
                                        ft_dev_check_card(hDev, ref status);
                                        if (status == 0) {
                                            Console.WriteLine("[Bridge] Contact card REMOVED from slot!");
                                            throw new IOException("Contact card removed from slot");
                                        }
                                    }
                                }

                                if (retApdu == 0 && rlen > 0) {
                                    Console.WriteLine(string.Format("[APDU Out {0:HH:mm:ss.fff}] {1}", DateTime.Now, BitConverter.ToString(rapdu, 0, rlen)));
                                    byte[] respHdr = new byte[] { (byte)(rlen >> 8), (byte)(rlen & 0xFF) };
                                    stream.Write(respHdr, 0, 2);
                                    stream.Write(rapdu, 0, rlen);
                                    stream.Flush();
                                } else {
                                    Console.WriteLine(string.Format("[APDU Err {0:HH:mm:ss.fff}] ret={1}, rlen={2}. Returning SW 6F 00", DateTime.Now, retApdu, rlen));
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
                                double sinceLastProbe = (DateTime.Now - lastProbeTime).TotalMilliseconds;

                                if (idleMs >= IdleThresholdMs && sinceLastProbe >= ProbeIntervalMs) {
                                    lastProbeTime = DateTime.Now;
                                    if (!CheckCardStillPresent()) {
                                        Thread.Sleep(80);
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
                    currentMedium = CardMedium.None;
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
    [FeitianSCR501Bridge]::EnableWatchdog = $false
} else {
    [FeitianSCR501Bridge]::EnableWatchdog = $true
    if ($IdleSeconds -gt 0) {
        [FeitianSCR501Bridge]::IdleThresholdMs = [int]($IdleSeconds * 1000)
    }
}

[FeitianSCR501Bridge]::StartBridge($driverDir, $VpcdHost, $VpcdPort)
