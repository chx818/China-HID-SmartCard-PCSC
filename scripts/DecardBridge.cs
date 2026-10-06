using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;

namespace ChinaHid {
    public sealed class LinkException : IOException {
        public LinkException(string message) : base(message) { }
    }

    public static class Apdu {
        public static byte[] Slice(byte[] b, int start, int count) {
            byte[] r = new byte[count]; Array.Copy(b, start, r, 0, count); return r;
        }
        public static byte[] Status(byte sw1, byte sw2) { return new byte[] { sw1, sw2 }; }
        public static byte[] Checked(byte[] r) {
            if (r == null || r.Length < 2 || r.Length > 65535)
                throw new LinkException("Invalid or missing R-APDU; execution outcome unknown");
            return r;
        }
        // Short APDU syntax, plus ISO extended APDUs. No narrowing casts before validation.
        public static bool Valid(byte[] c) {
            if (c == null || c.Length < 4 || c.Length > 65535) return false;
            if (c.Length <= 5) return true;
            if (c[4] != 0) return c.Length == 5 + c[4] || c.Length == 6 + c[4];
            if (c.Length < 7) return false;
            if (c.Length == 7) return true;
            int lc = (c[5] << 8) | c[6];
            return lc > 0 && (c.Length == 7 + lc || c.Length == 9 + lc);
        }
        private static bool Protected(byte cla) {
            if ((cla & 0x80) != 0) return (cla & 0x0C) != 0; // GP secure messaging, e.g. CLA 84.
            return (cla & 0x40) == 0 ? (cla & 0x0C) != 0 : (cla & 0x20) != 0;
        }
        private static byte GetResponseCla(byte cla) {
            // Proprietary class 80 (e.g. GP GET DATA) uses the basic interindustry channel.
            return (byte)((cla & 0x80) != 0 ? (cla & 3) : (cla & 0xEF));
        }
        public static byte[] Contact(byte[] command, int protocol, Func<byte[], byte[]> exchange) {
            return Contact(command, protocol, exchange, Int16.MaxValue);
        }
        public static byte[] Contact(byte[] command, int protocol, Func<byte[], byte[]> exchange, int nativeLimit) {
            if (!Valid(command)) return Status(0x67, 0);
            if (command.Length > Int16.MaxValue) return Status(0x67, 0);
            if (protocol == 1) {
                if (command.Length > nativeLimit) return Status(0x67, 0);
                return Checked(exchange((byte[])command.Clone()));
            }
            if (protocol != 0) throw new LinkException("Unsupported contact protocol");
            bool case2 = command.Length == 5;
            bool case4 = command.Length > 5 && command[4] != 0 && command.Length == 6 + command[4];
            int le = (case2 || case4) ? (command[command.Length - 1] == 0 ? 256 : command[command.Length - 1]) : 0;
            bool automatic = !Protected(command[0]);
            byte[] c = (byte[])command.Clone();
            if (c.Length == 4) { c = new byte[5]; Array.Copy(command, c, 4); }
            else if (case4) c = Slice(c, 0, c.Length - 1);
            // T6 T=0 GET RESPONSE has a 256-byte receive boundary: request <=128 per TPDU.
            if (automatic && case2 && c[1] == 0xC0 && le > 128) c[4] = 128;
            if (c.Length > nativeLimit) return Status(0x67, 0);
            byte[] r = Checked(exchange(c));
            // A 6C status can correct Le only when the original APDU actually has a Le-only TPDU.
            if (automatic && case2 && r.Length == 2 && r[0] == 0x6C) {
                int corrected = r[1] == 0 ? 256 : r[1];
                if (c[1] == 0xC0 && corrected > 128) return r; // Do not bypass the device limit.
                c = (byte[])c.Clone(); c[4] = r[1]; le = corrected;
                r = Checked(exchange(c));
            }
            if (!automatic) return r;
            // Keep the established T6 mapping: extended commands reach the SDK unchanged,
            // and automatic 61 chaining also applies to Case 3. Do not newly clip responses
            // to the caller's Le: existing clients/AlgTest depend on the reader's mapping.
            int responseLimit = case2 && command[1] == 0xC0 && command[4] == 0 ? 256 : 65533;
            using (MemoryStream result = new MemoryStream()) {
                for (int rounds = 0; rounds <= 64; rounds++) {
                    int count = r.Length - 2;
                    if (result.Length + count > 65533) throw new LinkException("T=0 response exceeds VPCD capacity");
                    result.Write(r, 0, count);
                    byte sw1 = r[r.Length - 2], sw2 = r[r.Length - 1];
                    int remaining = Math.Max(0, responseLimit - (int)result.Length);
                    if (sw1 != 0x61 || remaining == 0 || rounds == 64) {
                        result.WriteByte(sw1); result.WriteByte(sw2); return result.ToArray();
                    }
                    if (rounds > 0 && count == 0) throw new LinkException("GET RESPONSE made no progress");
                    int amount = Math.Min(Math.Min(sw2 == 0 ? 256 : sw2, remaining), 128);
                    byte[] get = new byte[] { GetResponseCla(command[0]), 0xC0, 0, 0, (byte)amount };
                    r = Checked(exchange(get));
                    if (r.Length == 2 && r[0] == 0x6C && r[1] > 0 && r[1] <= amount) {
                        get[4] = r[1]; r = Checked(exchange(get));
                    }
                }
            }
            throw new LinkException("GET RESPONSE limit exceeded");
        }
    }

    public sealed class ContactAtr {
        public int Protocol { get; private set; }
        public static ContactAtr Parse(byte[] atr) {
            if (atr == null || atr.Length < 2 || atr.Length > 33 || (atr[0] != 0x3B && atr[0] != 0x3F))
                throw new LinkException("Invalid contact ATR");
            int cursor = 2, y = atr[1] >> 4, group = 1, firstProtocol = -1, specificProtocol = -1;
            int sdkProtocol = 0; bool tck = false, crc = false;
            while (y != 0) {
                for (int bit = 1; bit <= 4; bit <<= 1) {
                    if ((y & bit) == 0) continue;
                    if (cursor >= atr.Length) throw new LinkException("Truncated contact ATR interface bytes");
                    byte value = atr[cursor++];
                    if (group == 2 && bit == 1) specificProtocol = value & 15;
                    if (group == 3 && bit == 4) crc = (value & 1) != 0;
                }
                if ((y & 8) == 0) break;
                if (cursor >= atr.Length) throw new LinkException("Truncated contact ATR TD byte");
                byte td = atr[cursor++]; int protocol = td & 15;
                if (group == 1) sdkProtocol = protocol == 1 ? 1 : 0;
                if (firstProtocol < 0 && protocol != 15) firstProtocol = protocol;
                if (protocol != 0) tck = true;
                y = td >> 4; group++;
            }
            int expected = cursor + (atr[1] & 15) + (tck ? 1 : 0);
            if (expected != atr.Length) throw new LinkException("Contact ATR length mismatch");
            if (tck) {
                byte xor = 0; for (int i = 1; i < atr.Length; i++) xor ^= atr[i];
                if (xor != 0) throw new LinkException("Contact ATR checksum mismatch");
            }
            int selected = specificProtocol >= 0 ? specificProtocol : firstProtocol < 0 ? 0 : firstProtocol;
            if (selected != 0 && selected != 1) throw new LinkException("Unsupported contact protocol " + selected);
            if (selected != sdkProtocol) throw new LinkException("ATR protocol requires negotiation unsupported by packaged dcrf32");
            if (selected == 1 && crc) throw new LinkException("Packaged dcrf32 T=1 supports LRC, not ATR-requested CRC");
            return new ContactAtr { Protocol = selected };
        }
    }

    public sealed class Ats {
        public byte[] Atr { get; private set; }
        public int FrameSize { get; private set; }
        public static Ats Parse(byte[] ats) {
            if (ats == null || ats.Length < 1 || ats.Length > 20 || ats[0] != ats.Length)
                throw new LinkException("Invalid ATS length");
            int offset = 1, fsci = 2; // TL-only ATS uses the standard default FSC=32.
            if (ats.Length > 1) {
                byte t0 = ats[1]; offset = 2; fsci = t0 & 15;
                if ((t0 & 0x80) != 0 || fsci > 8) throw new LinkException("Unsupported ATS frame size");
                foreach (int bit in new int[] { 0x10, 0x20, 0x40 }) {
                    if ((t0 & bit) != 0) {
                        if (offset >= ats.Length) throw new LinkException("Truncated ATS interface bytes");
                        if (bit == 0x20 && ((ats[offset] >> 4) == 15 || (ats[offset] & 15) == 15))
                            throw new LinkException("Reserved ATS waiting time");
                        offset++;
                    }
                }
            }
            int k = ats.Length - offset;
            if (k > 15) throw new LinkException("Too many ATS historical bytes");
            byte[] atr = new byte[5 + k];
            atr[0] = 0x3B; atr[1] = (byte)(0x80 | k); atr[2] = 0x80; atr[3] = 1;
            Array.Copy(ats, offset, atr, 4, k);
            for (int i = 1; i < atr.Length - 1; i++) atr[atr.Length - 1] ^= atr[i];
            return new Ats { Atr = atr, FrameSize = new int[] { 16,24,32,40,48,64,96,128,256 }[fsci] };
        }
    }

    public sealed class IsoDep {
        private readonly Func<byte[], byte, byte[]> exchange;
        private readonly int chunk;
        private int block;
        public bool StartupPresence { get; set; }
        public int MaxBlocks = 16384;
        public int MaxWtx = 4096;
        // Long operations that keep responding with WTX must not be cut off at 30 seconds.
        // The SDK retains its per-exchange timeout; optional total deadlines are opt-in.
        public int DeadlineMs = 0;
        public IsoDep(Ats ats, Func<byte[], byte, byte[]> exchange) : this(ats, exchange, 250) { }
        public IsoDep(Ats ats, Func<byte[], byte, byte[]> exchange, int maxInf) {
            if (maxInf < 1 || maxInf > 250) throw new ArgumentOutOfRangeException("maxInf");
            this.exchange = exchange;
            // FSC includes PCB and CRC; the backend also has its own envelope limit.
            chunk = Math.Min(maxInf, ats.FrameSize - 3);
        }
        private byte[] Exchange(byte[] frame, Stopwatch clock, ref int blocks, ref int wtx, bool presence) {
            byte initialTimeout = presence && !StartupPresence ? (byte)2 : (byte)10;
            byte timeout = initialTimeout;
            int deadline = presence ? (StartupPresence ? 5000 : 1500) : DeadlineMs;
            while (true) {
                if (++blocks > (presence ? (StartupPresence ? 64 : 16) : MaxBlocks) || (deadline > 0 && clock.ElapsedMilliseconds >= deadline))
                    throw new LinkException("ISO-DEP exchange deadline/block limit");
                byte[] r = exchange(frame, timeout);
                if (deadline > 0 && clock.ElapsedMilliseconds >= deadline) throw new LinkException("ISO-DEP exchange deadline");
                if (r == null || r.Length < 1 || r.Length > 255) throw new LinkException("RF exchange failed; execution outcome unknown");
                if (r[0] != 0xF2) return r;
                if (r.Length != 2 || r[1] < 1 || r[1] > 59 || ++wtx > (presence ? (StartupPresence ? 32 : 4) : MaxWtx))
                    throw new LinkException("Invalid or excessive WTX");
                frame = new byte[] { 0xF2, r[1] };
                timeout = (byte)Math.Min(255, initialTimeout * r[1]);
            }
        }
        public byte[] Transmit(byte[] apdu) {
            if (!Apdu.Valid(apdu)) return Apdu.Status(0x67, 0);
            Stopwatch clock = Stopwatch.StartNew(); int blocks = 0, wtx = 0;
            byte[] r = null;
            for (int offset = 0; offset < apdu.Length;) {
                int count = Math.Min(chunk, apdu.Length - offset);
                bool last = offset + count == apdu.Length;
                byte[] frame = new byte[1 + count]; frame[0] = (byte)((last ? 0x02 : 0x12) | block);
                Array.Copy(apdu, offset, frame, 1, count);
                r = Exchange(frame, clock, ref blocks, ref wtx, false);
                if (!last) {
                    if (r.Length != 1 || r[0] != (0xA2 | block))
                        throw new LinkException("Expected RF R(ACK) with current block number");
                    block ^= 1;
                }
                offset += count;
            }
            byte[] response = Receive(r, clock, ref blocks, ref wtx, false);
            StartupPresence = false;
            return response;
        }
        private byte[] Receive(byte[] r, Stopwatch clock, ref int blocks, ref int wtx, bool presence) {
            using (MemoryStream result = new MemoryStream()) {
                while (true) {
                    byte pcb = r[0];
                    // Only I-blocks without CID/NAD are negotiated. Never expose control frames as APDU data.
                    if ((pcb & 0xEE) != 0x02 || (pcb & 1) != block)
                        throw new LinkException("Unexpected RF block type/sequence: expected=" + block + ", PCB=" + pcb.ToString("X2") + ", len=" + r.Length);
                    if ((!presence && r.Length < 2) || result.Length + r.Length - 1 > 65535)
                        throw new LinkException("RF response length limit");
                    result.Write(r, 1, r.Length - 1);
                    block ^= 1;
                    if ((pcb & 0x10) == 0) return presence ? result.ToArray() : Apdu.Checked(result.ToArray());
                    r = Exchange(new byte[] { (byte)(0xA2 | block) }, clock, ref blocks, ref wtx, presence);
                }
            }
        }
        // Preserve the original T6 empty-I presence check and shared block sequence.
        // The Session invokes this only between complete APDU exchanges, never during WTX/chaining.
        public bool Present() {
            Stopwatch clock = Stopwatch.StartNew(); int blocks = 0, wtx = 0;
            byte[] frame = new byte[] { (byte)(0x02 | block) };
            byte[] r;
            try { r = Exchange(frame, clock, ref blocks, ref wtx, true); }
            catch (IOException) {
                Thread.Sleep(40);
                // Retry only the presence frame with its original number, never a business APDU.
                clock.Restart(); blocks = 0; wtx = 0;
                try { r = Exchange(frame, clock, ref blocks, ref wtx, true); }
                catch (IOException) { return false; }
            }
            // An echo may have no INF (observed on T6). Drain any chained reply before
            // accepting another APDU, and advance the number only for validated I-blocks.
            Receive(r, clock, ref blocks, ref wtx, true);
            StartupPresence = false;
            return true;
        }
    }

    public interface ICard : IDisposable {
        byte[] Atr { get; }
        string Medium { get; }
        bool Activate(string mode, bool preferContact);
        void Reset();
        void PowerOff();
        bool ContactPresent();
        bool RfPresent();
        byte[] Transmit(byte[] apdu);
    }

    internal static class Native {
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        internal static extern IntPtr LoadLibraryEx(string file, IntPtr reserved, uint flags);

        // dcic32.dll (T6 / standard DeCard Contact IC)
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_ReadVer(IntPtr d, [Out] byte[] b);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern IntPtr IC_InitCommAdvanced(short port);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_ExitComm(IntPtr d);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_DevBeep(IntPtr d, byte duration);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Status(IntPtr d);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Down(IntPtr d);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_InitType(IntPtr d, short type);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_CpuReset(IntPtr d, out byte n, [Out] byte[] b);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_CpuGetProtocol(IntPtr d);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_CpuApduSourceEXT(IntPtr d, short n, byte[] c, out short len, [Out] byte[] b);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_ResetMifare(IntPtr d, short ms);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Request(IntPtr d, byte mode, out ushort type);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Anticoll(IntPtr d, byte bits, out uint uid);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Select(IntPtr d, uint uid, out byte sak);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Anticoll2(IntPtr d, byte bits, out uint uid);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Select2(IntPtr d, uint uid, out byte sak);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Pro_Reset(IntPtr d, out byte len, [Out] byte[] b);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_Pro_Commandsource(IntPtr d, byte len, byte[] c, out byte n, [Out] byte[] b, byte timeout);

        // dcrf32.dll (A133 contact slot 0x0C and RF)
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_getver(int d, [Out] byte[] b);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int dc_init(short port, int baud);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_exit(int d);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_beep(int d, short duration);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_reset(int d, ushort ms);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_config_card(int d, byte type);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_request(int d, byte mode, out ushort type);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_anticoll(int d, byte bits, out uint uid);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_select(int d, uint uid, out byte sak);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_anticoll2(int d, byte bits, out uint uid);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_select2(int d, uint uid, out byte sak);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_pro_reset(int d, out byte len, [Out] byte[] b);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_pro_commandsource(int d, byte len, byte[] c, out byte n, [Out] byte[] b, byte timeout);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_setcpu(int d, byte slot);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_cpureset(int d, out byte n, [Out] byte[] b);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_cpudown(int d);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_cpuapdusource(int d, byte len, byte[] c, out byte n, [Out] byte[] b);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_cpuapdu(int d, byte len, byte[] c, out byte n, [Out] byte[] b);
    }

    public sealed class Decard : ICard {
        private IntPtr dev;
        private bool useDcrf;
        private static bool icLoaded, rfLoaded;
        private static string loadedDirectory;
        private bool rfFieldOn;
        private bool contactPowered;
        private short contactProbeCode;
        private Stopwatch rfActivated = new Stopwatch();
        private Stopwatch deviceHealth = Stopwatch.StartNew();
        private bool isYubiKey;
        private IsoDep rf;
        public string Backend { get { return useDcrf ? "dcrf32" : "dcic32"; } }
        private int protocol;
        public byte[] Atr { get; private set; }
        public string Medium { get; private set; }
        public static void LoadDriver(string directory) {
            if (IntPtr.Size != 4) throw new InvalidOperationException("DeCard driver requires x86 PowerShell");
            directory = Path.GetFullPath(directory);
            if (loadedDirectory != null) {
                if (!String.Equals(directory, loadedDirectory, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Vendor libraries already loaded from another directory");
                return;
            }
            string icPath = Path.Combine(directory, "dcic32.dll");
            string rfPath = Path.Combine(directory, "dcrf32.dll");
            if (File.Exists(icPath)) {
                icLoaded = Native.LoadLibraryEx(icPath, IntPtr.Zero, 0x100 | 0x800) != IntPtr.Zero;
                if (!icLoaded) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Cannot load packaged dcic32.dll");
            }
            if (File.Exists(rfPath)) {
                rfLoaded = Native.LoadLibraryEx(rfPath, IntPtr.Zero, 0x100 | 0x800) != IntPtr.Zero;
                if (!rfLoaded) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Cannot load packaged dcrf32.dll");
            }
            if (!icLoaded && !rfLoaded) throw new FileNotFoundException("No packaged DeCard SDK DLL found", directory);
            loadedDirectory = directory;
        }
        public Decard() {
            Atr = new byte[0]; Medium = "None";
            if (loadedDirectory == null) throw new InvalidOperationException("LoadDriver must succeed before opening a reader");
            // These packaged x86 SDKs return positive port tokens and negative error codes.
            // A token belongs to exactly one DLL. Never mix calls from two SDKs.
            long icResult = 0, rfResult = 0;
            if (icLoaded) { dev = Native.IC_InitCommAdvanced(100); icResult = dev.ToInt64(); }
            if (dev.ToInt64() <= 0 && rfLoaded) {
                int token = Native.dc_init(100, 115200); rfResult = token;
                if (token > 0) { dev = new IntPtr(token); useDcrf = true; }
            }
            if (dev.ToInt64() <= 0) {
                dev = IntPtr.Zero;
                throw new LinkException("Cannot open DeCard USB reader (dcic32=" + icResult + ", dcrf32=" + rfResult + ")");
            }
        }
        internal void Beep() {
            if (useDcrf) Native.dc_beep((int)dev, 10);
            else Native.IC_DevBeep(dev, 10);
        }
        private static void Require(short code, string operation) {
            if (code != 0) throw new LinkException(operation + " failed: " + code);
        }
        private bool Contact() {
            if (useDcrf) {
                Require(Native.dc_setcpu((int)dev, 0x0C), "Contact slot selection");
                byte n = 0; byte[] b = new byte[256];
                short reset = Native.dc_cpureset((int)dev, out n, b);
                if (reset == 193) { contactPowered = false; return false; }
                Require(reset, "Contact reset");
                contactPowered = true; // Even a malformed ATR needs power-off during cleanup.
                byte[] atr = Apdu.Slice(b, 0, n);
                protocol = ContactAtr.Parse(atr).Protocol;
                // On the tested A133 firmware an empty 0x7D transfer returns 1 when
                // powered, and a different code when down/lost. No APDU bytes are sent.
                // Calibrate only after a valid ATR, never interpret a generic error as "present".
                byte ignored; byte[] probeBuffer = new byte[256];
                short probe = Native.dc_cpuapdusource((int)dev, 0, new byte[0], out ignored, probeBuffer);
                if (probe != 1) throw new LinkException("Unsupported contact presence response: " + probe);
                contactProbeCode = probe;
                Atr = atr; Medium = "Contact"; return true;
            } else {
                short status = Native.IC_Status(dev);
                if (status == 1) return false;
                Require(status, "Contact presence check");
                Require(Native.IC_InitType(dev, 0x0C), "Contact slot selection");
                Require(Native.IC_Down(dev), "Contact power off");
                byte n; byte[] b = new byte[256];
                Require(Native.IC_CpuReset(dev, out n, b), "Contact reset");
                contactPowered = true;
                if (n < 2 || n > 33) throw new LinkException("Invalid contact ATR length");
                protocol = Native.IC_CpuGetProtocol(dev);
                if (protocol != 0 && protocol != 1) throw new LinkException("Invalid contact protocol: " + protocol);
                Atr = Apdu.Slice(b, 0, n); Medium = "Contact"; return true;
            }
        }
        private void StartRfField() {
            if (useDcrf) Require(Native.dc_reset((int)dev, 20), "RF field reset");
            else Require(Native.IC_ResetMifare(dev, 20), "RF field reset");
            rfFieldOn = true; // Cleanup must also switch off a field whose subsequent configuration fails.
            if (useDcrf) Require(Native.dc_config_card((int)dev, (byte)'A'), "RF Type A configuration");
        }
        private bool Rf() {
            // Leave the field on while seeking a card. Repeated resets can prevent a
            // slowly starting NFC token from ever becoming ready.
            if (!rfFieldOn) StartRfField();
            ushort type;
            short request = useDcrf ? Native.dc_request((int)dev, 1, out type) : Native.IC_Request(dev, 1, out type);
            if (request != 0) {
                request = useDcrf ? Native.dc_request((int)dev, 0, out type) : Native.IC_Request(dev, 0, out type);
                if (request != 0) return false;
            }
            uint uid; byte sak;
            Require(useDcrf ? Native.dc_anticoll((int)dev, 0, out uid) : Native.IC_Anticoll(dev, 0, out uid), "RF anticollision CL1");
            Require(useDcrf ? Native.dc_select((int)dev, uid, out sak) : Native.IC_Select(dev, uid, out sak), "RF select CL1");
            if ((sak & 4) != 0) {
                Require(useDcrf ? Native.dc_anticoll2((int)dev, 0, out uid) : Native.IC_Anticoll2(dev, 0, out uid), "RF anticollision CL2");
                Require(useDcrf ? Native.dc_select2((int)dev, uid, out sak) : Native.IC_Select2(dev, uid, out sak), "RF select CL2");
            }
            if ((sak & 4) != 0) throw new LinkException("10-byte RF UID not supported by this SDK adapter");
            if ((sak & 0x20) == 0) throw new LinkException("RF card does not support ISO 14443-4 APDUs");
            byte n; byte[] b = new byte[256];
            Require(useDcrf ? Native.dc_pro_reset((int)dev, out n, b) : Native.IC_Pro_Reset(dev, out n, b), "RF RATS");
            Ats ats = Ats.Parse(Apdu.Slice(b, 0, n));
            isYubiKey = System.Text.Encoding.ASCII.GetString(b, 0, n).IndexOf("YubiKey", StringComparison.Ordinal) >= 0;
            Atr = ats.Atr; rf = new IsoDep(ats, RfRaw, useDcrf ? 248 : 250); rf.StartupPresence = isYubiKey;
            rfActivated.Restart(); Medium = "Rf"; return true;
        }
        public bool Activate(string mode, bool preferContact) {
            bool wasRf = rf != null;
            Atr = new byte[0]; Medium = "None"; rf = null;
            if (wasRf) rfFieldOn = false;
            if (deviceHealth.ElapsedMilliseconds >= 3000) {
                byte[] version = new byte[256];
                Require(useDcrf ? Native.dc_getver((int)dev, version) : Native.IC_ReadVer(dev, version), "USB reader health check");
                deviceHealth.Restart();
            }
            if (mode == "Contact") return Contact();
            if (mode == "Rf") return Rf();
            if (mode != "Auto") throw new ArgumentException("Unknown card mode");
            // A failed/unsupported preferred card must not starve the other occupied slot.
            try { if (preferContact ? Contact() : Rf()) return true; }
            catch (LinkException) {
                Atr = new byte[0]; rf = null;
                if (contactPowered) {
                    Require(useDcrf ? Native.dc_cpudown((int)dev) : Native.IC_Down(dev), "Failed contact activation cleanup");
                    contactPowered = false;
                }
            }
            return preferContact ? Rf() : Contact();
        }
        public void Reset() {
            string medium = Medium;
            if (medium == "Rf") rfFieldOn = false;
            Atr = new byte[0]; rf = null;
            try {
                if (!(medium == "Contact" ? Contact() : medium == "Rf" && Rf()))
                    throw new LinkException("Card missing during reset");
            } catch { Atr = new byte[0]; throw; }
        }
        public void PowerOff() {
            Atr = new byte[0]; rf = null;
            try {
                if (Medium == "Contact" || contactPowered) {
                    contactPowered = false;
                    Require(useDcrf ? Native.dc_cpudown((int)dev) : Native.IC_Down(dev), "Contact power off");
                }
            } finally {
                // Contact may win after RF-first detection already powered an empty RF field.
                if (Medium == "Rf" || rfFieldOn) {
                    rfFieldOn = false;
                    if (useDcrf) Require(Native.dc_reset((int)dev, 0), "RF field off");
                    else Require(Native.IC_ResetMifare(dev, 20), "RF session reset");
                }
            }
        }
        private short ContactProbe() {
            byte n = 0; byte[] b = new byte[256];
            return Native.dc_cpuapdusource((int)dev, 0, new byte[0], out n, b);
        }
        public bool ContactPresent() {
            if (Medium != "Contact") return true;
            if (!useDcrf) return Native.IC_Status(dev) == 0;
            // No live application exists after host OFF, so reset is allowed only here.
            // During an active session presence checks never reset or SELECT the card.
            if (!contactPowered) return Contact();
            if (ContactProbe() == contactProbeCode) return true;
            Thread.Sleep(40);
            if (ContactProbe() == contactProbeCode) return true;
            contactPowered = false;
            return false;
        }
        public bool RfPresent() {
            if (Medium != "Rf") return true;
            // A powered-down RF card still needs idle removal monitoring. Reactivate
            // without exposing it as a new Windows card, then use the same presence path.
            if (rf == null) Reset();
            // Preserve the startup grace even after OFF/ATR/RESET in an existing session.
            if (rfActivated.ElapsedMilliseconds < 400) return true;
            return rf.Present();
        }
        private byte[] ContactRaw(byte[] c) {
            if (useDcrf) {
                // Keep the complete legacy HID message (APDU + 5 framing bytes) <=255.
                // 254-byte APDUs crashed this packaged DLL in an isolated live test;
                // 250-byte transfers were verified. T=1 adds another 4 protocol bytes.
                int limit = protocol == 1 ? 246 : 250;
                if (c.Length > limit) throw new LinkException("Contact SDK length exceeds " + limit);
                byte n = 0; byte[] b = new byte[256];
                short ret = protocol == 1
                    ? Native.dc_cpuapdu((int)dev, (byte)c.Length, c, out n, b)
                    : Native.dc_cpuapdusource((int)dev, (byte)c.Length, c, out n, b);
                Require(ret, "Contact APDU (outcome unknown)");
                if (n < 2) throw new LinkException("Invalid contact response length " + n);
                return Apdu.Slice(b, 0, n);
            }
            if (c.Length > Int16.MaxValue) throw new LinkException("Native send length exceeded");
            byte[] buffer = new byte[65536]; short length;
            Require(Native.IC_CpuApduSourceEXT(dev, checked((short)c.Length), c, out length, buffer), "Contact APDU (outcome unknown)");
            if (length < 2) throw new LinkException("Invalid native response length");
            return Apdu.Slice(buffer, 0, length);
        }
        private byte[] RfRaw(byte[] c, byte timeout) {
            // dcrf32 wraps a frame in six legacy bytes (timeout/length + envelope).
            if (c.Length > (useDcrf ? 249 : 255)) throw new LinkException("RF native send length exceeded");
            byte n; byte[] b = new byte[256];
            short ret = useDcrf
                ? Native.dc_pro_commandsource((int)dev, checked((byte)c.Length), c, out n, b, timeout)
                : Native.IC_Pro_Commandsource(dev, checked((byte)c.Length), c, out n, b, timeout);
            Require(ret, "RF block (outcome unknown)");
            return Apdu.Slice(b, 0, n);
        }
        public byte[] Transmit(byte[] c) {
            if (Atr.Length == 0) throw new LinkException("Card is not powered");
            if (Medium == "Contact") {
                // Do not silently split a signed/chained application command. Reject an
                // unsupported extended form/length before dispatch, preserving the session.
                if (useDcrf && c != null && c.Length > 5 && c[4] == 0) return Apdu.Status(0x67, 0);
                return Apdu.Contact(c, protocol, ContactRaw, useDcrf ? (protocol == 1 ? 246 : 250) : Int16.MaxValue);
            }
            if (rf == null) throw new LinkException("RF card not activated");
            return rf.Transmit(c);
        }
        public void Dispose() {
            if (dev == IntPtr.Zero || (int)dev <= 0) return;
            try { PowerOff(); } catch (IOException) { }
            finally {
                if (useDcrf) Native.dc_exit((int)dev);
                else Native.IC_ExitComm(dev);
                dev = IntPtr.Zero;
            }
        }
    }

    public static class Framing {
        private static void Exact(NetworkStream stream, byte[] b, int count, Stopwatch clock, int deadline) {
            int offset = 0;
            while (offset < count) {
                int remaining = deadline - (int)clock.ElapsedMilliseconds;
                if (remaining <= 0) throw new LinkException("VPCD partial-frame deadline");
                stream.ReadTimeout = remaining;
                int n = stream.Read(b, offset, count - offset);
                if (n == 0) throw new EndOfStreamException("VPCD closed mid-frame");
                offset += n;
            }
        }
        // Called only once data is available. The deadline covers header AND payload.
        public static byte[] Read(NetworkStream stream, int deadline) {
            Stopwatch clock = Stopwatch.StartNew(); byte[] header = new byte[2];
            Exact(stream, header, 2, clock, deadline);
            int count = (header[0] << 8) | header[1];
            if (count == 0) throw new LinkException("Empty VPCD frame");
            byte[] b = new byte[count]; Exact(stream, b, count, clock, deadline); return b;
        }
        public static void Write(NetworkStream stream, byte[] b) {
            if (b == null || b.Length < 1 || b.Length > 65535) throw new LinkException("VPCD response length");
            byte[] packet = new byte[b.Length + 2]; packet[0] = (byte)(b.Length >> 8); packet[1] = (byte)b.Length;
            Array.Copy(b, 0, packet, 2, b.Length); stream.WriteTimeout = 3000;
            stream.Write(packet, 0, packet.Length);
        }
    }

    public sealed class Session {
        public const int RfQuietMs = 400;
        public const int RfIdlePollMs = 200;
        public const int ContactPollMs = 100;
        private readonly ICard card;
        private bool powered = true;
        public Session(ICard card) { this.card = card; }
        public byte[] Handle(byte[] payload) {
            if (payload.Length == 1) {
                switch (payload[0]) {
                    case 0: powered = false; card.PowerOff(); return null;
                    case 1:
                    case 2: powered = false; card.Reset(); powered = true; return null;
                    case 4:
                        // Windows VPCD may request an ATR after powering down, with no ON first.
                        if (!powered) { card.Reset(); powered = true; }
                        if (card.Atr.Length < 2 || card.Atr.Length > 33) throw new LinkException("No current ATR");
                        return (byte[])card.Atr.Clone();
                    default: throw new LinkException("Unknown VPCD control: " + payload[0]);
                }
            }
            if (!powered) throw new LinkException("APDU received while powered off");
            // Exactly one application dispatch. An ambiguous failure disconnects; never replay it.
            return Apdu.Checked(card.Transmit(payload));
        }
        public void Run(TcpClient client, Func<bool> stop, int frameTimeout) {
            NetworkStream stream = client.GetStream();
            Stopwatch contactPoll = Stopwatch.StartNew(), idle = Stopwatch.StartNew(), rfPoll = Stopwatch.StartNew();
            while (!stop()) {
                if (client.Client.Poll(5000, SelectMode.SelectRead)) {
                    if (client.Available == 0) throw new EndOfStreamException("VPCD closed");
                    byte[] payload = Framing.Read(stream, frameTimeout);
                    byte[] response = Handle(payload);
                    if (response != null) Framing.Write(stream, response);
                    // Keep the 400ms quiet period after an APDU/reset; ATR polling must not starve detection.
                    if (payload.Length != 1 || payload[0] != 4) idle.Restart();
                }
                if (contactPoll.ElapsedMilliseconds >= ContactPollMs) {
                    if (!card.ContactPresent()) throw new LinkException("Contact removed");
                    contactPoll.Restart();
                }
                // Startup/business grace and steady polling are separate clocks. Fast idle
                // polls never reduce the initial 400ms grace or interrupt an active APDU.
                if (card.Medium == "Rf" && idle.ElapsedMilliseconds >= RfQuietMs && rfPoll.ElapsedMilliseconds >= RfIdlePollMs && !stream.DataAvailable) {
                    if (!card.RfPresent()) throw new LinkException("RF card removed");
                    rfPoll.Restart();
                }
            }
        }
    }

    public static class Runner {
        private static volatile bool cancel;
        private static void Cancel(object sender, ConsoleCancelEventArgs e) { e.Cancel = true; cancel = true; }
        public static void Run(string driver, string host, int port, string mode, bool preferContact, int runSeconds) {
            Run(driver, host, port, mode, preferContact, runSeconds, 0);
        }
        public static void Run(string driver, string host, int port, string mode, bool preferContact, int runSeconds, int directPort) {
            if (port < 1 || port > 65535 || directPort < 0 || directPort > 65535) throw new ArgumentOutOfRangeException("port");
            IPAddress address;
            if (host == "localhost") address = IPAddress.Loopback;
            else if (!IPAddress.TryParse(host, out address) || !IPAddress.IsLoopback(address))
                throw new ArgumentException("VPCD must use a loopback address");
            if (directPort == port) throw new ArgumentException("Diagnostic port must differ from VPCD");
            bool acquired = false;
            using (Mutex mutex = new Mutex(false, @"Global\ChinaHid.Decard.USB100")) {
                TcpListener directServer = null;
                try {
                    try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) throw new InvalidOperationException("Another DeCard bridge owns this reader");
                    Decard.LoadDriver(driver); cancel = false; Console.CancelKeyPress += Cancel;
                    Stopwatch lifetime = Stopwatch.StartNew();
                    Func<bool> stop = delegate { return cancel || (runSeconds > 0 && lifetime.Elapsed.TotalSeconds >= runSeconds); };
                    Console.WriteLine("DeCard mode=" + mode + ", priority=" + (preferContact ? "Contact" : "Rf") + ", VPCD=" + address + ":" + port);
                    Console.WriteLine("RF startup/after-APDU grace 400ms; idle polling 200ms; removal retry 40ms. APDU payload logging is disabled.");
                    if (directPort != 0) {
                        directServer = new TcpListener(IPAddress.Loopback, directPort); directServer.Start();
                        Console.WriteLine("Exclusive diagnostic channel 127.0.0.1:" + directPort + "; Windows VPCD is disconnected in this mode.");
                    }
                    bool readerAnnounced = mode == "Rf";
                    string lastError = null; Stopwatch errorClock = Stopwatch.StartNew();
                    while (!stop()) {
                        try {
                            using (Decard card = new Decard()) {
                                Console.WriteLine("Reader backend=" + card.Backend);
                                if (!readerAnnounced) { card.Beep(); readerAnnounced = true; }
                                while (!stop() && !card.Activate(mode, preferContact)) Thread.Sleep(50);
                                if (stop()) break;
                                // Signal card detection immediately; do not wait for the host connection.
                                card.Beep();
                                TcpClient connection;
                                if (directServer != null) {
                                    while (!stop() && !directServer.Pending()) Thread.Sleep(10);
                                    if (stop()) break;
                                    connection = directServer.AcceptTcpClient();
                                } else {
                                    connection = new TcpClient(address.AddressFamily);
                                    try {
                                        IAsyncResult pending = connection.BeginConnect(address, port, null, null);
                                        using (WaitHandle wait = pending.AsyncWaitHandle) {
                                            if (!wait.WaitOne(3000)) throw new LinkException("VPCD connection deadline");
                                            connection.EndConnect(pending);
                                        }
                                    } catch { connection.Close(); throw; }
                                }
                                using (TcpClient client = connection) {
                                    client.NoDelay = true;
                                    Console.WriteLine("Connected medium=" + card.Medium + " ATR=" + BitConverter.ToString(card.Atr));
                                    new Session(card).Run(client, stop, 3000);
                                }
                            }
                        } catch (IOException ex) {
                            if (lastError != ex.Message || errorClock.ElapsedMilliseconds >= 10000) {
                                Console.WriteLine("Session ended: " + ex.Message); lastError = ex.Message; errorClock.Restart();
                            }
                        } catch (SocketException ex) {
                            if (lastError != ex.Message || errorClock.ElapsedMilliseconds >= 10000) {
                                Console.WriteLine("VPCD unavailable: " + ex.Message); lastError = ex.Message; errorClock.Restart();
                            }
                        }
                        if (!stop()) Thread.Sleep(100);
                    }
                } finally {
                    if (directServer != null) directServer.Stop();
                    Console.CancelKeyPress -= Cancel;
                    if (acquired) mutex.ReleaseMutex();
                }
            }
        }
    }
}
