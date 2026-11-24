using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace TeleplyCodexHook {
    // Minimal native-speed bridge between Codex desktop hooks and Teleply's local named pipe.
    // Uses direct Win32 P/Invoke (no FileStream, no ThreadPool/Timer) to stay near bare CLR startup.
    // Three iron laws:
    //   1. Never exit with code 2 (exit code 2 blocks PreToolUse and forces Stop continuation).
    //   2. Missing pipe, timeout, malformed input, or any exception -> exit 0 ({} for Stop, empty otherwise).
    //   3. Zero external assembly references (mscorlib only) for fast empty-reply turnaround.
    internal static class Program {
        const uint GENERIC_READ = 0x80000000;
        const uint GENERIC_WRITE = 0x40000000;
        const uint OPEN_EXISTING = 3;
        const uint FILE_FLAG_OVERLAPPED = 0x40000000;
        const int STD_INPUT_HANDLE = -10;
        const int STD_OUTPUT_HANDLE = -11;
        const int ERROR_FILE_NOT_FOUND = 2;
        const int ERROR_PIPE_BUSY = 231;
        const int ERROR_IO_PENDING = 997;
        const uint WAIT_OBJECT_0 = 0;
        const int CONNECT_TIMEOUT_MS = 300;
        const int DEFAULT_READ_TIMEOUT_MS = 155000;
        const int MAX_BYTES = 4 * 1024 * 1024;
        static readonly IntPtr INVALID_HANDLE = new IntPtr(-1);

        [StructLayout(LayoutKind.Sequential)]
        struct OVERLAPPED {
            public IntPtr Internal;
            public IntPtr InternalHigh;
            public uint Offset;
            public uint OffsetHigh;
            public IntPtr hEvent;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr CreateFileW(
            string lpFileName, uint dwDesiredAccess, uint dwShareMode,
            IntPtr lpSecurityAttributes, uint dwCreationDisposition,
            uint dwFlagsAndAttributes, IntPtr hTemplateFile);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool WaitNamedPipeW(string lpNamedPipeName, int nTimeOut);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr GetStdHandle(int nStdHandle);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool ReadFile(
            IntPtr hFile, byte[] lpBuffer, uint nNumberOfBytesToRead,
            out uint lpNumberOfBytesRead, IntPtr lpOverlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool ReadFile(
            IntPtr hFile, byte[] lpBuffer, uint nNumberOfBytesToRead,
            out uint lpNumberOfBytesRead, ref OVERLAPPED lpOverlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool WriteFile(
            IntPtr hFile, byte[] lpBuffer, uint nNumberOfBytesToWrite,
            out uint lpNumberOfBytesWritten, IntPtr lpOverlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool WriteFile(
            IntPtr hFile, byte[] lpBuffer, uint nNumberOfBytesToWrite,
            out uint lpNumberOfBytesWritten, ref OVERLAPPED lpOverlapped);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern IntPtr CreateEventW(IntPtr lpEventAttributes, bool bManualReset, bool bInitialState, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetOverlappedResult(IntPtr hFile, ref OVERLAPPED lpOverlapped, out uint lpNumberOfBytesTransferred, bool bWait);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CancelIoEx(IntPtr hFile, IntPtr lpOverlapped);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr hObject);

        static int Main(string[] args) {
            string eventName = (args != null && args.Length > 0 && args[0] != null) ? args[0].Trim() : "";
            try {
                Run(eventName);
            } catch {
                EmitFallback(eventName);
            }
            return 0;
        }

        static bool IsStop(string eventName) {
            return string.Equals(eventName, "Stop", StringComparison.OrdinalIgnoreCase);
        }

        static void EmitStdout(string text) {
            if (string.IsNullOrEmpty(text)) return;
            byte[] bytes = Encoding.UTF8.GetBytes(text);
            IntPtr hOut = GetStdHandle(STD_OUTPUT_HANDLE);
            if (hOut == IntPtr.Zero || hOut == INVALID_HANDLE) return;
            int offset = 0;
            while (offset < bytes.Length) {
                byte[] chunk = offset == 0 ? bytes : Slice(bytes, offset, bytes.Length - offset);
                uint written;
                if (!WriteFile(hOut, chunk, (uint)chunk.Length, out written, IntPtr.Zero) || written == 0) break;
                offset += (int)written;
            }
        }

        static byte[] Slice(byte[] src, int offset, int count) {
            byte[] dst = new byte[count];
            Buffer.BlockCopy(src, offset, dst, 0, count);
            return dst;
        }

        static void EmitFallback(string eventName) {
            try {
                if (IsStop(eventName)) EmitStdout("{}");
            } catch {
                // Never throw from fallback; always return 0.
            }
        }

        static string SanitizeUser(string raw) {
            if (string.IsNullOrEmpty(raw)) return "user";
            var sb = new StringBuilder(raw.Length);
            for (int i = 0; i < raw.Length; i++) {
                char c = raw[i];
                bool ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                          (c >= '0' && c <= '9') || c == '.' || c == '_' || c == '-';
                sb.Append(ok ? c : '_');
            }
            return sb.Length > 0 ? sb.ToString() : "user";
        }

        static string ResolvePipePath() {
            string custom = Environment.GetEnvironmentVariable("TELEPLY_CODEX_HOOK_PIPE");
            if (!string.IsNullOrEmpty(custom)) return custom.Trim();
            string user = Environment.GetEnvironmentVariable("USERNAME");
            if (string.IsNullOrEmpty(user)) user = Environment.UserName;
            return @"\\.\pipe\teleply-codex-hooks-" + SanitizeUser(user);
        }

        static int ResolveReadTimeoutMs() {
            string raw = Environment.GetEnvironmentVariable("TELEPLY_CODEX_HOOK_READ_TIMEOUT_MS");
            int parsed;
            if (!string.IsNullOrEmpty(raw) && int.TryParse(raw, out parsed) && parsed >= 50 && parsed <= 600000) {
                return parsed;
            }
            return DEFAULT_READ_TIMEOUT_MS;
        }

        static string ReadStdinText() {
            IntPtr hIn = GetStdHandle(STD_INPUT_HANDLE);
            if (hIn == IntPtr.Zero || hIn == INVALID_HANDLE) return "";
            byte[] buf = new byte[8192];
            using (var ms = new MemoryStream()) {
                int total = 0;
                while (true) {
                    uint got;
                    bool ok = ReadFile(hIn, buf, (uint)buf.Length, out got, IntPtr.Zero);
                    if (!ok || got == 0) break;
                    int take = (total + (int)got > MAX_BYTES) ? (MAX_BYTES - total) : (int)got;
                    if (take > 0) {
                        ms.Write(buf, 0, take);
                        total += take;
                    }
                    if (total >= MAX_BYTES) break;
                }
                if (ms.Length == 0) return "";
                byte[] all = ms.GetBuffer();
                int len = (int)ms.Length;
                int offset = (len >= 3 && all[0] == 0xEF && all[1] == 0xBB && all[2] == 0xBF) ? 3 : 0;
                return Encoding.UTF8.GetString(all, offset, len - offset);
            }
        }

        static IntPtr ConnectPipe(string pipePath, int timeoutMs) {
            int deadline = Environment.TickCount + timeoutMs;
            while (true) {
                IntPtr handle = CreateFileW(
                    pipePath, GENERIC_READ | GENERIC_WRITE, 0, IntPtr.Zero,
                    OPEN_EXISTING, FILE_FLAG_OVERLAPPED, IntPtr.Zero);
                if (handle != INVALID_HANDLE && handle != IntPtr.Zero) return handle;
                int err = Marshal.GetLastWin32Error();
                if (err == ERROR_FILE_NOT_FOUND) return INVALID_HANDLE;
                if (err != ERROR_PIPE_BUSY) return INVALID_HANDLE;
                int remaining = deadline - Environment.TickCount;
                if (remaining <= 0) return INVALID_HANDLE;
                if (!WaitNamedPipeW(pipePath, remaining)) return INVALID_HANDLE;
            }
        }

        static bool WriteAllOverlapped(IntPtr handle, IntPtr ev, byte[] data, int timeoutMs) {
            int offset = 0;
            int deadline = Environment.TickCount + timeoutMs;
            while (offset < data.Length) {
                byte[] chunk = offset == 0 ? data : Slice(data, offset, data.Length - offset);
                var ov = new OVERLAPPED { hEvent = ev };
                uint written;
                bool ok = WriteFile(handle, chunk, (uint)chunk.Length, out written, ref ov);
                if (!ok) {
                    int err = Marshal.GetLastWin32Error();
                    if (err != ERROR_IO_PENDING) return false;
                    int rem = deadline - Environment.TickCount;
                    if (rem <= 0 || WaitForSingleObject(ev, (uint)rem) != WAIT_OBJECT_0) {
                        CancelIoEx(handle, IntPtr.Zero);
                        return false;
                    }
                    if (!GetOverlappedResult(handle, ref ov, out written, false)) return false;
                }
                if (written == 0) return false;
                offset += (int)written;
            }
            return true;
        }

        static byte[] ReadExactOverlapped(IntPtr handle, IntPtr ev, int count, int deadline) {
            byte[] result = new byte[count];
            byte[] scratch = new byte[count];
            int offset = 0;
            while (offset < count) {
                int need = count - offset;
                var ov = new OVERLAPPED { hEvent = ev };
                uint got;
                bool ok = ReadFile(handle, scratch, (uint)need, out got, ref ov);
                if (!ok) {
                    int err = Marshal.GetLastWin32Error();
                    if (err != ERROR_IO_PENDING) return null;
                    int rem = deadline - Environment.TickCount;
                    if (rem <= 0 || WaitForSingleObject(ev, (uint)rem) != WAIT_OBJECT_0) {
                        CancelIoEx(handle, IntPtr.Zero);
                        return null;
                    }
                    if (!GetOverlappedResult(handle, ref ov, out got, false)) return null;
                }
                if (got == 0) return null;
                Buffer.BlockCopy(scratch, 0, result, offset, (int)got);
                offset += (int)got;
            }
            return result;
        }

        static void Run(string eventName) {
            string rawPayload = ReadStdinText();
            string trimmed = rawPayload.Trim();
            string payloadJson = JsonMini.IsValidJsonObject(trimmed) ? trimmed : "{}";

            IntPtr handle = ConnectPipe(ResolvePipePath(), CONNECT_TIMEOUT_MS);
            if (handle == INVALID_HANDLE || handle == IntPtr.Zero) {
                EmitFallback(eventName);
                return;
            }

            IntPtr ev = CreateEventW(IntPtr.Zero, true, false, null);
            try {
                if (ev == IntPtr.Zero) {
                    EmitFallback(eventName);
                    return;
                }
                string reqJson = "{\"event\":" + JsonMini.Quote(eventName) + ",\"payload\":" + payloadJson + "}";
                byte[] reqBytes = Encoding.UTF8.GetBytes(reqJson);
                if (reqBytes.Length > MAX_BYTES) {
                    EmitFallback(eventName);
                    return;
                }
                byte[] frame = new byte[4 + reqBytes.Length];
                frame[0] = (byte)(reqBytes.Length & 0xFF);
                frame[1] = (byte)((reqBytes.Length >> 8) & 0xFF);
                frame[2] = (byte)((reqBytes.Length >> 16) & 0xFF);
                frame[3] = (byte)((reqBytes.Length >> 24) & 0xFF);
                Buffer.BlockCopy(reqBytes, 0, frame, 4, reqBytes.Length);

                if (!WriteAllOverlapped(handle, ev, frame, 5000)) {
                    EmitFallback(eventName);
                    return;
                }

                int readDeadline = Environment.TickCount + ResolveReadTimeoutMs();
                byte[] respHeader = ReadExactOverlapped(handle, ev, 4, readDeadline);
                if (respHeader == null) {
                    EmitFallback(eventName);
                    return;
                }
                int respLen = respHeader[0] | (respHeader[1] << 8) | (respHeader[2] << 16) | (respHeader[3] << 24);
                if (respLen <= 0 || respLen > MAX_BYTES) {
                    EmitFallback(eventName);
                    return;
                }
                byte[] respBytes = ReadExactOverlapped(handle, ev, respLen, readDeadline);
                if (respBytes == null) {
                    EmitFallback(eventName);
                    return;
                }
                string respJson = Encoding.UTF8.GetString(respBytes);
                string stdoutText;
                if (!JsonMini.TryExtractStdout(respJson, out stdoutText)) {
                    EmitFallback(eventName);
                    return;
                }
                if (string.IsNullOrEmpty(stdoutText)) {
                    if (IsStop(eventName)) EmitStdout("{}");
                    return;
                }
                EmitStdout(stdoutText);
            } finally {
                if (ev != IntPtr.Zero) CloseHandle(ev);
                CloseHandle(handle);
            }
        }
    }

    // Minimal zero-dependency JSON helpers (quote, validate object, extract "stdout" string).
    internal static class JsonMini {
        public static string Quote(string s) {
            if (s == null) return "\"\"";
            var sb = new StringBuilder(s.Length + 2);
            sb.Append('"');
            for (int i = 0; i < s.Length; i++) {
                char c = s[i];
                switch (c) {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
            return sb.ToString();
        }

        public static bool IsValidJsonObject(string s) {
            if (string.IsNullOrEmpty(s)) return false;
            int idx = 0;
            SkipWs(s, ref idx);
            if (idx >= s.Length || s[idx] != '{') return false;
            if (!ParseObject(s, ref idx, 0)) return false;
            SkipWs(s, ref idx);
            return idx == s.Length;
        }

        public static bool TryExtractStdout(string json, out string value) {
            value = "";
            if (string.IsNullOrEmpty(json)) return false;
            int idx = 0;
            SkipWs(json, ref idx);
            if (idx >= json.Length || json[idx] != '{') return false;
            idx++;
            SkipWs(json, ref idx);
            if (idx < json.Length && json[idx] == '}') return true;
            while (idx < json.Length) {
                SkipWs(json, ref idx);
                string key;
                if (!ReadString(json, ref idx, out key)) return false;
                SkipWs(json, ref idx);
                if (idx >= json.Length || json[idx] != ':') return false;
                idx++;
                SkipWs(json, ref idx);
                if (key == "stdout") {
                    if (idx < json.Length && json[idx] == '"') {
                        return ReadString(json, ref idx, out value);
                    }
                    if (MatchLiteral(json, ref idx, "null")) {
                        value = "";
                        return true;
                    }
                    return false;
                }
                if (!ParseValue(json, ref idx, 0)) return false;
                SkipWs(json, ref idx);
                if (idx >= json.Length) return false;
                if (json[idx] == '}') return true;
                if (json[idx] != ',') return false;
                idx++;
            }
            return false;
        }

        static void SkipWs(string s, ref int idx) {
            while (idx < s.Length) {
                char c = s[idx];
                if (c == ' ' || c == '\t' || c == '\r' || c == '\n') idx++;
                else break;
            }
        }

        static bool ParseValue(string s, ref int idx, int depth) {
            if (depth > 64) return false;
            SkipWs(s, ref idx);
            if (idx >= s.Length) return false;
            char c = s[idx];
            if (c == '{') return ParseObject(s, ref idx, depth + 1);
            if (c == '[') return ParseArray(s, ref idx, depth + 1);
            if (c == '"') { string unused; return ReadString(s, ref idx, out unused); }
            if (c == 't') return MatchLiteral(s, ref idx, "true");
            if (c == 'f') return MatchLiteral(s, ref idx, "false");
            if (c == 'n') return MatchLiteral(s, ref idx, "null");
            return ParseNumber(s, ref idx);
        }

        static bool ParseObject(string s, ref int idx, int depth) {
            if (depth > 64 || idx >= s.Length || s[idx] != '{') return false;
            idx++;
            SkipWs(s, ref idx);
            if (idx < s.Length && s[idx] == '}') { idx++; return true; }
            while (idx < s.Length) {
                SkipWs(s, ref idx);
                string unused;
                if (!ReadString(s, ref idx, out unused)) return false;
                SkipWs(s, ref idx);
                if (idx >= s.Length || s[idx] != ':') return false;
                idx++;
                if (!ParseValue(s, ref idx, depth + 1)) return false;
                SkipWs(s, ref idx);
                if (idx >= s.Length) return false;
                if (s[idx] == '}') { idx++; return true; }
                if (s[idx] != ',') return false;
                idx++;
            }
            return false;
        }

        static bool ParseArray(string s, ref int idx, int depth) {
            if (depth > 64 || idx >= s.Length || s[idx] != '[') return false;
            idx++;
            SkipWs(s, ref idx);
            if (idx < s.Length && s[idx] == ']') { idx++; return true; }
            while (idx < s.Length) {
                if (!ParseValue(s, ref idx, depth + 1)) return false;
                SkipWs(s, ref idx);
                if (idx >= s.Length) return false;
                if (s[idx] == ']') { idx++; return true; }
                if (s[idx] != ',') return false;
                idx++;
            }
            return false;
        }

        static bool ReadString(string s, ref int idx, out string result) {
            result = "";
            if (idx >= s.Length || s[idx] != '"') return false;
            idx++;
            var sb = new StringBuilder();
            while (idx < s.Length) {
                char c = s[idx++];
                if (c == '"') {
                    result = sb.ToString();
                    return true;
                }
                if (c < 0x20) return false;
                if (c == '\\') {
                    if (idx >= s.Length) return false;
                    char esc = s[idx++];
                    switch (esc) {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (idx + 4 > s.Length) return false;
                            int code = 0;
                            for (int k = 0; k < 4; k++) {
                                char h = s[idx++];
                                int v = (h >= '0' && h <= '9') ? (h - '0')
                                      : (h >= 'a' && h <= 'f') ? (h - 'a' + 10)
                                      : (h >= 'A' && h <= 'F') ? (h - 'A' + 10)
                                      : -1;
                                if (v < 0) return false;
                                code = (code << 4) | v;
                            }
                            sb.Append((char)code);
                            break;
                        default:
                            return false;
                    }
                } else {
                    sb.Append(c);
                }
            }
            return false;
        }

        static bool MatchLiteral(string s, ref int idx, string lit) {
            if (idx + lit.Length > s.Length) return false;
            for (int i = 0; i < lit.Length; i++) {
                if (s[idx + i] != lit[i]) return false;
            }
            idx += lit.Length;
            return true;
        }

        static bool ParseNumber(string s, ref int idx) {
            int start = idx;
            if (idx < s.Length && s[idx] == '-') idx++;
            if (idx >= s.Length) return false;
            if (s[idx] == '0') {
                idx++;
            } else if (s[idx] >= '1' && s[idx] <= '9') {
                while (idx < s.Length && s[idx] >= '0' && s[idx] <= '9') idx++;
            } else {
                return false;
            }
            if (idx < s.Length && s[idx] == '.') {
                idx++;
                if (idx >= s.Length || s[idx] < '0' || s[idx] > '9') return false;
                while (idx < s.Length && s[idx] >= '0' && s[idx] <= '9') idx++;
            }
            if (idx < s.Length && (s[idx] == 'e' || s[idx] == 'E')) {
                idx++;
                if (idx < s.Length && (s[idx] == '+' || s[idx] == '-')) idx++;
                if (idx >= s.Length || s[idx] < '0' || s[idx] > '9') return false;
                while (idx < s.Length && s[idx] >= '0' && s[idx] <= '9') idx++;
            }
            return idx > start;
        }
    }
}
