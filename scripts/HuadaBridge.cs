using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;
using System.Text;
using System.Collections.Generic;
using System.Security.Cryptography;

namespace ChinaHid {
    public sealed class LinkException : IOException {
        public LinkException(string message) : base(message) { }
    }
    public sealed class Command {
        public byte[] Bytes, Data;
        public int Le; // -1 absent; 65536 represents extended Le=0000.
        public bool Extended;
        public static Command Parse(byte[] c) {
            if (c == null || c.Length < 4 || c.Length > 65535) return null;
            Command r = new Command { Bytes = (byte[])c.Clone(), Data = new byte[0], Le = -1 };
            if (c.Length == 4) return r;
            if (c.Length == 5) { r.Le = c[4] == 0 ? 256 : c[4]; return r; }
            int offset, count;
            if (c[4] != 0) {
                offset = 5; count = c[4];
                if (c.Length != 5 + count && c.Length != 6 + count) return null;
                if (c.Length == 6 + count) r.Le = c[c.Length - 1] == 0 ? 256 : c[c.Length - 1];
            } else {
                if (c.Length < 7) return null;
                r.Extended = true; offset = 7; count = (c[5] << 8) | c[6];
                if (c.Length == 7) { r.Le = count == 0 ? 65536 : count; return r; }
                if (count == 0 || (c.Length != count + 7 && c.Length != count + 9)) return null;
                if (c.Length == count + 9) { int le = (c[c.Length - 2] << 8) | c[c.Length - 1]; r.Le = le == 0 ? 65536 : le; }
            }
            r.Data = Apdu.Slice(c, offset, count); return r;
        }
    }
    public static class Apdu {
        public const int NativeLimit = 261;
        public const int CtapChunkData = 48; // Qualified on HD-100; larger CTAP frames corrupted a long response.
        public static byte[] Slice(byte[] b, int start, int count) { byte[] r = new byte[count]; Array.Copy(b, start, r, 0, count); return r; }
        public static byte[] Status(byte sw1, byte sw2) { return new byte[] { sw1, sw2 }; }
        public static bool Valid(byte[] c) { return Command.Parse(c) != null; }
        public static byte[] Checked(byte[] r) {
            if (r == null || r.Length < 2 || r.Length > 65535) throw new LinkException("Invalid R-APDU; execution outcome unknown");
            return r;
        }
        public static bool Protected(byte cla) { return (cla & 0x80) != 0 ? (cla & 0x0C) != 0 : (cla & ((cla & 0x40) != 0 ? 0x20 : 0x0C)) != 0; }
        public static byte[] Short(Command c, byte cla, byte[] data, int le) {
            int n = 4 + (data.Length > 0 ? 1 + data.Length : 0) + (le >= 0 ? 1 : 0);
            byte[] wire = new byte[n]; Array.Copy(c.Bytes, wire, 4); wire[0] = cla;
            if (data.Length > 0) { wire[4] = (byte)data.Length; Array.Copy(data, 0, wire, 5, data.Length); }
            if (le >= 0) wire[n - 1] = (byte)(le == 256 ? 0 : le);
            return wire;
        }
        public static byte[] TransmitRf(Func<byte[], byte[]> raw, byte[] command) { return Rf(raw, command, false); }
        public static byte[] Rf(Func<byte[], byte[]> raw, byte[] command, bool selectedFido) {
            Command c = Command.Parse(command);
            if (c == null) return Status(0x67, 0);
            bool ctap = selectedFido && command[0] == 0x80 && command[1] == 0x10 && (command[2] == 0 || command[2] == 0x80) && command[3] == 0 && c.Data.Length > 0;
            if (!c.Extended && (!ctap || c.Data.Length <= CtapChunkData)) return Checked(raw(command));
            // Only CTAP's specified NFC chaining; never blind CLA edits on GP/MAC/write commands.
            // Reframe large short CTAP commands too: length<=261 prevents stack overflow,
            // but does not prevent the SDK/firmware's long-response failure for Lc=240.
            if (!ctap) return Status(0x67, 0);
            int offset = 0;
            while (offset < c.Data.Length) {
                int count = Math.Min(CtapChunkData, c.Data.Length - offset); bool last = offset + count == c.Data.Length;
                byte[] frame = Short(c, last ? (byte)0x80 : (byte)0x90, Slice(c.Data, offset, count), last && c.Le >= 0 ? Math.Min(c.Le, 256) : -1);
                byte[] r = Checked(raw(frame));
                if (!last && (r.Length != 2 || r[0] != 0x90 || r[1] != 0)) return r;
                if (last) return r; // Client owns GET RESPONSE and receive capacity.
                offset += count;
            }
            throw new LinkException("Empty CTAP command");
        }
        public static byte[] Contact(Func<byte[], byte[]> raw, byte[] command, int protocol) { return Contact(raw,command,protocol,true); }
        public static byte[] Contact(Func<byte[], byte[]> raw, byte[] command, int protocol, bool correctCase2Length) {
            Command c = Command.Parse(command);
            if (c == null || c.Extended) return Status(0x67, 0);
            if (protocol == 1) return Checked(raw(command));
            if (protocol != 0) throw new LinkException("Unknown contact protocol");
            byte[] wire = (byte[])command.Clone();
            if (wire.Length == 4) { wire = new byte[5]; Array.Copy(command, wire, 4); }
            else if (c.Data.Length > 0 && c.Le >= 0) wire = Slice(wire, 0, wire.Length - 1);
            byte[] r = Checked(raw(wire));
            if (correctCase2Length && command.Length == 5 && !Protected(command[0]) && r.Length == 2 && r[0] == 0x6C) {
                wire = (byte[])wire.Clone(); wire[4] = r[1]; r = Checked(raw(wire));
            }
            return r; // Preserve 61xx; no hidden unprotected continuation.
        }
        public static byte[] TransmitWithChaining(Func<byte[], byte[]> raw, byte[] command) { return Contact(raw, command, 0); }
    }
    public sealed class PublicReads {
        private string selected;
        public void Clear() { selected = null; }
        private static string Target(Command c) {
            if (c.Bytes[0] != 0 || c.Bytes[1] != 0xA4 || c.Bytes[2] != 4 || (c.Bytes[3] != 0 && c.Bytes[3] != 0x0C)) return null;
            string aid = BitConverter.ToString(c.Data).Replace("-", "");
            if (c.Data.Length >= 6 && c.Data.Length <= 16 && aid.StartsWith("D27600012401",StringComparison.Ordinal)) return "pgp";
            if (c.Data.Length >= 9 && c.Data.Length <= 16 && aid.StartsWith("A00000030800001000",StringComparison.Ordinal)) return "piv";
            return null;
        }
        public void Observe(Command c, byte[] response) {
            if (c == null) return;
            if (c.Bytes[1] == 0xA4) selected = response[response.Length - 2] == 0x61 || (response[response.Length - 2] == 0x90 && response[response.Length - 1] == 0) ? Target(c) : null;
            if (c.Bytes[1] == 0x70) selected = null;
        }
        public bool Allowed(Command c) {
            if (c == null || !c.Extended || c.Bytes[0] != 0 || c.Le < 0 || c.Data.Length > 255) return false;
            if (Target(c) != null) return true;
            if (selected == "pgp") return (c.Bytes[1] == 0xCA && c.Data.Length == 0) ||
                (c.Bytes[1] == 0x47 && c.Bytes[2] == 0x81 && c.Bytes[3] == 0 && c.Data.Length == 2 && (c.Data[0] == 0xB6 || c.Data[0] == 0xB8 || c.Data[0] == 0xA4) && c.Data[1] == 0);
            if (selected == "piv") return c.Bytes[1] == 0xCB && c.Bytes[2] == 0x3F && c.Bytes[3] == 0xFF && c.Data.Length >= 3 && c.Data[0] == 0x5C && c.Data[1] == c.Data.Length - 2;
            return false;
        }
        private static byte[] ReadOnce(Func<byte[],byte[]> raw, byte[] wire, int amount) {
            byte[] r = Apdu.Checked(raw(wire));
            if (r.Length == 2 && r[0] == 0x6C && (r[1] == 0 ? 256 : r[1]) <= amount) {
                wire = (byte[])wire.Clone(); wire[wire.Length - 1] = r[1]; r = Apdu.Checked(raw(wire));
            }
            return r;
        }
        private void CheckObject(Command c, byte[] data) {
            byte[] tag = null;
            if (selected == "piv" && c.Bytes[1] == 0xCB) tag = new byte[]{0x53};
            if (selected == "pgp" && c.Bytes[1] == 0x47) tag = new byte[]{0x7F,0x49};
            if (selected == "pgp" && c.Bytes[1] == 0xCA) {
                if (c.Bytes[2] == 0 && c.Bytes[3] == 0x6E) tag = new byte[]{0x6E};
                if (c.Bytes[2] == 0x7F && c.Bytes[3] == 0x66) tag = new byte[]{0x7F,0x66};
            }
            if (tag == null) return; // Raw AID, historical/cardholder bytes and empty certificate DOs are legitimate.
            if (data.Length <= tag.Length) throw new LinkException("Public object truncated/empty despite 9000");
            for (int i = 0; i < tag.Length; i++) if (tag[i] != data[i]) throw new LinkException("Unexpected public object tag");
            int offset = tag.Length, size = data[offset++];
            if ((size & 0x80) != 0) {
                int count = size & 0x7F; size = 0;
                if (count < 1 || count > 3 || offset + count > data.Length) throw new LinkException("Invalid public object BER length");
                for (int i = 0; i < count; i++) size = (size << 8) | data[offset++];
            }
            if (offset + size != data.Length) throw new LinkException("Incomplete public object despite 9000");
        }
        public byte[] Read(Command c, Func<byte[],byte[]> raw) {
            if (!Allowed(c)) return Apdu.Status(0x67,0);
            int requested = Math.Min(c.Le,65533), amount = Math.Min(requested,256);
            byte[] r = ReadOnce(raw,Apdu.Short(c,0,c.Data,amount),amount);
            using (MemoryStream output = new MemoryStream()) {
                for (int rounds = 0; rounds <= 256; rounds++) {
                    int count = r.Length - 2;
                    if (output.Length + count > requested) throw new LinkException("Public read exceeds requested Le");
                    output.Write(r,0,count); byte sw1 = r[r.Length-2], sw2 = r[r.Length-1];
                    if (sw1 != 0x61 || output.Length == requested) {
                        if (sw1 == 0x90 && sw2 == 0) CheckObject(c,output.ToArray());
                        output.WriteByte(sw1); output.WriteByte(sw2); return output.ToArray();
                    }
                    if (rounds == 256 || (rounds > 0 && count == 0)) throw new LinkException("Public GET RESPONSE limit/no progress");
                    amount = Math.Min(Math.Min(requested - (int)output.Length,sw2 == 0 ? 256 : sw2),256);
                    r = ReadOnce(raw,new byte[]{0,0xC0,0,0,(byte)(amount == 256 ? 0 : amount)},amount);
                }
            }
            throw new LinkException("Public read incomplete");
        }
    }
    public sealed class Ats {
        public byte[] Atr { get; private set; }
        public static Ats Parse(byte[] ats) {
            if (ats == null || ats.Length < 1 || ats.Length > 20 || ats[0] != ats.Length) throw new LinkException("Invalid ATS length");
            int offset = 1;
            if (ats.Length > 1) {
                byte t0 = ats[1]; offset = 2;
                if ((t0 & 0x80) != 0 || (t0 & 15) > 8) throw new LinkException("Invalid ATS FSCI");
                foreach (int bit in new int[] { 0x10, 0x20, 0x40 }) if ((t0 & bit) != 0) {
                    if (offset >= ats.Length) throw new LinkException("Truncated ATS interfaces");
                    if (bit == 0x20 && ((ats[offset] >> 4) == 15 || (ats[offset] & 15) == 15)) throw new LinkException("Reserved ATS waiting time");
                    offset++;
                }
            }
            int k = ats.Length - offset;
            if (k > 15) throw new LinkException("ATS history exceeds ATR capacity");
            byte[] atr = new byte[5 + k]; atr[0] = 0x3B; atr[1] = (byte)(0x80 | k); atr[2] = 0x80; atr[3] = 1;
            Array.Copy(ats, offset, atr, 4, k); for (int i = 1; i < atr.Length - 1; i++) atr[atr.Length - 1] ^= atr[i];
            return new Ats { Atr = atr };
        }
    }
    public static class ContactAtr {
        public static int Protocol(byte[] atr) {
            if (atr == null || atr.Length < 2 || atr.Length > 33 || (atr[0] != 0x3B && atr[0] != 0x3F)) throw new LinkException("Invalid contact ATR");
            int index = 2, mask = atr[1] >> 4, group = 1, first = -1, specific = -1; bool tck = false;
            while (mask != 0) {
                foreach (int bit in new int[] { 1, 2, 4 }) if ((mask & bit) != 0) {
                    if (index >= atr.Length) throw new LinkException("Truncated contact ATR interfaces");
                    if (group == 2 && bit == 1) specific = atr[index] & 15;
                    index++;
                }
                if ((mask & 8) == 0) break;
                if (index >= atr.Length) throw new LinkException("Missing contact ATR TD");
                byte td = atr[index++]; int p = td & 15;
                if (p != 0) tck = true; if (first < 0 && p != 15) first = p;
                mask = td >> 4; group++;
            }
            if (index + (atr[1] & 15) + (tck ? 1 : 0) != atr.Length) throw new LinkException("ATR length mismatch");
            if (tck) { byte v = 0; for (int i = 1; i < atr.Length; i++) v ^= atr[i]; if (v != 0) throw new LinkException("Bad ATR TCK"); }
            int protocol = specific >= 0 ? specific : first < 0 ? 0 : first;
            if (protocol != 0 && protocol != 1) throw new LinkException("Unsupported contact protocol");
            return protocol;
        }
    }
    public interface ICard : IDisposable {
        byte[] Atr { get; } string Medium { get; }
        bool Activate(string mode, bool preferContact); void Reset(); void PowerOff();
        bool ContactPresent(); bool RfPresent(); byte[] Transmit(byte[] apdu);
    }
    public interface IHuadaSdk {
        int Open(string port); int Close(int handle); int Beep(int h, byte duration);
        int Version(int h, StringBuilder b); int Status(int h, byte slot);
        int ContactOn(int h, byte slot, byte[] b); int ContactOff(int h, byte slot);
        int ContactApdu(int h, byte slot, byte[] c, byte[] b);
        int RfControl(int h, short on); int TypeA(int h); int Request(int h);
        int Anticoll(int h, byte[] uid); int Select(int h, byte type); int RfOn(int h, byte[] ats);
        int RfApdu(int h, byte[] c, byte[] b); void Banner(int h);
    }
    internal static class Native {
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall, CharSet=CharSet.Ansi)] internal static extern int ICC_Reader_Open(string port);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int ICC_Reader_Close(int h);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int ICC_PosBeep(int h, byte duration);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall, CharSet=CharSet.Ansi)] internal static extern int ICC_Reader_GetDeviceVersion(int h, StringBuilder b);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int ICC_Reader_GetStatus(int h, byte slot);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int ICC_Reader_PowerOn(int h, byte slot, [Out] byte[] b);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int ICC_Reader_PowerOff(int h, byte slot);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int ICC_Reader_Application(int h, byte slot, int n, byte[] c, [Out] byte[] b);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int PICC_Reader_RFControl(int h, short on);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int PICC_Reader_SetTypeA(int h);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int PICC_Reader_Request(int h);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int PICC_Reader_anticoll(int h, [Out] byte[] uid);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int PICC_Reader_Select(int h, byte type);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int PICC_Reader_PowerOnTypeA(int h, [Out] byte[] b);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int PICC_Reader_Application(int h, int n, byte[] c, [Out] byte[] b);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall, CharSet=CharSet.Ansi)] internal static extern int ICC_DispInfo(int h, byte row, byte col, string data);
        [DllImport("SSSE32.dll", CallingConvention=CallingConvention.StdCall)] internal static extern int ICC_ChangeLight(int h, byte mode);
    }
    public static class DriverLoader {
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] private static extern IntPtr LoadLibraryEx(string file, IntPtr reserved, uint flags);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] private static extern uint GetModuleFileName(IntPtr h, StringBuilder path, int count);
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] private static extern IntPtr GetModuleHandle(string name);
        public const string QualifiedHash = "94cdd613c9cf6175f111508774780aea38f48a1f7726cb2c152eb69d0a96be83";
        public static void Load(string directory) {
            if (IntPtr.Size != 4) throw new InvalidOperationException("SSSE32 requires x86 PowerShell");
            string path = Path.GetFullPath(Path.Combine(directory, "SSSE32.dll"));
            string hash; using (SHA256 sha = SHA256.Create()) hash = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path))).Replace("-", "").ToLowerInvariant();
            if (hash != QualifiedHash) {
                Console.WriteLine("[Notice] Using custom/unpatched SSSE32.dll (SHA-256: " + hash + ")");
            }
            IntPtr existing = GetModuleHandle("SSSE32.dll"); if (existing != IntPtr.Zero) Verify(existing, path);
            IntPtr module = LoadLibraryEx(path, IntPtr.Zero, 0x100 | 0x800);
            if (module == IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Cannot load packaged SSSE32.dll");
            Verify(module, path);
        }
        private static void Verify(IntPtr module, string expected) {
            StringBuilder actual = new StringBuilder(32768);
            if (GetModuleFileName(module, actual, actual.Capacity) == 0 || !String.Equals(Path.GetFullPath(actual.ToString()), expected, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("A different SSSE32.dll is already loaded; restart with the packaged driver");
        }
    }
    internal sealed class VendorSdk : IHuadaSdk {
        public int Open(string p) { return Native.ICC_Reader_Open(p); } public int Close(int h) { return Native.ICC_Reader_Close(h); }
        public int Beep(int h, byte d) { return Native.ICC_PosBeep(h,d); }
        public int Version(int h, StringBuilder b) { return Native.ICC_Reader_GetDeviceVersion(h,b); }
        public int Status(int h, byte s) { return Native.ICC_Reader_GetStatus(h,s); }
        public int ContactOn(int h, byte s, byte[] b) { return Native.ICC_Reader_PowerOn(h,s,b); }
        public int ContactOff(int h, byte s) { return Native.ICC_Reader_PowerOff(h,s); }
        public int ContactApdu(int h, byte s, byte[] c, byte[] b) { return Native.ICC_Reader_Application(h,s,c.Length,c,b); }
        public int RfControl(int h, short on) { return Native.PICC_Reader_RFControl(h,on); } public int TypeA(int h) { return Native.PICC_Reader_SetTypeA(h); }
        public int Request(int h) { return Native.PICC_Reader_Request(h); } public int Anticoll(int h, byte[] u) { return Native.PICC_Reader_anticoll(h,u); }
        public int Select(int h, byte type) { return Native.PICC_Reader_Select(h,type); } public int RfOn(int h, byte[] b) { return Native.PICC_Reader_PowerOnTypeA(h,b); }
        public int RfApdu(int h, byte[] c, byte[] b) { return Native.PICC_Reader_Application(h,c.Length,c,b); }
        public void Banner(int h) {
            // Keep LCD branding. No PIN pad, speech, keyboard input or card commands.
            Native.ICC_ChangeLight(h,1);
            Native.ICC_DispInfo(h,1,1," github.com/chx818/ "); Native.ICC_DispInfo(h,2,1,"     China-HID-     ");
            Native.ICC_DispInfo(h,3,1,"   SmartCard-PCSC   "); Native.ICC_DispInfo(h,4,1,"     by chx818      ");
        }
    }
    public sealed class HuadaCard : ICard {
        private int handle; private readonly IHuadaSdk sdk;
        private bool contactOn, rfOn, disposed, fido; private int contactProtocol;
        private readonly PublicReads publicReads = new PublicReads();
        private readonly Stopwatch rfClock = new Stopwatch(), healthClock = Stopwatch.StartNew();
        public string Medium { get; private set; } // Interface identity survives OFF.
        public byte[] Atr { get; private set; }
        public HuadaCard() : this(new VendorSdk()) { }
        public HuadaCard(IHuadaSdk sdk) {
            this.sdk = sdk; Medium = "None"; Atr = new byte[0];
            handle = sdk.Open("USB1");
            if (handle <= 0) { handle = 0; throw new LinkException("Cannot open HD-100 USB1"); }
            try { sdk.Banner(handle); } catch { sdk.Close(handle); handle = 0; throw; }
        }
        private static void Require(int result, string operation) { if (result != 0) throw new LinkException(operation + " failed: " + result); }
        private void Field(short on) {
            int rc = sdk.RfControl(handle,on);
            // This packaged DLL returns 1 on successful RFControl although PDF says 0.
            if (rc != 0 && rc != 1) throw new LinkException("RF control failed: " + rc);
        }
        private void ClearCard() { Atr = new byte[0]; fido = false; publicReads.Clear(); }
        public void InitScreen() { sdk.Banner(handle); }
        public void Beep() { int code = sdk.Beep(handle,48); if (code != 0) Console.WriteLine("Reader beep rejected: " + code); }
        public bool Activate(string mode, bool preferContact) {
            ClearCard(); Medium = "None";
            if (healthClock.ElapsedMilliseconds > 3000) { StringBuilder b = new StringBuilder(512); int rc = sdk.Version(handle,b); if (rc < 0) throw new LinkException("USB health check failed: " + rc); healthClock.Restart(); }
            if (mode == "Contact") return Contact(); if (mode == "Rf") return Rf();
            if (mode != "Auto") throw new ArgumentException("Invalid card mode");
            return preferContact ? (Contact() || Rf()) : (Rf() || Contact());
        }
        private static bool HasContact(int status) {
            // Bundled DLL maps device state 01 to -3 and 02 to -2;
            // PDF documents 0/1/2. Do not classify communication errors as present.
            if (status == 0 || status == 1 || status == -3) return true;
            if (status == 2 || status == -2) return false;
            throw new LinkException("Contact status error: " + status);
        }
        private bool Contact() {
            if (!HasContact(sdk.Status(handle,1))) return false;
            byte[] b = new byte[65536]; int n = sdk.ContactOn(handle,1,b);
            if (n == -2 || n == -4) return false; // SDK: absent / card does not answer. Auto can try RF.
            if (n <= 0) throw new LinkException("Contact power/reset failed: " + n);
            contactOn = true;
            if (n > 33) throw new LinkException("Invalid contact ATR length: " + n);
            byte[] atr = Apdu.Slice(b,0,n); contactProtocol = ContactAtr.Protocol(atr);
            Atr = atr; Medium = "Contact"; return true;
        }
        private bool Rf() {
            if (!rfOn) { Field(1); rfOn = true; Thread.Sleep(30); Require(sdk.TypeA(handle),"RF Type A configuration"); }
            int request = sdk.Request(handle);
            if (request != 0) { if (request < 0) throw new LinkException("RF request error: " + request); return false; }
            byte[] uid = new byte[256]; Require(sdk.Anticoll(handle,uid),"RF anticollision");
            Require(sdk.Select(handle,0x41),"RF select");
            byte[] b = new byte[65536]; int n = sdk.RfOn(handle,b);
            if (n <= 0 || n > 20) throw new LinkException("RF RATS failed/invalid length: " + n);
            Atr = Ats.Parse(Apdu.Slice(b,0,n)).Atr; Medium = "Rf"; rfClock.Restart(); return true;
        }
        public bool ContactPresent() { return Medium != "Contact" || HasContact(sdk.Status(handle,1)); }
        public bool RfPresent() { return Medium == "Rf"; } // Not a physical presence detector.
        public void Reset() {
            string target = Medium; ClearCard();
            if (target == "Contact") {
                if (contactOn) {
                    int rc = sdk.ContactOff(handle,1);
                    if (rc < 0) throw new LinkException("Contact off before reset failed: " + rc);
                    contactOn = false;
                }
                if (!Contact()) throw new LinkException("Contact card absent during reset");
            } else if (target == "Rf") {
                if (rfOn) { Field(0); rfOn = false; }
                if (!Rf()) throw new LinkException("RF card absent during reset");
            } else throw new LinkException("Reset without a selected interface");
        }
        public void PowerOff() {
            ClearCard();
            try { if (contactOn) { contactOn = false; int rc = sdk.ContactOff(handle,1); if (rc < 0) throw new LinkException("Contact power off failed: " + rc); } }
            finally { if (rfOn) { rfOn = false; Field(0); } }
        }
        private byte[] Raw(byte[] c) {
            Command parsed = Command.Parse(c);
            if (parsed == null || parsed.Extended || c.Length > Apdu.NativeLimit) throw new LinkException("Unsafe native APDU form blocked before SDK");
            byte[] buffer = new byte[65536];
            int n = Medium == "Rf" ? sdk.RfApdu(handle,c,buffer) : sdk.ContactApdu(handle,1,c,buffer);
            // No capacity argument exists. Reserve its 16-bit output range and validate
            // the return value, never scan for 9000 inside untrusted/stale response data.
            if (n < 2 || n > 65535) throw new LinkException(Medium + " SDK APDU failed/invalid length: " + n + "; outcome unknown");
            byte sw1 = buffer[n - 2];
            if (!((sw1 >= 0x60 && sw1 <= 0x6F) || (sw1 >= 0x90 && sw1 <= 0x9F)))
                throw new LinkException("SDK response has an invalid status trailer; response discarded");
            return Apdu.Slice(buffer,0,n);
        }
        public byte[] Transmit(byte[] c) {
            if (handle <= 0 || Atr.Length == 0) throw new LinkException("APDU while card is off/unavailable");
            bool select = c != null && c.Length >= 2 && (c[1] == 0xA4 || c[1] == 0x70);
            bool wasFido = fido; if (select) fido = false;
            if (Medium == "Rf" && rfClock.ElapsedMilliseconds < 400) Thread.Sleep(400 - (int)rfClock.ElapsedMilliseconds);
            byte[] r; Command command = Command.Parse(c);
            try {
                if (command != null && publicReads.Allowed(command)) {
                    // A mapped read is still a T=0 exchange on contact cards: remove
                    // case-4 Le on the wire, but leave bounded 6C retry to PublicReads.
                    r = publicReads.Read(command,delegate(byte[] wire) { return Medium == "Contact" ? Apdu.Contact(Raw,wire,contactProtocol,false) : Raw(wire); });
                }
                else r = Medium == "Rf" ? Apdu.Rf(Raw,c,wasFido) : Apdu.Contact(Raw,c,contactProtocol);
            } catch { fido = false; publicReads.Clear(); throw; }
            publicReads.Observe(command,r);
            if (command != null && c[0] == 0 && c[1] == 0xA4 && c[2] == 4 && c[3] == 0 && BitConverter.ToString(command.Data) == "A0-00-00-06-47-2F-00-01" && (r[r.Length-2] == 0x61 || (r[r.Length-2] == 0x90 && r[r.Length-1] == 0))) fido = true;
            return r;
        }
        public void Dispose() {
            if (disposed) return; disposed = true;
            try { if (handle > 0) PowerOff(); }
            finally { if (handle > 0) { try { sdk.Close(handle); } finally { handle = 0; } } }
        }
    }
    public static class Framing {
        private static byte[] Exact(Stream s, int count, Stopwatch clock, int timeout) {
            byte[] b = new byte[count]; int offset = 0;
            while (offset < count) {
                int remaining = timeout - (int)clock.ElapsedMilliseconds;
                if (remaining <= 0) throw new IOException("VPCD partial-frame deadline");
                if (s.CanTimeout) s.ReadTimeout = remaining;
                int n = s.Read(b,offset,count-offset); if (n == 0) throw new EndOfStreamException("VPCD closed mid-frame"); offset += n;
            }
            return b;
        }
        public static byte[] Read(Stream s, int timeoutMs) {
            Stopwatch clock = Stopwatch.StartNew(); byte[] header = Exact(s,2,clock,timeoutMs); int n = (header[0] << 8) | header[1];
            if (n == 0) throw new LinkException("Empty VPCD frame");
            return Exact(s,n,clock,timeoutMs);
        }
        public static void Write(Stream s, byte[] b) {
            if (b == null || b.Length == 0 || b.Length > 65535) throw new LinkException("VPCD response length out of range");
            if (s.CanTimeout) s.WriteTimeout = 3000;
            byte[] frame = new byte[b.Length + 2]; frame[0] = (byte)(b.Length >> 8); frame[1] = (byte)b.Length; Array.Copy(b,0,frame,2,b.Length); s.Write(frame,0,frame.Length);
        }
    }
    public sealed class VpcdSession {
        private readonly ICard card; private bool powered = true;
        public VpcdSession(ICard card) { this.card = card; }
        public byte[] Handle(byte[] payload) {
            if (payload == null || payload.Length == 0) throw new LinkException("Empty VPCD payload");
            if (payload.Length == 1) {
                switch (payload[0]) {
                    case 0: powered = false; card.PowerOff(); return null;
                    case 1: case 2: powered = false; card.Reset(); powered = true; return null;
                    case 4:
                        if (!powered) { card.Reset(); powered = true; }
                        if (card.Atr.Length < 2 || card.Atr.Length > 33) throw new LinkException("No valid current ATR");
                        return (byte[])card.Atr.Clone();
                    default: throw new LinkException("Unknown VPCD control: " + payload[0]);
                }
            }
            if (!powered) throw new LinkException("APDU received while powered off");
            return Apdu.Checked(card.Transmit(payload));
        }
        public void Run(TcpClient client, Func<bool> stop, int frameTimeout) {
            NetworkStream stream = client.GetStream(); Stopwatch alive = Stopwatch.StartNew(), poll = Stopwatch.StartNew();
            string last = "none", phase = "idle"; long frames = 0, lastMs = 0;
            try {
                while (!stop()) {
                    phase = "waiting for host";
                    if (client.Client.Poll(5000,SelectMode.SelectRead)) {
                        if (client.Available == 0) throw new EndOfStreamException("VPCD closed by peer (TCP EOF)");
                        phase = "reading frame"; byte[] payload = Framing.Read(stream,frameTimeout);
                        last = payload.Length == 1 ? "CTRL(" + payload[0] + ")" : "APDU(len=" + payload.Length + ")"; frames++;
                        phase = "executing " + last; Stopwatch operation = Stopwatch.StartNew(); byte[] response = Handle(payload);
                        phase = "sending response"; if (response != null) Framing.Write(stream,response); lastMs = operation.ElapsedMilliseconds;
                    }
                    if (card.Medium == "Contact" && poll.ElapsedMilliseconds >= 250) {
                        phase = "contact presence check";
                        if (!card.ContactPresent()) throw new LinkException("Contact card removed"); poll.Restart();
                    }
                }
            } catch (Exception ex) {
                ex.Data["BridgeSession"] = "medium=" + card.Medium + "; phase=" + phase + "; last=" + last + "; frames=" + frames + "; last_ms=" + lastMs + "; uptime_ms=" + alive.ElapsedMilliseconds;
                throw;
            }
        }
    }
    public static class Runner {
        private static volatile bool cancel;
        private static void Cancel(object sender, ConsoleCancelEventArgs e) { e.Cancel = true; cancel = true; }
        public static void Run(string host, int port, string mode, bool preferContact, int seconds) { Run(Path.Combine(Environment.CurrentDirectory,"drivers"),host,port,mode,preferContact,seconds); }
        public static void Run(string driverDirectory, string host, int port, string mode, bool preferContact, int seconds) {
            if (port < 1 || port > 65535 || seconds < 0) throw new ArgumentOutOfRangeException("port/time");
            if (mode != "Auto" && mode != "Contact" && mode != "Rf") throw new ArgumentException("Invalid mode");
            IPAddress address;
            if (String.Equals(host,"localhost",StringComparison.OrdinalIgnoreCase)) address = IPAddress.Loopback;
            else if (!IPAddress.TryParse(host,out address) || !IPAddress.IsLoopback(address)) throw new ArgumentException("VPCD must use loopback");
            bool held = false;
            using (Mutex mutex = new Mutex(false,@"Global\ChinaHid.Huada.HD100")) {
                try {
                    try { held = mutex.WaitOne(0); } catch (AbandonedMutexException) { held = true; }
                    if (!held) throw new InvalidOperationException("Another Huada bridge owns this reader");
                    DriverLoader.Load(driverDirectory); cancel = false; Console.CancelKeyPress += Cancel;
                    Stopwatch clock = Stopwatch.StartNew(); Func<bool> stop = delegate { return cancel || (seconds > 0 && clock.Elapsed.TotalSeconds >= seconds); };
                    Console.WriteLine("Huada HD-100 mode=" + mode + ", priority=" + (preferContact ? "Contact" : "Rf") + ", VPCD=" + address + ":" + port);
                    Console.WriteLine("Fixed signature banner displayed. Dual-interface PC/SC bridge active.");
                    bool readerAnnounced = false; string previousError = null; Stopwatch errorClock = Stopwatch.StartNew();
                    while (!stop()) {
                        try {
                            using (HuadaCard card = new HuadaCard()) {
                                if (!readerAnnounced) { card.Beep(); readerAnnounced = true; }
                                while (!stop() && !card.Activate(mode,preferContact)) Thread.Sleep(100);
                                if (stop()) break;
                                card.Beep(); Console.WriteLine("Card detected: " + card.Medium + "; ATR=" + BitConverter.ToString(card.Atr));
                                TcpClient client = null; bool warned = false;
                                try {
                                    while (!stop()) {
                                        client = new TcpClient(address.AddressFamily);
                                        try {
                                            IAsyncResult pending = client.BeginConnect(address,port,null,null);
                                            using (WaitHandle waiter = pending.AsyncWaitHandle) {
                                                if (!waiter.WaitOne(2000)) throw new IOException("VPCD connect deadline");
                                                client.EndConnect(pending);
                                            }
                                            break;
                                        } catch (SocketException) { client.Close(); client = null; if (!warned) { Console.WriteLine("Waiting for VPCD; card is kept active."); warned = true; } }
                                        catch (IOException) { client.Close(); client = null; if (!warned) { Console.WriteLine("Waiting for VPCD; card is kept active."); warned = true; } }
                                        if (!stop()) Thread.Sleep(250);
                                    }
                                    if (stop()) break;
                                    client.NoDelay = true; Console.WriteLine("Connected to VPCD."); new VpcdSession(card).Run(client,stop,3000);
                                } finally { if (client != null) client.Close(); }
                            }
                        } catch (IOException ex) {
                            if (previousError != ex.Message || errorClock.ElapsedMilliseconds > 10000) {
                                Console.WriteLine("[" + DateTimeOffset.Now.ToString("o") + "] Session ended: " + ex.Message);
                                if (ex.Data.Contains("BridgeSession")) Console.WriteLine("[Session context] " + ex.Data["BridgeSession"]);
                                previousError = ex.Message; errorClock.Restart();
                            }
                        } catch (SocketException ex) { Console.WriteLine("VPCD transport error: " + ex.SocketErrorCode); }
                        if (!stop()) Thread.Sleep(250);
                    }
                } finally { Console.CancelKeyPress -= Cancel; if (held) mutex.ReleaseMutex(); }
            }
        }
    }
}
