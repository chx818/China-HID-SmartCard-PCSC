using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;
using System.Text;
using System.Collections.Generic;

namespace ChinaHid {
    public sealed class LinkException : IOException {
        public LinkException(string message) : base(message) { }
    }

    public static class Apdu {
        public static byte[] Slice(byte[] b, int start, int count) {
            byte[] r = new byte[count];
            Array.Copy(b, start, r, 0, count);
            return r;
        }

        public static byte[] Status(byte sw1, byte sw2) {
            return new byte[] { sw1, sw2 };
        }

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

        /// <summary>
        /// Proxies APDUs with hardware chunking (ISO 7816-4 command chaining for Lc > 240)
        /// and response chaining (auto GET RESPONSE loop on 61 XX).
        /// </summary>
        public static byte[] TransmitWithChaining(Func<byte[], byte[]> rawExchange, byte[] command) {
            if (!Valid(command)) return Status(0x67, 0x00);

            byte cla = command[0];
            byte ins = command[1];
            byte p1 = command[2];
            byte p2 = command[3];

            int lc = 0;
            int dataOffset = 0;
            bool hasLe = false;
            byte le = 0;

            if (command.Length == 4) {
                // Case 1
            } else if (command.Length == 5) {
                // Short APDU Case 2S
                hasLe = true;
                le = command[4];
            } else if (command[4] != 0) {
                // Short APDU Case 3S or 4S
                lc = command[4];
                dataOffset = 5;
                if (command.Length == 6 + lc) {
                    hasLe = true;
                    le = command[command.Length - 1];
                }
            } else if (command.Length == 7) {
                // Extended APDU Case 2E: CLA INS P1 P2 00 Le1 Le2
                hasLe = true;
                // No Lc, only Ne
            } else if (command.Length > 7) {
                // Extended APDU Case 3E or 4E
                lc = (command[5] << 8) | command[6];
                dataOffset = 7;
                if (command.Length == 9 + lc) {
                    hasLe = true;
                    le = command[command.Length - 1];
                }
            }

            byte[] r = null;

            if (lc > 240) {
                int sent = 0;
                while (sent < lc) {
                    int chunkSize = Math.Min(240, lc - sent);
                    bool isLast = (sent + chunkSize == lc);
                    byte chunkCla = isLast ? cla : (byte)(cla | 0x10);

                    int frameLen = 5 + chunkSize + (isLast && hasLe ? 1 : 0);
                    byte[] chunkFrame = new byte[frameLen];
                    chunkFrame[0] = chunkCla;
                    chunkFrame[1] = ins;
                    chunkFrame[2] = p1;
                    chunkFrame[3] = p2;
                    chunkFrame[4] = (byte)chunkSize;
                    Array.Copy(command, dataOffset + sent, chunkFrame, 5, chunkSize);
                    if (isLast && hasLe) chunkFrame[frameLen - 1] = le;

                    r = Checked(rawExchange(chunkFrame));
                    sent += chunkSize;

                    if (!isLast) {
                        byte sw1 = r[r.Length - 2];
                        byte sw2 = r[r.Length - 1];
                        if (sw1 != 0x90 || sw2 != 0x00) {
                            return r;
                        }
                    }
                }
            } else {
                r = Checked(rawExchange(command));
            }

            // ISO 7816-4 Response Chaining loop on 61 XX
            if (r.Length >= 2 && r[r.Length - 2] == 0x61) {
                List<byte> assembled = new List<byte>();
                for (int i = 0; i < r.Length - 2; i++) assembled.Add(r[i]);

                byte sw2 = r[r.Length - 1];
                for (int rounds = 0; rounds < 64; rounds++) {
                    byte getCla = (byte)((cla & 0x80) != 0 ? (cla & 3) : 0x00);
                    byte[] getCmd = new byte[] { getCla, 0xC0, 0x00, 0x00, sw2 };
                    r = Checked(rawExchange(getCmd));
                    if (r.Length < 2) break;

                    for (int i = 0; i < r.Length - 2; i++) assembled.Add(r[i]);

                    byte nextSw1 = r[r.Length - 2];
                    byte nextSw2 = r[r.Length - 1];
                    if (nextSw1 == 0x61) {
                        sw2 = nextSw2;
                    } else {
                        assembled.Add(nextSw1);
                        assembled.Add(nextSw2);
                        return assembled.ToArray();
                    }
                }
                assembled.Add(r[r.Length - 2]);
                assembled.Add(r[r.Length - 1]);
                return assembled.ToArray();
            }

            return r;
        }

        /// <summary>
        /// Contactless RF transmission: passes APDUs to the card.
        /// If command is long (Lc > 240), chunks with ISO 7816-4 command chaining (CLA | 0x10)
        /// to stay within SSSE32.dll's stack buffer limit (~290 bytes).
        /// Does NOT assemble 61 XX: raw responses (including 61 XX status) are returned
        /// directly to Windows PC/SC for native GET RESPONSE dispatch.
        /// </summary>
        public static byte[] TransmitRf(Func<byte[], byte[]> rawExchange, byte[] command) {
            if (!Valid(command)) return Status(0x67, 0x00);

            byte cla = command[0];
            byte ins = command[1];
            byte p1 = command[2];
            byte p2 = command[3];

            int lc = 0;
            int dataOffset = 0;
            bool hasLe = false;
            byte le = 0;

            if (command.Length > 7 && command[4] == 0) {
                // Extended APDU Case 3E or 4E
                lc = (command[5] << 8) | command[6];
                dataOffset = 7;
                if (command.Length == 9 + lc) {
                    hasLe = true;
                    le = command[command.Length - 1];
                }
            } else if (command.Length > 5 && command[4] != 0) {
                // Short APDU Case 3S or 4S
                lc = command[4];
                dataOffset = 5;
                if (command.Length == 6 + lc) {
                    hasLe = true;
                    le = command[command.Length - 1];
                }
            }

            if (lc > 240) {
                byte[] r = null;
                int sent = 0;
                while (sent < lc) {
                    int chunkSize = Math.Min(240, lc - sent);
                    bool isLast = (sent + chunkSize == lc);
                    byte chunkCla = isLast ? cla : (byte)(cla | 0x10);

                    int frameLen = 5 + chunkSize + (isLast && hasLe ? 1 : 0);
                    byte[] chunkFrame = new byte[frameLen];
                    chunkFrame[0] = chunkCla;
                    chunkFrame[1] = ins;
                    chunkFrame[2] = p1;
                    chunkFrame[3] = p2;
                    chunkFrame[4] = (byte)chunkSize;
                    Array.Copy(command, dataOffset + sent, chunkFrame, 5, chunkSize);
                    if (isLast && hasLe) chunkFrame[frameLen - 1] = le;

                    r = Checked(rawExchange(chunkFrame));
                    sent += chunkSize;

                    if (!isLast) {
                        byte sw1 = r[r.Length - 2];
                        byte sw2 = r[r.Length - 1];
                        if (sw1 != 0x90 || sw2 != 0x00) {
                            return r;
                        }
                    }
                }
                return r;
            } else {
                return Checked(rawExchange(command));
            }
        }
    }

    public sealed class Ats {
        public byte[] Atr { get; private set; }
        public static Ats Parse(byte[] ats) {
            if (ats == null || ats.Length < 1 || ats.Length > 32)
                throw new LinkException("Invalid ATS length");
            int offset = 1;
            if (ats.Length > 1) {
                byte t0 = ats[1];
                offset = 2;
                foreach (int bit in new int[] { 0x10, 0x20, 0x40 }) {
                    if ((t0 & bit) != 0) {
                        if (offset >= ats.Length) break;
                        offset++;
                    }
                }
            }
            int k = ats.Length - offset;
            if (k < 0) k = 0;
            if (k > 15) k = 15;
            byte[] atr = new byte[5 + k];
            atr[0] = 0x3B;
            atr[1] = (byte)(0x80 | k);
            atr[2] = 0x80;
            atr[3] = 1;
            if (k > 0) Array.Copy(ats, offset, atr, 4, k);
            for (int i = 1; i < atr.Length - 1; i++) atr[atr.Length - 1] ^= atr[i];
            return new Ats { Atr = atr };
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
        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Ansi)]
        public static extern int ICC_Reader_Open(string devName);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_Reader_Close(int readerHandle);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_PosBeep(int readerHandle, int time);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Ansi)]
        public static extern int ICC_Reader_GetDeviceVersion(int readerHandle, StringBuilder version);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Ansi)]
        public static extern int ICC_Reader_GetDeviceSN(int readerHandle, StringBuilder sn);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_Reader_GetStatus(int readerHandle, byte slotNo);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_Reader_PowerOn(int readerHandle, byte slotNo, byte[] response);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_Reader_pre_PowerOn(int readerHandle, byte slotNo, byte[] response);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_Reader_hot_PowerOn(int readerHandle, byte slotNo, byte[] response);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_Reader_PowerOff(int readerHandle, byte slotNo);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_Reader_Application(int readerHandle, byte slotNo, int cmdLen, byte[] cmd, byte[] response);

        // Display & Backlight
        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Ansi)]
        public static extern int ICC_DispInfo(int readerHandle, byte row, byte list, string data);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int ICC_ChangeLight(int readerHandle, byte mode);

        // Contactless PICC
        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int PICC_Reader_RFControl(int readerHandle, short flag);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int PICC_Reader_SetTypeA(int readerHandle);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int PICC_Reader_Request(int readerHandle);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int PICC_Reader_anticoll(int readerHandle, byte[] uid);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int PICC_Reader_Select(int readerHandle, byte cardType);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int PICC_Reader_PowerOnTypeA(int readerHandle, byte[] response);

        [DllImport("SSSE32.dll", CallingConvention = CallingConvention.StdCall)]
        public static extern int PICC_Reader_Application(int readerHandle, int cmdLen, byte[] cmd, byte[] response);
    }

    public sealed class HuadaCard : ICard {
        private int handle;
        public string Medium { get; private set; }
        public byte[] Atr { get; private set; }
        private bool disposed;

        public HuadaCard() {
            Medium = "None";
            Atr = new byte[0];
            handle = Native.ICC_Reader_Open("USB1");
            if (handle <= 0) {
                throw new LinkException("Cannot open Huada HD-100 reader (code " + handle + ")");
            }
            InitScreen();
        }

        /// <summary>
        /// Persistent project banner display. Maintained across card connect, disconnect, and idle.
        /// Line width: 20 characters.
        /// </summary>
        public void InitScreen() {
            if (handle > 0) {
                Native.ICC_ChangeLight(handle, 1);
                Native.ICC_DispInfo(handle, 1, 1, " github.com/chx818/ ");
                Native.ICC_DispInfo(handle, 2, 1, "     China-HID-     ");
                Native.ICC_DispInfo(handle, 3, 1, "   SmartCard-PCSC   ");
                Native.ICC_DispInfo(handle, 4, 1, "     by chx818      ");
            }
        }

        public bool Activate(string mode, bool preferContact) {
            Atr = new byte[0];
            Medium = "None";

            if (mode == "Contact") return TryActivateContact();
            if (mode == "Rf") return TryActivateRf();

            if (preferContact) {
                if (TryActivateContact()) return true;
                return TryActivateRf();
            } else {
                if (TryActivateRf()) return true;
                return TryActivateContact();
            }
        }

        private bool TryActivateContact() {
            int status = Native.ICC_Reader_GetStatus(handle, 1);
            if (status != 0 && status != 1 && status != -3) return false;

            byte[] resp = new byte[64];
            int len = Native.ICC_Reader_PowerOn(handle, 1, resp);
            if (len <= 0) len = Native.ICC_Reader_pre_PowerOn(handle, 1, resp);
            if (len <= 0) len = Native.ICC_Reader_hot_PowerOn(handle, 1, resp);
            if (len > 0) {
                Atr = Apdu.Slice(resp, 0, len);
                Medium = "Contact";
                return true;
            }
            return false;
        }

        private bool TryActivateRf() {
            Native.PICC_Reader_RFControl(handle, 1);
            Thread.Sleep(30); // Allow RF field to settle and card power to stabilize
            Native.PICC_Reader_SetTypeA(handle);

            int req = Native.PICC_Reader_Request(handle);
            if (req != 0) {
                Thread.Sleep(20);
                req = Native.PICC_Reader_Request(handle);
                if (req != 0) return false;
            }

            byte[] uid = new byte[10];
            int anticoll = Native.PICC_Reader_anticoll(handle, uid);
            if (anticoll != 0) return false;

            int sel = Native.PICC_Reader_Select(handle, 0x41);
            if (sel != 0) sel = Native.PICC_Reader_Select(handle, 0x00);
            if (sel != 0) return false;

            byte[] ats = new byte[64];
            int atsLen = Native.PICC_Reader_PowerOnTypeA(handle, ats);
            if (atsLen <= 0) {
                Thread.Sleep(25);
                atsLen = Native.PICC_Reader_PowerOnTypeA(handle, ats);
            }
            if (atsLen > 0) {
                Ats parsed = Ats.Parse(Apdu.Slice(ats, 0, atsLen));
                Atr = parsed.Atr;
                Medium = "Rf";
                return true;
            }
            return false;
        }

        public bool ContactPresent() {
            if (handle <= 0) return false;
            int status = Native.ICC_Reader_GetStatus(handle, 1);
            return (status == 0 || status == 1 || status == -3);
        }

        public bool RfPresent() {
            if (handle <= 0 || Medium != "Rf") return false;
            // No intrusive APDU probing during session:
            // injecting APDUs (e.g. 00 A4 04 00 00) deselects the active applet (e.g. FIDO2)
            // and resets transaction state. Card loss is detected on APDU transmission or reset.
            return true;
        }

        public void Reset() {
            if (Medium == "Contact") {
                byte[] resp = new byte[64];
                int len = Native.ICC_Reader_PowerOn(handle, 1, resp);
                if (len <= 0) len = Native.ICC_Reader_pre_PowerOn(handle, 1, resp);
                if (len <= 0) len = Native.ICC_Reader_hot_PowerOn(handle, 1, resp);
                if (len > 0) Atr = Apdu.Slice(resp, 0, len);
                else throw new LinkException("Contact reset failed");
            } else if (Medium == "Rf") {
                Native.PICC_Reader_RFControl(handle, 0);
                Thread.Sleep(30);
                if (!TryActivateRf()) throw new LinkException("RF reset failed");
            }
        }

        public void PowerOff() {
            if (handle <= 0) return;
            if (Medium == "Contact") {
                Native.ICC_Reader_PowerOff(handle, 1);
            } else if (Medium == "Rf") {
                Native.PICC_Reader_RFControl(handle, 0);
            }
            Medium = "None";
            Atr = new byte[0];
        }

        public byte[] Transmit(byte[] apdu) {
            if (handle <= 0) throw new LinkException("Reader handle closed");

            if (Medium == "Rf") {
                return Apdu.TransmitRf(cmd => {
                    byte[] resp = new byte[2048];
                    int rLen = Native.PICC_Reader_Application(handle, cmd.Length, cmd, resp);
                    if (rLen <= 0) {
                        // Resilient recovery: if response buffer has valid SW trailer, recover length
                        if (resp[0] != 0 || resp[1] != 0) {
                            for (int i = 2; i < 512; i++) {
                                if (resp[i] == 0x90 && resp[i + 1] == 0x00 && (i + 2 >= 512 || (resp[i + 2] == 0 && resp[i + 3] == 0))) {
                                    rLen = i + 2;
                                    break;
                                }
                            }
                        }
                    }
                    if (rLen <= 0) throw new LinkException("RF PICC_Reader_Application failed: " + rLen);
                    return Apdu.Slice(resp, 0, rLen);
                }, apdu);
            } else if (Medium == "Contact") {
                return Apdu.TransmitWithChaining(cmd => {
                    byte[] resp = new byte[2048];
                    int rLen = Native.ICC_Reader_Application(handle, 1, cmd.Length, cmd, resp);
                    if (rLen <= 0) throw new LinkException("Contact ICC_Reader_Application failed: " + rLen);
                    return Apdu.Slice(resp, 0, rLen);
                }, apdu);
            } else {
                throw new LinkException("No active card medium for Transmit");
            }
        }

        public void Dispose() {
            if (!disposed) {
                disposed = true;
                if (handle > 0) {
                    try {
                        PowerOff();
                        InitScreen();
                        Native.ICC_Reader_Close(handle);
                    } catch { }
                    handle = 0;
                }
            }
        }
    }

    public static class Framing {
        public static byte[] Read(Stream s, int timeoutMs) {
            byte[] hdr = ReadExact(s, 2, timeoutMs);
            int len = (hdr[0] << 8) | hdr[1];
            if (len == 0) return new byte[0];
            return ReadExact(s, len, timeoutMs);
        }

        public static void Write(Stream s, byte[] payload) {
            byte[] buf = new byte[payload.Length + 2];
            buf[0] = (byte)(payload.Length >> 8);
            buf[1] = (byte)(payload.Length & 0xFF);
            Array.Copy(payload, 0, buf, 2, payload.Length);
            s.Write(buf, 0, buf.Length);
            s.Flush();
        }

        private static byte[] ReadExact(Stream s, int count, int timeoutMs) {
            byte[] buf = new byte[count];
            int offset = 0;
            while (offset < count) {
                int read = s.Read(buf, offset, count - offset);
                if (read <= 0) throw new EndOfStreamException();
                offset += read;
            }
            return buf;
        }
    }

    internal sealed class SessionTrace {
        private readonly Stopwatch lifetime = Stopwatch.StartNew();
        private readonly Queue<string> frames = new Queue<string>();
        private readonly string medium;
        private string phase = "starting", request = "none";
        private long phaseStarted, requestStarted, lastCompleted = -1, requestMs;
        private long contactLast, contactMax, contactCount, requests, responses;
        internal string Peer = "unknown", FailureKind;

        internal SessionTrace(string medium) { this.medium = medium; }
        internal void Begin(string value) { phase = value; phaseStarted = lifetime.ElapsedMilliseconds; }
        internal void Request(byte[] payload) {
            request = payload.Length == 1 ? "CTRL(" + payload[0] + ")" : "APDU(len=" + payload.Length + ")";
            requests++;
            requestMs = -1;
            requestStarted = lifetime.ElapsedMilliseconds;
            Begin("executing " + request);
        }
        internal void Complete(byte[] response) {
            requestMs = lifetime.ElapsedMilliseconds - requestStarted;
            lastCompleted = lifetime.ElapsedMilliseconds;
            if (response != null) responses++;
            if (frames.Count == 8) frames.Dequeue();
            frames.Enqueue(request + ":" + requestMs + "ms/out=" + (response == null ? 0 : response.Length));
            Begin("idle");
        }
        internal void PollDone() {
            long elapsed = lifetime.ElapsedMilliseconds - phaseStarted;
            contactCount++;
            contactLast = elapsed;
            contactMax = Math.Max(contactMax, elapsed);
            Begin("idle");
        }
        internal void Attach(Exception ex) {
            string kind = FailureKind;
            if (kind == null) {
                if (ex is EndOfStreamException) kind = "peer-eof-mid-frame";
                else if (ex is LinkException) kind = "bridge-or-device-error";
                else if (ex is SocketException || ex is IOException) kind = "transport-error";
                else kind = "unexpected-error";
            }
            long now = lifetime.ElapsedMilliseconds;
            SocketException socket = ex as SocketException ?? ex.InnerException as SocketException;
            string socketCode = socket == null ? "none" : socket.SocketErrorCode.ToString();
            ex.Data["BridgeSession"] = "kind=" + kind + "; medium=" + medium + "; peer=" + Peer
                + "; uptime_ms=" + now + "; phase=" + phase + "; phase_ms=" + (now - phaseStarted)
                + "; last_request=" + request + "; last_request_ms=" + requestMs
                + "; since_last_completed_ms=" + (lastCompleted < 0 ? -1 : now - lastCompleted)
                + "; requests=" + requests + "; responses=" + responses + "; socket_error=" + socketCode
                + "; contact_probe(count/last/max_ms)=" + contactCount + "/" + contactLast + "/" + contactMax
                + "; recent=" + String.Join(" | ", frames.ToArray());
        }
    }

    public sealed class VpcdSession {
        private readonly ICard card;
        private bool powered;
        private const int ContactPollMs = 250;
        private const int RfQuietMs = 400;
        private const int RfIdlePollMs = 250;

        public VpcdSession(ICard card) {
            this.card = card;
            this.powered = true;
        }

        public byte[] Handle(byte[] payload) {
            if (payload.Length == 1) {
                switch (payload[0]) {
                    case 0:
                        powered = false;
                        card.PowerOff();
                        return null;
                    case 1:
                    case 2:
                        powered = false;
                        card.Reset();
                        powered = true;
                        return null;
                    case 4:
                        if (!powered) {
                            card.Reset();
                            powered = true;
                        }
                        if (card.Atr.Length < 2 || card.Atr.Length > 33)
                            throw new LinkException("No current ATR");
                        return (byte[])card.Atr.Clone();
                    default:
                        throw new LinkException("Unknown VPCD control: " + payload[0]);
                }
            }
            if (!powered) throw new LinkException("APDU received while powered off");
            return Apdu.Checked(card.Transmit(payload));
        }

        public void Run(TcpClient client, Func<bool> stop, int frameTimeout) {
            NetworkStream stream = client.GetStream();
            Stopwatch contactPoll = Stopwatch.StartNew(), idle = Stopwatch.StartNew(), rfPoll = Stopwatch.StartNew();
            SessionTrace trace = new SessionTrace(card.Medium);
            trace.Peer = Convert.ToString(client.Client.RemoteEndPoint);

            try {
                while (!stop()) {
                    trace.Begin("waiting for host");
                    if (client.Client.Poll(5000, SelectMode.SelectRead)) {
                        if (client.Available == 0) {
                            trace.FailureKind = "peer-eof";
                            throw new EndOfStreamException("VPCD closed by peer (TCP EOF)");
                        }
                        trace.Begin("reading host frame");
                        byte[] payload = Framing.Read(stream, frameTimeout);
                        trace.Request(payload);
                        if (payload.Length > 1) {
                            Console.WriteLine("[" + DateTime.Now.ToString("HH:mm:ss.fff") + "] APDU In:  " + BitConverter.ToString(payload));
                        }
                        byte[] response = Handle(payload);
                        trace.Begin("sending response");
                        if (response != null) {
                            Framing.Write(stream, response);
                            if (payload.Length > 1) {
                                Console.WriteLine("[" + DateTime.Now.ToString("HH:mm:ss.fff") + "] APDU Out: " + BitConverter.ToString(response));
                            }
                        }
                        trace.Complete(response);
                        if (payload.Length != 1 || payload[0] != 4) idle.Restart();
                    }

                    if (card.Medium == "Contact" && contactPoll.ElapsedMilliseconds >= ContactPollMs) {
                        trace.Begin("contact presence check");
                        if (!card.ContactPresent()) {
                            trace.FailureKind = "contact-absent";
                            throw new LinkException("Contact card removed");
                        }
                        trace.PollDone();
                        contactPoll.Restart();
                    }
                }
            } catch (Exception ex) {
                trace.Attach(ex);
                throw;
            }
        }
    }

    public static class Runner {
        private static volatile bool cancel;
        private static void Cancel(object sender, ConsoleCancelEventArgs e) {
            e.Cancel = true;
            cancel = true;
        }

        public static void Run(string host, int port, string mode, bool preferContact, int runSeconds) {
            IPAddress address;
            if (host == "localhost") address = IPAddress.Loopback;
            else if (!IPAddress.TryParse(host, out address) || !IPAddress.IsLoopback(address))
                throw new ArgumentException("VPCD must use a loopback address");

            bool acquired = false;
            using (Mutex mutex = new Mutex(false, @"Global\ChinaHid.Huada.HD100")) {
                try {
                    try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) throw new InvalidOperationException("Another Huada bridge owns this reader");

                    cancel = false;
                    Console.CancelKeyPress += Cancel;
                    Stopwatch lifetime = Stopwatch.StartNew();
                    Func<bool> stop = delegate { return cancel || (runSeconds > 0 && lifetime.Elapsed.TotalSeconds >= runSeconds); };

                    Console.WriteLine("Huada HD-100 mode=" + mode + ", priority=" + (preferContact ? "Contact" : "Rf") + ", VPCD=" + address + ":" + port);
                    Console.WriteLine("Fixed signature banner displayed. ISO 7816-4 APDU command/response chaining enabled.");

                    using (HuadaCard card = new HuadaCard()) {
                        while (!stop()) {
                            if (!card.Activate(mode, preferContact)) {
                                Thread.Sleep(200);
                                continue;
                            }

                            Console.WriteLine("[" + DateTime.Now.ToString("HH:mm:ss") + "] Card detected (" + card.Medium + "), ATR: " + BitConverter.ToString(card.Atr));

                            using (TcpClient client = new TcpClient()) {
                                try {
                                    client.Connect(address, port);
                                    Console.WriteLine("[" + DateTime.Now.ToString("HH:mm:ss") + "] Connected to VPCD at " + address + ":" + port);
                                    VpcdSession session = new VpcdSession(card);
                                    session.Run(client, stop, 30000);
                                } catch (Exception ex) {
                                    Console.WriteLine("[" + DateTime.Now.ToString("HH:mm:ss") + "] Card/Session event: " + ex.Message);
                                }
                            }

                            card.PowerOff();
                            Thread.Sleep(300);
                        }
                    }
                } finally {
                    if (acquired) mutex.ReleaseMutex();
                }
            }
        }
    }
}
