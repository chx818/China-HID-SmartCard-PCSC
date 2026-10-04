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
            // T6 T=0 GET RESPONSE has a 256-byte receive boundary: request <=128 per TPDU.
            if (automatic && case2 && c[1] == 0xC0 && le > 128) c[4] = 128;
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
        public int MaxBlocks = 16384;
        public int MaxWtx = 4096;
        // Long operations that keep responding with WTX must not be cut off at 30 seconds.
        // The SDK retains its per-exchange timeout; optional total deadlines are opt-in.
        public int DeadlineMs = 0;
        public IsoDep(Ats ats, Func<byte[], byte, byte[]> exchange) {
            this.exchange = exchange;
            // FSC includes PCB and CRC. The DLL strips CRC and has a one-byte length.
            chunk = Math.Min(250, ats.FrameSize - 3);
        }
        private byte[] Exchange(byte[] frame, Stopwatch clock, ref int blocks, ref int wtx, bool presence) {
            byte initialTimeout = presence ? (byte)2 : (byte)10;
            byte timeout = initialTimeout;
            int deadline = presence ? 1500 : DeadlineMs;
            while (true) {
                if (++blocks > (presence ? 16 : MaxBlocks) || (deadline > 0 && clock.ElapsedMilliseconds >= deadline))
                    throw new LinkException("ISO-DEP exchange deadline/block limit");
                byte[] r = exchange(frame, timeout);
                if (deadline > 0 && clock.ElapsedMilliseconds >= deadline) throw new LinkException("ISO-DEP exchange deadline");
                if (r == null || r.Length < 1 || r.Length > 255) throw new LinkException("RF exchange failed; execution outcome unknown");
                if (r[0] != 0xF2) return r;
                if (r.Length != 2 || r[1] < 1 || r[1] > 59 || ++wtx > (presence ? 4 : MaxWtx))
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
            return Receive(r, clock, ref blocks, ref wtx, false);
        }
        private byte[] Receive(byte[] r, Stopwatch clock, ref int blocks, ref int wtx, bool presence) {
            using (MemoryStream result = new MemoryStream()) {
                while (true) {
                    byte pcb = r[0];
                    // Only I-blocks without CID/NAD are negotiated. Never expose control frames as APDU data.
                    if ((pcb & 0xEE) != 0x02 || (pcb & 1) != block)
                        throw new LinkException("Unexpected RF block type/sequence");
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
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern IntPtr IC_InitCommAdvanced(short port);
        [DllImport("dcic32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern short IC_ExitComm(IntPtr d);
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
    }

    public sealed class Decard : ICard {
        private IntPtr dev;
        private IsoDep rf;
        private int protocol;
        public byte[] Atr { get; private set; }
        public string Medium { get; private set; }
        public static void LoadDriver(string directory) {
            string path = Path.GetFullPath(Path.Combine(directory, "dcic32.dll"));
            if (!File.Exists(path)) throw new FileNotFoundException("Missing vendor driver", path);
            if (IntPtr.Size != 4) throw new InvalidOperationException("dcic32.dll requires x86 PowerShell");
            // Search the absolute DLL's directory and System32, never the working directory/PATH.
            if (Native.LoadLibraryEx(path, IntPtr.Zero, 0x00000100 | 0x00000800) == IntPtr.Zero)
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Cannot load dcic32.dll");
        }
        public Decard() {
            Atr = new byte[0]; Medium = "None";
            dev = Native.IC_InitCommAdvanced(100);
            if (dev == IntPtr.Zero || dev == new IntPtr(-1)) { dev = IntPtr.Zero; throw new LinkException("Cannot open T6 USB reader"); }
        }
        private static void Require(short code, string operation) {
            if (code != 0) throw new LinkException(operation + " failed: " + code);
        }
        private bool Contact() {
            short status = Native.IC_Status(dev);
            if (status == 1) return false;
            Require(status, "Contact presence check");
            Require(Native.IC_InitType(dev, 0x0C), "Contact slot selection");
            Require(Native.IC_Down(dev), "Contact power off");
            byte n; byte[] b = new byte[256];
            Require(Native.IC_CpuReset(dev, out n, b), "Contact reset");
            if (n < 2 || n > 33) throw new LinkException("Invalid contact ATR length");
            protocol = Native.IC_CpuGetProtocol(dev);
            if (protocol != 0 && protocol != 1) throw new LinkException("Invalid contact protocol: " + protocol);
            Atr = Apdu.Slice(b, 0, n); Medium = "Contact"; return true;
        }
        private bool Rf() {
            Require(Native.IC_ResetMifare(dev, 20), "RF field reset");
            ushort type;
            if (Native.IC_Request(dev, 1, out type) != 0 && Native.IC_Request(dev, 0, out type) != 0) return false;
            uint uid; byte sak;
            Require(Native.IC_Anticoll(dev, 0, out uid), "RF anticollision CL1");
            Require(Native.IC_Select(dev, uid, out sak), "RF select CL1");
            if ((sak & 4) != 0) {
                Require(Native.IC_Anticoll2(dev, 0, out uid), "RF anticollision CL2");
                Require(Native.IC_Select2(dev, uid, out sak), "RF select CL2");
            }
            if ((sak & 4) != 0) throw new LinkException("10-byte RF UID not supported by this SDK adapter");
            if ((sak & 0x20) == 0) throw new LinkException("RF card does not support ISO 14443-4 APDUs");
            byte n; byte[] b = new byte[256];
            Require(Native.IC_Pro_Reset(dev, out n, b), "RF RATS");
            Ats ats = Ats.Parse(Apdu.Slice(b, 0, n));
            Atr = ats.Atr; rf = new IsoDep(ats, RfRaw); Medium = "Rf"; return true;
        }
        public bool Activate(string mode, bool preferContact) {
            Atr = new byte[0]; Medium = "None"; rf = null;
            if (mode == "Contact") return Contact();
            if (mode == "Rf") return Rf();
            if (mode != "Auto") throw new ArgumentException("Unknown card mode");
            // A failed/unsupported preferred card must not starve the other occupied slot.
            try { if (preferContact ? Contact() : Rf()) return true; }
            catch (LinkException) { Atr = new byte[0]; rf = null; }
            return preferContact ? Rf() : Contact();
        }
        public void Reset() {
            string medium = Medium;
            Atr = new byte[0]; rf = null;
            try {
                if (!(medium == "Contact" ? Contact() : medium == "Rf" && Rf()))
                    throw new LinkException("Card missing during reset");
            } catch { Atr = new byte[0]; throw; }
        }
        public void PowerOff() {
            Atr = new byte[0]; rf = null;
            if (Medium == "Contact") Require(Native.IC_Down(dev), "Contact power off");
            else if (Medium == "Rf") Require(Native.IC_ResetMifare(dev, 20), "RF session reset");
        }
        public bool ContactPresent() { return Medium != "Contact" || Native.IC_Status(dev) == 0; }
        public bool RfPresent() {
            if (Medium != "Rf") return true;
            // A powered-down RF card still needs idle removal monitoring. Reactivate
            // without exposing it as a new Windows card, then use the same presence path.
            if (rf == null) Reset();
            return rf.Present();
        }
        private byte[] ContactRaw(byte[] c) {
            if (c.Length > Int16.MaxValue) throw new LinkException("Native send length exceeded");
            // SDK lacks a receive capacity argument. Reserve its full 16-bit output range.
            byte[] b = new byte[65536]; short n;
            Require(Native.IC_CpuApduSourceEXT(dev, checked((short)c.Length), c, out n, b), "Contact APDU (outcome unknown)");
            if (n < 2) throw new LinkException("Invalid native response length");
            return Apdu.Slice(b, 0, n);
        }
        private byte[] RfRaw(byte[] c, byte timeout) {
            if (c.Length > 255) throw new LinkException("RF native send length exceeded");
            byte n; byte[] b = new byte[256];
            Require(Native.IC_Pro_Commandsource(dev, checked((byte)c.Length), c, out n, b, timeout), "RF block (outcome unknown)");
            return Apdu.Slice(b, 0, n);
        }
        public byte[] Transmit(byte[] c) {
            if (Atr.Length == 0) throw new LinkException("Card is not powered");
            if (Medium == "Contact") return Apdu.Contact(c, protocol, ContactRaw);
            if (rf == null) throw new LinkException("RF card not activated");
            return rf.Transmit(c);
        }
        public void Dispose() {
            if (dev == IntPtr.Zero) return;
            try { PowerOff(); } catch (IOException) { }
            finally { Native.IC_ExitComm(dev); dev = IntPtr.Zero; }
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
            Stopwatch contactPoll = Stopwatch.StartNew(), idle = Stopwatch.StartNew();
            while (!stop()) {
                // Drain host requests before probing. Receive a complete frame and finish
                // its complete APDU/WTX/chaining operation on this same thread.
                if (client.Client.Poll(10000, SelectMode.SelectRead)) {
                    if (client.Available == 0) throw new EndOfStreamException("VPCD closed");
                    byte[] payload = Framing.Read(stream, frameTimeout);
                    byte[] response = Handle(payload);
                    if (response != null) Framing.Write(stream, response);
                    // Repeated ATR polling by Windows must not starve presence checks.
                    if (payload.Length != 1 || payload[0] != 4) idle.Restart();
                }
                if (contactPoll.ElapsedMilliseconds >= 250) {
                    if (!card.ContactPresent()) throw new LinkException("Contact removed");
                    contactPoll.Restart();
                }
                if (card.Medium == "Rf" && idle.ElapsedMilliseconds >= 400 && !stream.DataAvailable) {
                    if (!card.RfPresent()) throw new LinkException("RF card removed");
                    idle.Restart();
                }
            }
        }
    }

    public static class Runner {
        private static volatile bool cancel;
        private static void Cancel(object sender, ConsoleCancelEventArgs e) { e.Cancel = true; cancel = true; }
        public static void Run(string driver, string host, int port, string mode, bool preferContact, int runSeconds) {
            if (port < 1 || port > 65535) throw new ArgumentOutOfRangeException("port");
            IPAddress address;
            if (host == "localhost") address = IPAddress.Loopback;
            else if (!IPAddress.TryParse(host, out address) || !IPAddress.IsLoopback(address))
                throw new ArgumentException("VPCD must use a loopback address (transport is unauthenticated)");
            bool acquired = false;
            using (Mutex mutex = new Mutex(false, @"Global\ChinaHid.Decard.USB100")) {
                try {
                    try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) throw new InvalidOperationException("Another DeCard bridge owns this reader");
                    Decard.LoadDriver(driver); cancel = false; Console.CancelKeyPress += Cancel;
                    Stopwatch lifetime = Stopwatch.StartNew();
                    Func<bool> stop = delegate { return cancel || (runSeconds > 0 && lifetime.Elapsed.TotalSeconds >= runSeconds); };
                    Console.WriteLine("DeCard mode=" + mode + ", priority=" + (preferContact ? "Contact" : "Rf") + ", VPCD=" + address + ":" + port);
                    Console.WriteLine("Single virtual slot. Contact polling 250ms; RF idle polling 400ms with 40ms retry. APDU payload logging is disabled.");
                    string lastError = null; Stopwatch errorClock = Stopwatch.StartNew();
                    while (!stop()) {
                        try {
                            using (Decard card = new Decard()) {
                                bool activated = false;
                                // Periodically reopen even if a removed USB device reports "no card".
                                for (int attempt = 0; attempt < 4 && !stop(); attempt++) {
                                    if (card.Activate(mode, preferContact)) { activated = true; break; }
                                    Thread.Sleep(250);
                                }
                                if (stop()) break;
                                if (!activated) { Thread.Sleep(250); continue; }
                                using (TcpClient client = new TcpClient(address.AddressFamily)) {
                                    client.NoDelay = true;
                                    IAsyncResult connection = client.BeginConnect(address, port, null, null);
                                    using (WaitHandle wait = connection.AsyncWaitHandle) {
                                        if (!wait.WaitOne(3000)) throw new LinkException("VPCD connection deadline");
                                        client.EndConnect(connection);
                                    }
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
                        if (!stop()) Thread.Sleep(500);
                    }
                } finally {
                    Console.CancelKeyPress -= Cancel;
                    if (acquired) mutex.ReleaseMutex();
                }
            }
        }
    }
}

