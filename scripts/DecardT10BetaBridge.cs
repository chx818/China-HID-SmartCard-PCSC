using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;

namespace ChinaHid.T10Beta {
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
            return (byte)((cla & 0x80) != 0 ? (cla & 3) : (cla & 0xEF));
        }
        public static byte[] Contact(byte[] command, int protocol, Func<byte[], byte[]> exchange) {
            if (!Valid(command)) return Status(0x67, 0);
            if (command.Length > Int16.MaxValue) return Status(0x67, 0);
            if (protocol == 1) {
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
            if (automatic && case2 && c[1] == 0xC0 && le > 128) c[4] = 128;
            byte[] r = Checked(exchange(c));
            if (automatic && case2 && r.Length == 2 && r[0] == 0x6C) {
                int corrected = r[1] == 0 ? 256 : r[1];
                if (c[1] == 0xC0 && corrected > 128) return r;
                c = (byte[])c.Clone(); c[4] = r[1]; le = corrected;
                r = Checked(exchange(c));
            }
            if (!automatic) return r;
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

    public sealed class Ats {
        public byte[] Atr { get; private set; }
        public int FrameSize { get; private set; }
        public static Ats Parse(byte[] ats) {
            if (ats == null || ats.Length < 1 || ats.Length > 20 || ats[0] != ats.Length)
                throw new LinkException("Invalid ATS length");
            int offset = 1, fsci = 2;
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
        public int DeadlineMs = 0;
        public IsoDep(Ats ats, Func<byte[], byte, byte[]> exchange) {
            this.exchange = exchange;
            chunk = Math.Min(250, ats.FrameSize - 3);
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
        public bool Present() {
            Stopwatch clock = Stopwatch.StartNew(); int blocks = 0, wtx = 0;
            byte[] frame = new byte[] { (byte)(0x02 | block) };
            byte[] r;
            try { r = Exchange(frame, clock, ref blocks, ref wtx, true); }
            catch (IOException) {
                Thread.Sleep(40);
                clock.Restart(); blocks = 0; wtx = 0;
                try { r = Exchange(frame, clock, ref blocks, ref wtx, true); }
                catch (IOException) { return false; }
            }
            Receive(r, clock, ref blocks, ref wtx, true);
            StartupPresence = false;
            return true;
        }
    }

    internal static class Native {
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        internal static extern IntPtr LoadLibraryEx(string file, IntPtr reserved, uint flags);

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
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_setcpu(int d, byte ctype);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_cpureset(int d, out byte rlen, [Out] byte[] rdata);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_cpudown(int d);
        [DllImport("dcrf32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short dc_cpuapdusource(int d, byte slen, byte[] sdata, out byte rlen, [Out] byte[] rdata);
    }

    public sealed class DecardT10Card : IDisposable {
        private int dev;
        private static bool rfLoaded;
        private static string loadedDirectory;
        private bool rfFieldOn;
        private Stopwatch rfActivated = new Stopwatch();
        private Stopwatch deviceHealth = Stopwatch.StartNew();
        private bool isYubiKey;
        private IsoDep rf;
        private int protocol; // 0 for T=0, 1 for T=1
        public byte[] Atr { get; private set; }
        public string Medium { get; private set; }
        public int Handle { get { return dev; } }

        public static void LoadDriver(string directory) {
            if (IntPtr.Size != 4) throw new InvalidOperationException("DeCard T10 driver requires x86 PowerShell");
            directory = Path.GetFullPath(directory);
            if (loadedDirectory != null) return;
            string rfPath = Path.Combine(directory, "dcrf32.dll");
            if (File.Exists(rfPath)) {
                rfLoaded = Native.LoadLibraryEx(rfPath, IntPtr.Zero, 0x100 | 0x800) != IntPtr.Zero;
                if (!rfLoaded) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Cannot load packaged dcrf32.dll");
            } else {
                throw new FileNotFoundException("dcrf32.dll not found", rfPath);
            }
            loadedDirectory = directory;
        }

        public DecardT10Card() {
            Atr = new byte[0]; Medium = "None";
            if (loadedDirectory == null) throw new InvalidOperationException("LoadDriver must succeed before opening a reader");
            dev = Native.dc_init(100, 115200);
            if (dev <= 0) throw new LinkException("Cannot open DeCard T10 reader via dcrf32.dll: " + dev);
        }

        public void Beep() {
            if (dev > 0) Native.dc_beep(dev, 10);
        }

        private static void Require(short code, string operation) {
            if (code != 0) throw new LinkException(operation + " failed: " + code);
        }

        private static int ParseProtocolFromAtr(byte[] atr) {
            if (atr == null || atr.Length < 2) return 0;
            byte t0 = atr[1];
            int offset = 2;
            if ((t0 & 0x10) != 0) offset++;
            if ((t0 & 0x20) != 0) offset++;
            if ((t0 & 0x40) != 0) offset++;
            if ((t0 & 0x80) != 0 && offset < atr.Length) {
                return (atr[offset] & 0x0F) == 1 ? 1 : 0;
            }
            return 0;
        }

        private bool Contact() {
            // Select Main Contact Slot 0x0C
            short setRes = Native.dc_setcpu(dev, 0x0C);
            if (setRes != 0) return false;

            byte rlen; byte[] b = new byte[256];
            short rst = Native.dc_cpureset(dev, out rlen, b);
            if (rst != 0 || rlen < 2 || rlen > 33) return false;

            protocol = ParseProtocolFromAtr(b);
            Atr = Apdu.Slice(b, 0, rlen);
            Medium = "Contact";
            return true;
        }

        private void StartRfField() {
            Require(Native.dc_reset(dev, 20), "RF field reset");
            rfFieldOn = true;
            Require(Native.dc_config_card(dev, (byte)'A'), "RF Type A configuration");
        }

        private bool Rf() {
            if (!rfFieldOn) StartRfField();
            ushort type;
            short request = Native.dc_request(dev, 1, out type);
            if (request != 0) {
                request = Native.dc_request(dev, 0, out type);
                if (request != 0) return false;
            }
            uint uid; byte sak;
            Require(Native.dc_anticoll(dev, 0, out uid), "RF anticollision CL1");
            Require(Native.dc_select(dev, uid, out sak), "RF select CL1");
            if ((sak & 4) != 0) {
                Require(Native.dc_anticoll2(dev, 0, out uid), "RF anticollision CL2");
                Require(Native.dc_select2(dev, uid, out sak), "RF select CL2");
            }
            if ((sak & 0x20) == 0) return false; // Non-ISO-DEP
            byte len; byte[] b = new byte[256];
            Require(Native.dc_pro_reset(dev, out len, b), "RF RATS");
            Ats ats = Ats.Parse(Apdu.Slice(b, 0, len));
            isYubiKey = (type == 0x0004 && (ats.Atr.Length == 23 || ats.Atr.Length == 14));
            rf = new IsoDep(ats, RfRaw) { StartupPresence = isYubiKey };
            Atr = ats.Atr; Medium = "Rf";
            rfActivated.Restart();
            return true;
        }

        public bool Activate(string mode, bool preferContact) {
            if (deviceHealth.ElapsedMilliseconds >= 3000) {
                byte[] version = new byte[256];
                Require(Native.dc_getver(dev, version), "USB reader health check");
                deviceHealth.Restart();
            }
            if (mode == "Contact") return Contact();
            if (mode == "Rf") return Rf();
            if (mode != "Auto") throw new ArgumentException("Unknown card mode");
            try { if (preferContact ? Contact() : Rf()) return true; }
            catch (LinkException) { Atr = new byte[0]; rf = null; }
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
            if (Medium == "Contact") {
                Native.dc_cpudown(dev);
            } else if (Medium == "Rf" || rfFieldOn) {
                Native.dc_reset(dev, 0);
                rfFieldOn = false;
            }
        }

        public bool ContactPresent() {
            if (Medium != "Contact") return true;
            return true; // Active APDU failure triggers removal immediately.
        }

        public bool RfPresent() {
            if (Medium != "Rf") return true;
            if (rf == null) Reset();
            if (rfActivated.ElapsedMilliseconds < 400) return true;
            return rf.Present();
        }

        private byte[] ContactRaw(byte[] c) {
            if (c.Length > 255) throw new LinkException("Contact send length exceeds hardware buffer");
            byte n; byte[] b = new byte[256];
            short ret = Native.dc_cpuapdusource(dev, (byte)c.Length, c, out n, b);
            if (ret != 0) throw new LinkException("Contact APDU failed: " + ret);
            if (n < 2) throw new LinkException("Invalid contact response length: " + n);
            return Apdu.Slice(b, 0, n);
        }

        private byte[] RfRaw(byte[] c, byte timeout) {
            if (c.Length > 255) throw new LinkException("RF native send length exceeded");
            byte n; byte[] b = new byte[256];
            short ret = Native.dc_pro_commandsource(dev, (byte)c.Length, c, out n, b, timeout);
            Require(ret, "RF block exchange");
            return Apdu.Slice(b, 0, n);
        }

        public byte[] Transmit(byte[] c) {
            if (Atr.Length == 0) throw new LinkException("Card is not powered");
            if (Medium == "Contact") return Apdu.Contact(c, protocol, ContactRaw);
            if (rf == null) throw new LinkException("RF card not activated");
            return rf.Transmit(c);
        }

        public void Dispose() {
            if (dev > 0) {
                try { PowerOff(); } catch { }
                Native.dc_exit(dev);
                dev = 0;
            }
        }
    }

    public static class Framing {
        public static byte[] Read(NetworkStream stream, int timeoutMs) {
            byte[] header = new byte[2]; int read = 0;
            Stopwatch sw = Stopwatch.StartNew();
            while (read < 2) {
                if (stream.DataAvailable) {
                    int chunk = stream.Read(header, read, 2 - read);
                    if (chunk == 0) throw new EndOfStreamException();
                    read += chunk;
                } else {
                    if (sw.ElapsedMilliseconds > timeoutMs) throw new TimeoutException("Header read timed out");
                    Thread.Sleep(5);
                }
            }
            int length = (header[0] << 8) | header[1];
            if (length == 0 || length > 65535) throw new LinkException("Invalid VPCD frame length: " + length);
            byte[] payload = new byte[length]; read = 0; sw.Restart();
            while (read < length) {
                if (stream.DataAvailable) {
                    int chunk = stream.Read(payload, read, length - read);
                    if (chunk == 0) throw new EndOfStreamException();
                    read += chunk;
                } else {
                    if (sw.ElapsedMilliseconds > timeoutMs) throw new TimeoutException("Payload read timed out");
                    Thread.Sleep(5);
                }
            }
            return payload;
        }
        public static void Write(NetworkStream stream, byte[] payload) {
            if (payload == null || payload.Length == 0 || payload.Length > 65535)
                throw new LinkException("Invalid payload length");
            byte[] frame = new byte[2 + payload.Length];
            frame[0] = (byte)(payload.Length >> 8); frame[1] = (byte)payload.Length;
            Array.Copy(payload, 0, frame, 2, payload.Length);
            stream.Write(frame, 0, frame.Length);
            stream.Flush();
        }
    }

    public sealed class Session {
        private readonly DecardT10Card card;
        private bool powered = true;
        public int ContactPollMs = 250;
        public int RfQuietMs = 400;
        public int RfIdlePollMs = 200;
        public Session(DecardT10Card card) { this.card = card; }
        private byte[] Handle(byte[] payload) {
            if (payload == null || payload.Length == 0) throw new LinkException("Empty VPCD control");
            if (payload.Length == 1) {
                switch (payload[0]) {
                    case 0: powered = false; card.PowerOff(); return null;
                    case 1:
                    case 2: powered = false; card.Reset(); powered = true; return null;
                    case 4:
                        if (!powered) { card.Reset(); powered = true; }
                        if (card.Atr.Length < 2 || card.Atr.Length > 33) throw new LinkException("No current ATR");
                        return (byte[])card.Atr.Clone();
                    default: throw new LinkException("Unknown VPCD control: " + payload[0]);
                }
            }
            if (!powered) throw new LinkException("APDU received while powered off");
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
                    if (payload.Length != 1 || payload[0] != 4) idle.Restart();
                }
                if (contactPoll.ElapsedMilliseconds >= ContactPollMs) {
                    if (!card.ContactPresent()) throw new LinkException("Contact removed");
                    contactPoll.Restart();
                }
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

        public static void Run(string driver, string host, int port, string mode, bool preferContact, int runSeconds, int directPort) {
            if (port < 1 || port > 65535 || directPort < 0 || directPort > 65535) throw new ArgumentOutOfRangeException("port");
            IPAddress address;
            if (host == "localhost") address = IPAddress.Loopback;
            else if (!IPAddress.TryParse(host, out address) || !IPAddress.IsLoopback(address))
                throw new ArgumentException("VPCD must use a loopback address");
            if (directPort == port) throw new ArgumentException("Diagnostic port must differ from VPCD");
            
            bool acquired = false;
            using (Mutex mutex = new Mutex(false, @"Global\ChinaHid.Decard.T10Beta")) {
                TcpListener directServer = null;
                try {
                    try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) throw new InvalidOperationException("Another DeCard T10 Beta bridge owns this reader");
                    DecardT10Card.LoadDriver(driver);
                    cancel = false;
                    Console.CancelKeyPress += Cancel;
                    Stopwatch lifetime = Stopwatch.StartNew();
                    Func<bool> stop = delegate { return cancel || (runSeconds > 0 && lifetime.Elapsed.TotalSeconds >= runSeconds); };
                    
                    Console.WriteLine("=== DeCard T10 Beta Bridge (PID A133 Dual Interface) ===");
                    Console.WriteLine("Mode: " + mode + " | Priority: " + (preferContact ? "ContactFirst" : "RfFirst") + " | VPCD: " + address + ":" + port);
                    Console.WriteLine("Contact Slot: 0x0C (dcrf32.dll) | RF: ISO 14443-4 T=CL with 400ms startup grace");
                    if (directPort != 0) {
                        directServer = new TcpListener(IPAddress.Loopback, directPort); directServer.Start();
                        Console.WriteLine("Diagnostic channel listening on 127.0.0.1:" + directPort);
                    }

                    bool readerBeeped = false;
                    string lastError = null; Stopwatch errorClock = Stopwatch.StartNew();

                    while (!stop()) {
                        try {
                            using (DecardT10Card card = new DecardT10Card()) {
                                if (!readerBeeped) { card.Beep(); readerBeeped = true; }
                                
                                // Fast polling loop (50ms)
                                while (!stop() && !card.Activate(mode, preferContact)) Thread.Sleep(50);
                                if (stop()) break;

                                // Immediate physical beep when card detected
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
                                            if (!wait.WaitOne(3000)) throw new LinkException("VPCD connection timeout");
                                            connection.EndConnect(pending);
                                        }
                                    } catch { connection.Close(); throw; }
                                }

                                using (TcpClient client = connection) {
                                    client.NoDelay = true;
                                    Console.WriteLine(string.Format("[{0:HH:mm:ss}] Active Medium: {1} | ATR: {2}", DateTime.Now, card.Medium, BitConverter.ToString(card.Atr)));
                                    new Session(card).Run(client, stop, 3000);
                                }
                            }
                        } catch (IOException ex) {
                            if (lastError != ex.Message || errorClock.ElapsedMilliseconds >= 10000) {
                                Console.WriteLine(string.Format("[{0:HH:mm:ss}] Session ended: {1}", DateTime.Now, ex.Message));
                                lastError = ex.Message; errorClock.Restart();
                            }
                        } catch (SocketException ex) {
                            if (lastError != ex.Message || errorClock.ElapsedMilliseconds >= 10000) {
                                Console.WriteLine(string.Format("[{0:HH:mm:ss}] VPCD unavailable: {1}", DateTime.Now, ex.Message));
                                lastError = ex.Message; errorClock.Restart();
                            }
                        }
                        if (!stop()) Thread.Sleep(50);
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
