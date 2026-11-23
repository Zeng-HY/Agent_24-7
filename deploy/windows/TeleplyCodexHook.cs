using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

namespace TeleplyCodexHook {
    // Minimal native-speed bridge between Codex desktop hooks and Teleply's local named pipe.
    // Three iron laws:
    //   1. Never exit with code 2 (exit code 2 blocks PreToolUse and forces Stop continuation).
    //   2. Missing pipe, timeout, malformed input, or any exception -> exit 0 ({} for Stop, empty otherwise).
    //   3. Zero external assembly references (mscorlib only) for fast empty-reply turnaround.
    internal static class Program {
        const uint GENERIC_READ = 0x80000000;
        const uint GENERIC_WRITE = 0x40000000;
        const uint OPEN_EXISTING = 3;
        const int ERROR_FILE_NOT_FOUND = 2;
        const int ERROR_PIPE_BUSY = 231;
        const int CONNECT_TIMEOUT_MS = 300;
        const int DEFAULT_READ_TIMEOUT_MS = 155000;
        const int MAX_BYTES = 4 * 1024 * 1024;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern SafeFileHandle CreateFileW(
            string lpFileName,
            uint dwDesiredAccess,
            uint dwShareMode,
            IntPtr lpSecurityAttributes,
            uint dwCreationDisposition,
            uint dwFlagsAndAttributes,
            IntPtr hTemplateFile);

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool WaitNamedPipeW(string lpNamedPipeName, int nTimeOut);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CancelIoEx(IntPtr hFile, IntPtr lpOverlapped);

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
            using (Stream stdout = Console.OpenStandardOutput()) {
                stdout.Write(bytes, 0, bytes.Length);
                stdout.Flush();
            }
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
            using (Stream stdin = Console.OpenStandardInput())
            using (var ms = new MemoryStream()) {
                byte[] buf = new byte[8192];
                int total = 0;
                int n;
                while ((n = stdin.Read(buf, 0, buf.Length)) > 0) {
                    if (total + n > MAX_BYTES) {
                        ms.Write(buf, 0, MAX_BYTES - total);
                        break;
                    }
                    ms.Write(buf, 0, n);
                    total += n;
                }
                if (ms.Length == 0) return "";
                byte[] all = ms.ToArray();
                int offset = (all.Length >= 3 && all[0] == 0xEF && all[1] == 0xBB && all[2] == 0xBF) ? 3 : 0;
                return Encoding.UTF8.GetString(all, offset, all.Length - offset);
            }
        }

        static SafeFileHandle ConnectPipe(string pipePath, int timeoutMs) {
            int deadline = Environment.TickCount + timeoutMs;
            while (true) {
                SafeFileHandle handle = CreateFileW(
                    pipePath, GENERIC_READ | GENERIC_WRITE, 0, IntPtr.Zero, OPEN_EXISTING, 0, IntPtr.Zero);
                if (!handle.IsInvalid) return handle;
                int err = Marshal.GetLastWin32Error();
                handle.Dispose();
                if (err == ERROR_FILE_NOT_FOUND) return null;
                if (err != ERROR_PIPE_BUSY) return null;
                int remaining = deadline - Environment.TickCount;
                if (remaining <= 0) return null;
                if (!WaitNamedPipeW(pipePath, remaining)) return null;
            }
        }

        static void Run(string eventName) {
            string rawPayload = ReadStdinText();
            string trimmed = rawPayload.Trim();
            string payloadJson = JsonMini.IsValidJsonObject(trimmed) ? trimmed : "{}";

            SafeFileHandle handle = ConnectPipe(ResolvePipePath(), CONNECT_TIMEOUT_MS);
            if (handle == null) {
                EmitFallback(eventName);
                return;
            }

            int readTimeoutMs = ResolveReadTimeoutMs();
            using (handle)
            using (var timer = new Timer(_ => {
                try {
                    if (!handle.IsClosed && !handle.IsInvalid) {
                        CancelIoEx(handle.DangerousGetHandle(), IntPtr.Zero);
                    }
                } catch { }
            }, null, readTimeoutMs, Timeout.Infinite))
            using (var fs = new FileStream(handle, FileAccess.ReadWrite, 4096, false)) {
                string reqJson = "{\"event\":" + JsonMini.Quote(eventName) + ",\"payload\":" + payloadJson + "}";
                byte[] reqBytes = Encoding.UTF8.GetBytes(reqJson);
                if (reqBytes.Length > MAX_BYTES) {
                    EmitFallback(eventName);
                    return;
                }
                byte[] header = new byte[4];
                header[0] = (byte)(reqBytes.Length & 0xFF);
                header[1] = (byte)((reqBytes.Length >> 8) & 0xFF);
                header[2] = (byte)((reqBytes.Length >> 16) & 0xFF);
                header[3] = (byte)((reqBytes.Length >> 24) & 0xFF);
                fs.Write(header, 0, 4);
                fs.Write(reqBytes, 0, reqBytes.Length);
                fs.Flush();

                byte[] respHeader = ReadExact(fs, 4);
                if (respHeader == null) {
                    EmitFallback(eventName);
                    return;
                }
                int respLen = respHeader[0] | (respHeader[1] << 8) | (respHeader[2] << 16) | (respHeader[3] << 24);
                if (respLen <= 0 || respLen > MAX_BYTES) {
                    EmitFallback(eventName);
                    return;
                }
                byte[] respBytes = ReadExact(fs, respLen);
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
            }
        }

        static byte[] ReadExact(Stream stream, int count) {
            byte[] buf = new byte[count];
            int offset = 0;
            while (offset < count) {
                int n = stream.Read(buf, offset, count - offset);
                if (n <= 0) return null;
                offset += n;
            }
            return buf;
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
