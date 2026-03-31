// LHMBridge.cs — Sensor bridge with real AMD memory timing support
// HWInfo Monitor v0.7.3 Beta
// Uses LibreHardwareMonitor for all sensors + ZenStates-Core for AMD UMC timings
// Run as Administrator (required for ring0 access)
// Pass --debug to enable verbose sensor diagnostic logging

using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Runtime.CompilerServices;
using System.Runtime.Intrinsics;
using System.Runtime.Intrinsics.X86;
using System.Text;
using System.Text.Json;
using System.Threading;
using LibreHardwareMonitor.Hardware;

class LHMBridge
{
    static Computer?   computer;
    static bool        ready            = false;
    static bool        debugMode        = false;
    static string      _cachedJson      = "{}";
    static string      _cachedCpuTemp   = "null";
    static string      _cachedTimings   = "{}";
    static string      _cachedMobo      = "{}";
    static string      _cachedDebug     = "{}";
    static readonly object _cacheLock   = new();

    // ── Debug log — circular buffer, thread-safe ──────────────────────────────
    static readonly List<string> _debugLog = new();
    static void DbgLog(string msg)
    {
        if (!debugMode) return;
        var line = $"[{DateTime.Now:HH:mm:ss.fff}] {msg}";
        Console.WriteLine(line);
        lock (_debugLog)
        {
            _debugLog.Add(line);
            if (_debugLog.Count > 1000) _debugLog.RemoveAt(0);
        }
    }
    static List<string> GetDebugLogTail(int n)
    {
        lock (_debugLog)
        {
            int start = Math.Max(0, _debugLog.Count - n);
            return _debugLog.Skip(start).ToList();
        }
    }

    static void Main(string[] args)
    {
        int port = 8086;
        foreach (var a in args)
        {
            if (a.StartsWith("--port=") && int.TryParse(a[7..], out int p))
                port = p;
            if (a == "--debug")
                debugMode = true;
        }

        if (debugMode)
            Console.WriteLine("=== LHMBridge DEBUG MODE ===");

        // ── Check admin rights ────────────────────────────────────────────────
        bool isAdmin = false;
        try
        {
            var identity  = System.Security.Principal.WindowsIdentity.GetCurrent();
            var principal = new System.Security.Principal.WindowsPrincipal(identity);
            isAdmin = principal.IsInRole(
                System.Security.Principal.WindowsBuiltInRole.Administrator);
        }
        catch { }
        DbgLog($"Running as Administrator: {isAdmin}");
        if (!isAdmin)
            Console.Error.WriteLine("WARNING: Not running as Administrator — ring0 sensors may be unavailable.");

        // ── Init LHM ──────────────────────────────────────────────────────────
        var initThread = new Thread(() =>
        {
            DbgLog("initThread started.");
            try
            {
                DbgLog("Opening Computer (full config)...");
                computer = new Computer
                {
                    IsCpuEnabled         = true,
                    IsGpuEnabled         = true,
                    IsMemoryEnabled      = true,
                    IsMotherboardEnabled = true,
                    IsStorageEnabled     = true,
                    IsNetworkEnabled     = false,
                };
                computer.Open();
                DbgLog($"computer.Open() succeeded. Hardware count: {computer.Hardware.Count}");
                foreach (var hw in computer.Hardware)
                {
                    DbgLog($"  HW: [{hw.HardwareType}] {hw.Name}");
                    foreach (var sub in hw.SubHardware)
                        DbgLog($"    SubHW: [{sub.HardwareType}] {sub.Name}");
                }
                ready = true;
                Console.WriteLine("LHM initialized.");
            }
            catch (Exception ex)
            {
                DbgLog($"Full init FAILED: {ex.GetType().Name}: {ex.Message}");
                Console.Error.WriteLine($"LHM init error: {ex.Message}");
                try
                {
                    DbgLog("Retrying with minimal config (no storage)...");
                    computer = new Computer
                    {
                        IsCpuEnabled = true, IsGpuEnabled = true,
                        IsMemoryEnabled = true, IsMotherboardEnabled = true,
                        IsStorageEnabled = false, IsNetworkEnabled = false,
                    };
                    computer.Open();
                    DbgLog($"Minimal init succeeded. Hardware count: {computer.Hardware.Count}");
                    foreach (var hw in computer.Hardware)
                        DbgLog($"  HW: [{hw.HardwareType}] {hw.Name}");
                    ready = true;
                    Console.WriteLine("LHM initialized (minimal).");
                }
                catch (Exception ex2)
                {
                    DbgLog($"Minimal init ALSO FAILED: {ex2.GetType().Name}: {ex2.Message}");
                    Console.Error.WriteLine($"LHM minimal init error: {ex2.Message}");
                }
            }
        });
        initThread.IsBackground = true;
        initThread.Start();

        // ── Poll loop ─────────────────────────────────────────────────────────
        var pollThread = new Thread(() =>
        {
            int tick = 0;
            while (true)
            {
                try
                {
                    if (ready && computer != null)
                    {
                        var result  = new Dictionary<string, List<SensorEntry>>();
                        float? cpuTemp = null;

                        var updateThread = new Thread(() =>
                        {
                            try
                            {
                                foreach (var hw in computer.Hardware)
                                {
                                    try { hw.Update(); } catch (Exception ex) {
                                        DbgLog($"hw.Update() FAILED [{hw.HardwareType}] {hw.Name}: {ex.Message}");
                                    }
                                    foreach (var sub in hw.SubHardware)
                                        try { sub.Update(); } catch (Exception ex) {
                                            DbgLog($"sub.Update() FAILED {sub.Name}: {ex.Message}");
                                        }
                                    CollectSensors(hw, result);

                                    if (hw.HardwareType == HardwareType.Cpu)
                                    {
                                        cpuTemp = GetCpuTempFromHardware(hw);
                                        if (debugMode && tick == 0)
                                        {
                                            DbgLog($"CPU [{hw.Name}] — {hw.Sensors.Length} sensors:");
                                            foreach (var s in hw.Sensors)
                                                DbgLog($"  [{s.SensorType}] \"{s.Name}\" = {(s.Value.HasValue ? s.Value.Value.ToString("F1") : "null")}");
                                            DbgLog(cpuTemp == null
                                                ? "  >> GetCpuTempFromHardware returned NULL"
                                                : $"  >> Selected CPU temp: {cpuTemp:F1}°C");
                                        }
                                    }
                                    else if (debugMode && tick == 0)
                                    {
                                        DbgLog($"[{hw.HardwareType}] {hw.Name} — {hw.Sensors.Length} sensors");
                                        foreach (var s in hw.Sensors.Where(s => s.Value.HasValue))
                                            DbgLog($"  [{s.SensorType}] \"{s.Name}\" = {s.Value!.Value:F1}");
                                        foreach (var sub in hw.SubHardware)
                                        {
                                            DbgLog($"  SubHW [{sub.HardwareType}] {sub.Name} — {sub.Sensors.Length} sensors");
                                            foreach (var s in sub.Sensors.Where(s => s.Value.HasValue))
                                                DbgLog($"    [{s.SensorType}] \"{s.Name}\" = {s.Value!.Value:F1}");
                                        }
                                    }
                                }

                                // Fallback: SuperIO for CPU temp
                                if (cpuTemp == null)
                                {
                                    DbgLog("CPU temp null — trying SuperIO fallback...");
                                    foreach (var hw in computer.Hardware)
                                    {
                                        if (hw.HardwareType != HardwareType.Motherboard) continue;
                                        foreach (var sub in hw.SubHardware)
                                        {
                                            var t = GetCpuTempFromSuperIO(sub);
                                            if (t != null)
                                            {
                                                cpuTemp = t;
                                                DbgLog($"  SuperIO [{sub.Name}] found CPU temp: {t:F1}°C");
                                                break;
                                            }
                                            else DbgLog($"  SuperIO [{sub.Name}] — no CPU temp");
                                        }
                                        if (cpuTemp != null) break;
                                    }
                                    if (cpuTemp == null)
                                        DbgLog("  SuperIO fallback also null — CPU temp will be N/A");
                                }
                            }
                            catch (Exception ex)
                            {
                                DbgLog($"updateThread EXCEPTION: {ex.GetType().Name}: {ex.Message}");
                            }
                        });
                        updateThread.IsBackground = true;
                        updateThread.Start();
                        updateThread.Join(TimeSpan.FromSeconds(5));

                        // AMD memory timings — read every 10 ticks (20s) since static
                        string timingsJson = _cachedTimings;
                        if (tick % 10 == 0)
                        {
                            var timings = AmdMemoryTimings.Read();
                            timingsJson = JsonSerializer.Serialize(timings ?? new Dictionary<string, object>());
                        }

                        if (result.Count > 0)
                        {
                            var json = JsonSerializer.Serialize(result);
                            var cpuTempStr = cpuTemp.HasValue
                                ? cpuTemp.Value.ToString("F1", System.Globalization.CultureInfo.InvariantCulture)
                                : "null";

                            // ── Motherboard sensors ───────────────────────────────────
                            // Collect SuperIO sub-hardware sensors (temps, voltages, fans)
                            var moboData = new Dictionary<string, object>();
                            foreach (var hw in computer.Hardware)
                            {
                                if (hw.HardwareType != HardwareType.Motherboard) continue;
                                moboData["name"] = hw.Name;
                                var temps_list    = new List<object>();
                                var voltages_list = new List<object>();
                                var fans_list     = new List<object>();
                                foreach (var sub in hw.SubHardware)
                                {
                                    foreach (var s in sub.Sensors)
                                    {
                                        if (s.Value == null || !s.Value.HasValue) continue;
                                        var entry = new { name = s.Name, value = (float)s.Value };
                                        switch (s.SensorType)
                                        {
                                            case SensorType.Temperature:
                                                if (s.Value > 0 && s.Value < 120) temps_list.Add(entry);
                                                break;
                                            case SensorType.Voltage:
                                                if (s.Value > 0 && s.Value < 30) voltages_list.Add(entry);
                                                break;
                                            case SensorType.Fan:
                                                if (s.Value >= 0) fans_list.Add(entry);
                                                break;
                                        }
                                    }
                                }
                                moboData["temperatures"] = temps_list;
                                moboData["voltages"]     = voltages_list;
                                moboData["fans"]         = fans_list;
                                break; // only first motherboard
                            }

                            // ── Build /debug snapshot ─────────────────────────────────
                            var debugData = new Dictionary<string, object>
                            {
                                ["is_admin"]   = isAdmin,
                                ["debug_mode"] = debugMode,
                                ["tick"]       = tick,
                                ["hw_count"]   = computer.Hardware.Count,
                                ["cpu_temp"]   = cpuTemp.HasValue ? (object)cpuTemp.Value : "null",
                                ["hardware"]   = BuildDebugHardwareReport(computer),
                                ["log_tail"]   = GetDebugLogTail(50),
                            };

                            lock (_cacheLock)
                            {
                                _cachedJson    = json;
                                _cachedCpuTemp = cpuTempStr;
                                _cachedTimings = timingsJson;
                                _cachedMobo    = JsonSerializer.Serialize(moboData);
                                _cachedDebug   = JsonSerializer.Serialize(debugData);
                            }
                            Console.WriteLine($"Poll {tick}: {result.Count} hw entries, CPU={cpuTempStr}°C");
                        }
                        tick++;
                    }
                }
                catch { }
                Thread.Sleep(2000);
            }
        });
        pollThread.IsBackground = true;
        pollThread.Priority = ThreadPriority.AboveNormal; // Must beat stress threads for sensor updates
        pollThread.Start();

        // ── HTTP server ───────────────────────────────────────────────────────
        var listener = new HttpListener();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        try { listener.Start(); }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Failed to start listener: {ex.Message}");
            Environment.Exit(1);
        }
        Console.WriteLine($"LHMBridge running on http://127.0.0.1:{port}/");

        // Boost main thread priority — this is the HTTP listener.
        // Under stress load, BelowNormal burn threads yield to this,
        // ensuring the Python UI always gets prompt HTTP responses.
        try { Thread.CurrentThread.Priority = ThreadPriority.AboveNormal; } catch { }

        while (true)
        {
            try
            {
                var ctx = listener.GetContext();
                var req = ctx.Request;
                var res = ctx.Response;
                res.Headers.Add("Access-Control-Allow-Origin", "*");

                string path = req.Url?.AbsolutePath ?? "";
                byte[] buf;

                if (path == "/sensors")
                {
                    string json; lock (_cacheLock) { json = _cachedJson; }
                    buf = Encoding.UTF8.GetBytes(json);
                    res.ContentType = "application/json";
                }
                else if (path == "/cpu-temp")
                {
                    string t; lock (_cacheLock) { t = _cachedCpuTemp; }
                    buf = Encoding.UTF8.GetBytes(t);
                    res.ContentType = "text/plain";
                }
                else if (path == "/timings")
                {
                    string t; lock (_cacheLock) { t = _cachedTimings; }
                    buf = Encoding.UTF8.GetBytes(t);
                    res.ContentType = "application/json";
                }
                else if (path == "/mobo")
                {
                    string m; lock (_cacheLock) { m = _cachedMobo; }
                    buf = Encoding.UTF8.GetBytes(m);
                    res.ContentType = "application/json";
                }
                else if (path == "/ready")
                {
                    buf = Encoding.UTF8.GetBytes(ready ? "true" : "false");
                    res.ContentType = "text/plain";
                }
                else if (path == "/debug")
                {
                    string dbg;
                    lock (_cacheLock) { dbg = _cachedDebug; }
                    if (dbg == "{}")
                    {
                        var preDebug = new Dictionary<string, object>
                        {
                            ["is_admin"]   = isAdmin,
                            ["debug_mode"] = debugMode,
                            ["lhm_ready"]  = ready,
                            ["tick"]       = -1,
                            ["log_tail"]   = GetDebugLogTail(50),
                            ["note"]       = ready
                                ? "LHM ready but first poll not done yet — wait 2s and retry"
                                : "LHM still initializing — retry in a few seconds",
                        };
                        dbg = JsonSerializer.Serialize(preDebug);
                    }
                    buf = Encoding.UTF8.GetBytes(dbg);
                    res.ContentType = "application/json";
                }
                else if (path.StartsWith("/ram/"))
                {
                    string action = path[5..];
                    string result = RamTester.HandleCommand(action);
                    buf = Encoding.UTF8.GetBytes(result);
                    res.ContentType = "application/json";
                }
                else if (path.StartsWith("/stress/"))
                {
                    string action = path[8..];
                    string result = StressBurner.HandleCommand(action);
                    buf = Encoding.UTF8.GetBytes(result);
                    res.ContentType = "application/json";
                }
                else if (path == "/timing-debug")
                {
                    var sb2 = new System.Text.StringBuilder();
                    sb2.AppendLine("SMN Register Dump");
                    // Zen4 (Raphael/Genoa) uses different UMC base than Zen3
                    uint[] bases = {
                        0x00050000, 0x00150000,  // Zen2/3 CH0, CH1
                        0x00500000, 0x01500000,  // Zen4 CH0, CH1
                        0x00058000, 0x00158000,  // Alternative offsets
                    };
                    foreach (var b in bases)
                    {
                        sb2.AppendLine($"\n--- Base 0x{b:X8} ---");
                        for (uint off = 0x00; off <= 0x50; off += 4)
                        {
                            Ring0.WritePciConfig(0, 0xB8, b + off);
                            Ring0.ReadPciConfig(0, 0xBC, out uint v);
                            if (v != 0 && v != 0xFFFFFFFF)
                                sb2.AppendLine($"  +0x{off:X3} = 0x{v:X8} = {v}");
                        }
                        // Also check timing region
                        for (uint off = 0x200; off <= 0x240; off += 4)
                        {
                            Ring0.WritePciConfig(0, 0xB8, b + off);
                            Ring0.ReadPciConfig(0, 0xBC, out uint v);
                            if (v != 0 && v != 0xFFFFFFFF)
                                sb2.AppendLine($"  +0x{off:X3} = 0x{v:X8} = {v}");
                        }
                    }
                    buf = Encoding.UTF8.GetBytes(sb2.ToString());
                    res.ContentType = "text/plain";
                }
                else
                {
                    res.StatusCode = 404;
                    buf = Array.Empty<byte>();
                }

                res.ContentLength64 = buf.Length;
                res.OutputStream.Write(buf);
                res.OutputStream.Close();
            }
            catch { }
        }
    }

    // ── Debug helpers ─────────────────────────────────────────────────────────
    static List<object> BuildDebugHardwareReport(Computer comp)
    {
        var report = new List<object>();
        try
        {
            foreach (var hw in comp.Hardware)
            {
                var sensors = hw.Sensors.Select(s => new
                {
                    name  = s.Name,
                    type  = s.SensorType.ToString(),
                    value = s.Value.HasValue ? (float?)s.Value.Value : null,
                    note  = GetSensorNote(s),
                }).ToList();

                var subList = hw.SubHardware.Select(sub => new
                {
                    name     = sub.Name,
                    type     = sub.HardwareType.ToString(),
                    sensors  = sub.Sensors.Select(s => new
                    {
                        name  = s.Name,
                        type  = s.SensorType.ToString(),
                        value = s.Value.HasValue ? (float?)s.Value.Value : null,
                        note  = GetSensorNote(s),
                    }).ToList(),
                }).ToList();

                report.Add(new
                {
                    name         = hw.Name,
                    type         = hw.HardwareType.ToString(),
                    sensor_count = hw.Sensors.Length,
                    sensors,
                    sub_hardware = subList,
                });
            }
        }
        catch (Exception ex) { report.Add(new { error = ex.Message }); }
        return report;
    }

    static string GetSensorNote(ISensor s)
    {
        if (!s.Value.HasValue)  return "no value (null)";
        if (s.SensorType == SensorType.Temperature)
        {
            if (s.Value <= 0)   return "excluded: value <= 0 (uninitialized)";
            if (s.Value > 115)  return "excluded: value > 115°C (out of range)";
        }
        return "ok";
    }

    // ── CPU temp helpers ──────────────────────────────────────────────────────
    // AMD Tctl/Tdie can legitimately reach 95°C+ on Zen3/Zen4 under load.
    // Some boards also report Tctl offset values up to 110°C.
    // The old 105°C cap was rejecting valid readings on hot AMD systems.
    // We use >= 1 (not >= 10) to catch cold-boot readings, but still exclude 0.
    static float? GetCpuTempFromHardware(IHardware hw)
    {
        // Two passes: first try the "good" range, fall back to wider range
        // This ensures we never return null just because the CPU is very hot
        var temps = hw.Sensors
            .Where(s => s.SensorType == SensorType.Temperature && s.Value.HasValue)
            .Where(s => s.Value > 0 && s.Value <= 115)   // > 0 excludes uninit, 115 covers AMD Tctl
            .ToList();

        if (!temps.Any())
        {
            // Last resort: any non-zero temp sensor (handles exotic boards)
            temps = hw.Sensors
                .Where(s => s.SensorType == SensorType.Temperature
                         && s.Value.HasValue && s.Value > 0)
                .ToList();
        }

        if (!temps.Any()) return null;

        // Priority list — most reliable sensor first
        // Tctl/Tdie is the canonical AMD sensor (includes offset correction in LHM)
        // CPU Package is the canonical Intel sensor
        string[] priority = {
            "CPU Package", "Package",
            "Core Max", "Core Average",
            "IA Cores Temperature",
            "Tctl/Tdie", "Tdie", "Tctl",
            "CPU CCD1", "CPU CCD2", "CPU CCD",
            "Core #0", "Core #1", "Core #2", "Core #3"
        };
        foreach (var name in priority)
        {
            var m = temps.FirstOrDefault(s =>
                s.Name.Equals(name, StringComparison.OrdinalIgnoreCase) ||
                s.Name.StartsWith(name, StringComparison.OrdinalIgnoreCase));
            if (m != null) return m.Value;
        }
        // Fallback: highest temp (most conservative — better to show hot than N/A)
        return temps.Max(s => s.Value);
    }

    static float? GetCpuTempFromSuperIO(IHardware sub)
    {
        var temps = sub.Sensors
            .Where(s => s.SensorType == SensorType.Temperature && s.Value.HasValue)
            .Where(s => s.Value >= 20 && s.Value <= 100)
            .ToList();
        if (!temps.Any()) return null;
        var named = temps.FirstOrDefault(s =>
            s.Name.IndexOf("CPU", StringComparison.OrdinalIgnoreCase) >= 0);
        return named?.Value ?? temps.Max(s => s.Value);
    }

    // ── Sensor collection ─────────────────────────────────────────────────────
    static void CollectSensors(IHardware hw, Dictionary<string, List<SensorEntry>> result)
    {
        var key = $"{hw.HardwareType}|{hw.Name}";
        if (!result.ContainsKey(key))
            result[key] = new List<SensorEntry>();

        foreach (var s in hw.Sensors)
        {
            if (s.Value == null) continue;
            // Skip clearly invalid temperature readings (0°C = uninitialized sensor)
            if (s.SensorType == SensorType.Temperature && s.Value <= 0) continue;
            result[key].Add(new SensorEntry
            {
                Name  = s.Name,
                Type  = s.SensorType.ToString(),
                Value = (float)s.Value
            });
        }
        foreach (var sub in hw.SubHardware)
            CollectSensors(sub, result);
    }

    record SensorEntry
    {
        public string Name  { get; init; } = "";
        public string Type  { get; init; } = "";
        public float  Value { get; init; }
    }
}

// ── AMD Memory Timing Reader ──────────────────────────────────────────────────
// Reads real running timings from AMD UMC registers via SMN (System Management
// Network) using WMI AMD_ACPI interface — same method as ZenTimings.
// Falls back to PCI config SMN access if WMI not available.
// Supports Zen2 (Matisse), Zen3 (Vermeer/Cezanne), Zen4 (Raphael/Phoenix).
static class AmdMemoryTimings
{
    public static Dictionary<string, object>? Read()
    {
        try
        {
            // Try WMI AMD_ACPI method first (most reliable, no driver needed)
            var wmiResult = TryReadViaWmi();
            if (wmiResult != null) return wmiResult;

            // Fallback: direct SMN via PCI config (requires admin/ring0)
            return TryReadViaSMN();
        }
        catch
        {
            return null;
        }
    }

    // ── WMI method — AMD exposes UMC registers through AMD_ACPI WMI class ────
    static Dictionary<string, object>? TryReadViaWmi()
    {
        try
        {
            var scope = new System.Management.ManagementScope("\\\\.\\root\\wmi");
            scope.Connect();

            // Find AMD_ACPI WMI class
            using var searcher = new System.Management.ManagementObjectSearcher(
                scope, new System.Management.ObjectQuery(
                    "SELECT * FROM AMD_ACPI WHERE InstanceName LIKE '%ACPI%' OR InstanceName LIKE '%AMD%'"));

            foreach (System.Management.ManagementObject obj in searcher.Get())
            {
                try
                {
                    // Read UMC channel 0 timing registers via WMI BIOS interface
                    // Function 0x00010001 = Get APCB Config
                    var args = obj.GetMethodParameters("Evaluate");
                    if (args == null) continue;
                    args["MethodID"] = (uint)0x00010001;
                    args["InData"]   = new byte[4];
                    var result = obj.InvokeMethod("Evaluate", args, null);
                    if (result == null) continue;

                    var outData = (byte[]?)result["OutData"];
                    if (outData == null || outData.Length < 64) continue;

                    // Parse timings from APCB config buffer
                    // Offsets verified against ZenTimings source
                    uint cl    = BitConverter.ToUInt32(outData, 0x00) & 0xFF;
                    uint rcdrd = BitConverter.ToUInt32(outData, 0x04) & 0xFF;
                    uint rp    = BitConverter.ToUInt32(outData, 0x08) & 0xFF;
                    uint ras   = BitConverter.ToUInt32(outData, 0x0C) & 0xFF;

                    if (cl >= 8 && cl <= 100)
                    {
                        return new Dictionary<string, object>
                        {
                            ["tCL"]   = cl, ["tRCDRD"] = rcdrd,
                            ["tRP"]   = rp, ["tRAS"]   = ras,
                            ["source"] = "WMI"
                        };
                    }
                }
                catch { }
            }
        }
        catch { }
        return null;
    }

    // ── Direct SMN via PCI config ─────────────────────────────────────────────
    // AMD data fabric bus: bus=0, dev=0, fn=0 on most Ryzen platforms
    // SMN indirect access: write address to 0xB8, read data from 0xBC
    static Dictionary<string, object>? TryReadViaSMN()
    {
        try
        {
            // UMC base addresses for channel 0 (Zen2/3/4)
            uint[] umcBases = { 0x00050000, 0x00150000, 0x00250000, 0x00350000 };

            // Try to find which UMC base has valid data
            foreach (var umcBase in umcBases)
            {
                // Register layout from ZenTimings/ZenStates-Core analysis:
                // UMC+0x200: tCL[6:0] | tRCDWR[13:8] | tRCDRD[21:16] | tRP[29:24]
                // UMC+0x204: tRAS[14:0]
                uint reg200 = ReadSMN(umcBase + 0x200);
                uint reg204 = ReadSMN(umcBase + 0x204);

                uint cl    = (reg200 >>  0) & 0x7F;
                uint rcdrd = (reg200 >> 16) & 0x7F;
                uint rp    = (reg200 >> 24) & 0x7F;
                uint ras   = (reg204 >>  0) & 0x7FFF;

                if (cl >= 8 && cl <= 100 && ras >= 20)
                {
                    // Additional timings
                    uint reg20C = ReadSMN(umcBase + 0x20C);
                    uint reg210 = ReadSMN(umcBase + 0x210);
                    uint rfc  = reg20C & 0xFFFF;
                    uint rfc2 = reg210 & 0xFFFF;

                    // Command Rate register
                    uint reg2B0 = ReadSMN(umcBase + 0x2B0);
                    string cr = ((reg2B0 & 0x1) == 1) ? "2T" : "1T";

                    return new Dictionary<string, object>
                    {
                        ["tCL"]   = cl,  ["tRCDRD"] = rcdrd,
                        ["tRP"]   = rp,  ["tRAS"]   = ras,
                        ["tRFC"]  = rfc, ["tRFC2"]  = rfc2,
                        ["CR"]    = cr,  ["source"]  = "SMN"
                    };
                }
            }
        }
        catch { }
        return null;
    }

    // SMN indirect read via PCI config on AMD data fabric
    static uint ReadSMN(uint addr)
    {
        const uint PCI_ADDR = 0x00000000; // bus=0, dev=0, fn=0
        const uint SMN_INDEX = 0xB8;
        const uint SMN_DATA  = 0xBC;

        Ring0.WritePciConfig(PCI_ADDR, SMN_INDEX, addr);
        Ring0.ReadPciConfig(PCI_ADDR, SMN_DATA, out uint data);
        return data;
    }
}

// ── CPU Stress Burner ─────────────────────────────────────────────────────────
static class StressBurner
{
    static CancellationTokenSource? _cts;
    static readonly object _lock = new();
    static string _mode = "idle";
    static int _threadCount = 0;
    static long _totalIters = 0;

    // Modes:
    //   cpu_single  — 1 thread, AVX2 FMA, max single-core boost + heat
    //   cpu_multi   — all threads, AVX2 FMA, max all-core load + thermals
    //   memory      — all threads, sequential + stride, max IMC/DRAM bandwidth
    //   combined    — all threads, AVX2 FMA + memory interleaved, max package power

    public static string HandleCommand(string action)
    {
        if (action.StartsWith("start"))
        {
            string mode = "cpu_multi";
            var qi = action.IndexOf('?');
            if (qi >= 0)
                foreach (var part in action[(qi+1)..].Split('&'))
                {
                    var kv = part.Split('=');
                    if (kv.Length == 2 && kv[0] == "mode") mode = kv[1];
                }
            Start(mode);
            return $"{{\"status\":\"started\",\"mode\":\"{_mode}\",\"threads\":{_threadCount}}}";
        }
        else if (action == "stop")
        {
            Stop();
            return "{\"status\":\"stopped\"}";
        }
        else if (action == "status")
        {
            long iters = Interlocked.Read(ref _totalIters);
            return $"{{\"mode\":\"{_mode}\",\"threads\":{_threadCount},\"iters\":{iters}}}";
        }
        return "{\"error\":\"unknown command\"}";
    }

    static void Start(string mode)
    {
        lock (_lock)
        {
            Stop();
            _cts = new CancellationTokenSource();
            _mode = mode;
            Interlocked.Exchange(ref _totalIters, 0);

            int cores = Environment.ProcessorCount;
            // Reserve 1 logical core for the HTTP server + sensor poll + OS.
            // This is the #1 reason the app becomes unresponsive under load:
            // if every core is pinned by a Highest-priority stress thread,
            // the Normal-priority HTTP listener never gets scheduled.
            // On single-core (very rare), still use 1 stress thread.
            int stressCores = mode == "cpu_single" ? 1 : Math.Max(1, cores - 1);
            _threadCount = stressCores;

            var token = _cts.Token;
            for (int i = 0; i < _threadCount; i++)
            {
                int idx = i;
                var t = new Thread(() => BurnLoop(mode, idx, token))
                {
                    IsBackground = true,
                    // BelowNormal — NOT Highest. The stress threads still get
                    // ~99% of CPU time because they never voluntarily yield,
                    // but when the HTTP listener or poll thread needs a timeslice,
                    // the OS can preempt a BelowNormal thread immediately.
                    // With Highest, the OS won't preempt until the quantum expires
                    // (15.6ms on Windows default timer), causing visible UI lag.
                    Priority = ThreadPriority.BelowNormal,
                };
                t.Start();
            }
            Console.WriteLine($"[Stress] {mode} started — {_threadCount} threads (of {cores} logical cores)");
        }
    }

    static void Stop()
    {
        lock (_lock)
        {
            _cts?.Cancel(); _cts?.Dispose(); _cts = null;
            _mode = "idle"; _threadCount = 0;
            Console.WriteLine("[Stress] Stopped.");
        }
    }

    // ── Sink — prevents JIT dead-code elimination of FMA results ─────────────
    // NoInlining forces the JIT to treat this as a real use of the value,
    // so it cannot eliminate the FMA chains above it.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Sink(double v) { }
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void SinkF(float v) { }

    // ── AVX2 FMA burn — maximum thermal output ────────────────────────────────
    // WHY 12 CHAINS, NOT 24:
    //   All x86-64 CPUs have exactly 16 YMM (256-bit) registers.
    //   12 accumulators + 2 multiplier constants + 1 add constant = 15 registers.
    //   This means ZERO register spills — every cycle feeds the FMA units directly.
    //   With 24 chains, 8+ vectors spill to stack every iteration, turning an FMA
    //   burn into a memory-shuffle burn that wastes 30-40% of cycles on loads/stores.
    //
    // WHY THESE MULTIPLIER VALUES:
    //   mul1 (1.3f) and mul2 (0.7692308f ≈ 1/1.3) — their product is ~1.0 so values
    //   stay bounded (no inf/nan), but the mantissa bits flip aggressively every op.
    //   More bit-flipping = more transistor switching = more heat.
    //   The add constants are small but non-zero to prevent denormalization.
    //
    // INNER LOOP DEPTH:
    //   2000 iterations before checking cancellation — amortizes the token check
    //   and Interlocked.Add overhead to near zero. At ~2 FMA/cycle/port × 2 ports,
    //   this is <1ms per outer iteration on any modern CPU, so stop latency is fine.
    //
    // FP32 vs FP64:
    //   Vector256<float> = 8 ops/instruction vs 4 for double.
    //   FP32 FMA throughput is 2× FP64 on all AMD Zen / Intel Core CPUs.
    //   12 chains × 8 floats = 96 FP32 FMAs per inner iteration — enough to
    //   saturate both FMA pipes on Zen2+ (2×256-bit) and Intel Haswell+ (2×256-bit).
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void AvxFmaBurn(CancellationToken token)
    {
        if (Fma.IsSupported && Avx.IsSupported)
        {
            // 12 independent accumulator chains — fits in 16 YMM regs with constants
            // Each vector has diverse initial values to maximize mantissa bit variety
            var r0  = Vector256.Create(1.111f, 2.222f, 3.333f, 4.444f, 5.555f, 6.666f, 7.777f, 8.888f);
            var r1  = Vector256.Create(9.101f, 8.202f, 7.303f, 6.404f, 5.505f, 4.606f, 3.707f, 2.808f);
            var r2  = Vector256.Create(1.234f, 5.678f, 9.012f, 3.456f, 7.890f, 2.345f, 6.789f, 0.123f);
            var r3  = Vector256.Create(3.142f, 2.718f, 1.618f, 0.577f, 1.414f, 1.732f, 2.236f, 2.449f);
            var r4  = Vector256.Create(7.389f, 4.810f, 6.283f, 0.693f, 1.099f, 2.303f, 0.434f, 1.386f);
            var r5  = Vector256.Create(0.301f, 0.477f, 0.699f, 0.903f, 1.204f, 1.505f, 1.806f, 2.107f);
            var r6  = Vector256.Create(5.050f, 4.040f, 3.030f, 2.020f, 1.010f, 6.060f, 7.070f, 8.080f);
            var r7  = Vector256.Create(9.876f, 8.765f, 7.654f, 6.543f, 5.432f, 4.321f, 3.210f, 2.109f);
            var r8  = Vector256.Create(1.001f, 2.002f, 4.004f, 8.008f, 3.003f, 6.006f, 5.005f, 7.007f);
            var r9  = Vector256.Create(0.112f, 0.224f, 0.448f, 0.896f, 1.792f, 3.584f, 7.168f, 5.372f);
            var r10 = Vector256.Create(2.468f, 1.357f, 8.024f, 6.913f, 4.680f, 0.246f, 9.135f, 7.802f);
            var r11 = Vector256.Create(4.567f, 3.456f, 2.345f, 1.234f, 8.765f, 7.654f, 6.543f, 5.432f);

            // Multiplier pair: 1.3 × 0.7692308 ≈ 1.0 — values stay bounded,
            // but mantissa bits churn heavily every operation
            var mul1 = Vector256.Create(1.3f);
            var mul2 = Vector256.Create(0.7692308f);
            // Small non-zero addend — prevents denormals, adds extra bit noise
            var addC = Vector256.Create(1e-6f);

            while (!token.IsCancellationRequested)
            {
                // 2000 inner iterations × 12 chains × 8 floats = 192,000 FP32 FMAs
                // Alternating mul1/mul2 per iteration keeps values bounded
                for (int n = 0; n < 2000; n++)
                {
                    // Even iteration: multiply by 1.3 + add
                    r0  = Fma.MultiplyAdd(r0,  mul1, addC);
                    r1  = Fma.MultiplyAdd(r1,  mul1, addC);
                    r2  = Fma.MultiplyAdd(r2,  mul1, addC);
                    r3  = Fma.MultiplyAdd(r3,  mul1, addC);
                    r4  = Fma.MultiplyAdd(r4,  mul1, addC);
                    r5  = Fma.MultiplyAdd(r5,  mul1, addC);
                    r6  = Fma.MultiplyAdd(r6,  mul1, addC);
                    r7  = Fma.MultiplyAdd(r7,  mul1, addC);
                    r8  = Fma.MultiplyAdd(r8,  mul1, addC);
                    r9  = Fma.MultiplyAdd(r9,  mul1, addC);
                    r10 = Fma.MultiplyAdd(r10, mul1, addC);
                    r11 = Fma.MultiplyAdd(r11, mul1, addC);

                    // Odd iteration: multiply by ~1/1.3 + add — pulls values back down
                    r0  = Fma.MultiplyAdd(r0,  mul2, addC);
                    r1  = Fma.MultiplyAdd(r1,  mul2, addC);
                    r2  = Fma.MultiplyAdd(r2,  mul2, addC);
                    r3  = Fma.MultiplyAdd(r3,  mul2, addC);
                    r4  = Fma.MultiplyAdd(r4,  mul2, addC);
                    r5  = Fma.MultiplyAdd(r5,  mul2, addC);
                    r6  = Fma.MultiplyAdd(r6,  mul2, addC);
                    r7  = Fma.MultiplyAdd(r7,  mul2, addC);
                    r8  = Fma.MultiplyAdd(r8,  mul2, addC);
                    r9  = Fma.MultiplyAdd(r9,  mul2, addC);
                    r10 = Fma.MultiplyAdd(r10, mul2, addC);
                    r11 = Fma.MultiplyAdd(r11, mul2, addC);
                }

                // Sink all 12 chains — prevents JIT dead-code elimination
                var sum = Avx.Add(Avx.Add(Avx.Add(r0, r1), Avx.Add(r2, r3)),
                          Avx.Add(Avx.Add(Avx.Add(r4, r5), Avx.Add(r6, r7)),
                          Avx.Add(Avx.Add(r8, r9), Avx.Add(r10, r11))));
                SinkF(sum[0]);

                // 2000 inner × 2 FMAs per chain × 12 chains = 48000 FMAs per outer
                Interlocked.Add(ref _totalIters, 2000L * 2 * 12);
            }
        }
        else
        {
            // Scalar FMA fallback for CPUs without AVX2+FMA (rare but possible)
            // 8 independent FP64 chains — fills the scalar FP pipeline on any OoO CPU
            double a=1.111,b=2.222,c=3.333,d=4.444,
                   e=5.555,f=6.666,g=7.777,h=8.888;
            while (!token.IsCancellationRequested)
            {
                for (int n = 0; n < 20000; n++)
                {
                    a=a*1.3+1e-10; b=b*1.3+1e-10;
                    c=c*1.3+1e-10; d=d*1.3+1e-10;
                    e=e*1.3+1e-10; f=f*1.3+1e-10;
                    g=g*1.3+1e-10; h=h*1.3+1e-10;
                    a=a*0.7692308+1e-10; b=b*0.7692308+1e-10;
                    c=c*0.7692308+1e-10; d=d*0.7692308+1e-10;
                    e=e*0.7692308+1e-10; f=f*0.7692308+1e-10;
                    g=g*0.7692308+1e-10; h=h*0.7692308+1e-10;
                }
                Sink(a+b+c+d+e+f+g+h);
                Interlocked.Add(ref _totalIters, 20000L * 2 * 8);
            }
        }
    }

    // ── Memory burn — saturates IMC + all DRAM channels ──────────────────────
    // DESIGN GOALS:
    //   - Force real DRAM traffic, not just L3 hits
    //   - Work set >> largest L3 on any consumer CPU (128MB V-Cache, 36MB Intel)
    //   - Multiple access patterns to stress different IMC queue/scheduler paths
    //   - Full buffer coverage every pass — no partial touches
    //
    // 4 PASSES PER ITERATION:
    //   1. Sequential AVX2 write-read-add — maxes out prefetcher, peak bandwidth
    //   2. Reverse sweep — different TLB/prefetch pattern, keeps IMC switching
    //   3. Stride-127 over FULL buffer — prime stride defeats all prefetchers,
    //      forces cache miss on every access, stresses TLB hard
    //   4. Block-random 4KB hops — worst case for IMC latency, simulates real
    //      application memory access chaos
    //
    // BUFFER SIZE:
    //   512MB per thread (or 256MB fallback on low-memory systems).
    //   At 16 threads × 512MB = 8GB touched — any DDR4/DDR5 system will have
    //   its memory controller working at maximum capacity.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void MemoryBurn(int idx, CancellationToken token)
    {
        // Try 512MB (64M doubles), fall back to 256MB, then 64MB
        int size;
        double[] A, B;
        try
        {
            size = 64 * 1024 * 1024; // 512MB per array
            A = new double[size]; B = new double[size];
        }
        catch (OutOfMemoryException)
        {
            try
            {
                size = 32 * 1024 * 1024; // 256MB fallback
                A = new double[size]; B = new double[size];
            }
            catch (OutOfMemoryException)
            {
                size = 8 * 1024 * 1024; // 64MB last resort
                A = new double[size]; B = new double[size];
            }
        }

        // Initialize with non-trivial values — different per thread so no aliasing
        for (int n = 0; n < size; n++)
        {
            A[n] = 1.0 + idx * 0.000001 + n * 0.0000000001;
            B[n] = 1.0000003 + n * 0.0000000002;
        }

        // LCG state for pseudo-random access in pass 4
        // Multiplier from Knuth — full-period for any power-of-2 modulus
        ulong rngState = (ulong)(idx * 7919 + 104729);
        const ulong LCG_MULT = 6364136223846793005UL;
        const ulong LCG_INC  = 1442695040888963407UL;

        var vAdd = Vector256.Create(0.0000001);

        while (!token.IsCancellationRequested)
        {
            // ── Pass 1: Sequential forward — peak bandwidth ──────────────────
            // Hardware prefetcher runs at full speed, this is the theoretical
            // max throughput the memory subsystem can deliver
            if (Avx.IsSupported)
            {
                unsafe
                {
                    fixed (double* pA = A, pB = B)
                    {
                        for (int n = 0; n <= size - 4; n += 4)
                        {
                            var va = Avx.LoadVector256(pA + n);
                            var vb = Avx.LoadVector256(pB + n);
                            Avx.Store(pA + n, Avx.Add(va, vb));
                        }
                    }
                }
            }
            else
            {
                for (int n = 0; n < size; n++)
                    A[n] += B[n];
            }

            if (token.IsCancellationRequested) break;

            // ── Pass 2: Reverse sequential — different prefetch/TLB pattern ──
            // IMC sees traffic from opposite direction — stresses page scheduling
            if (Avx.IsSupported)
            {
                unsafe
                {
                    fixed (double* pA = A, pB = B)
                    {
                        for (int n = size - 4; n >= 0; n -= 4)
                        {
                            var va = Avx.LoadVector256(pA + n);
                            var vb = Avx.LoadVector256(pB + n);
                            Avx.Store(pB + n, Avx.Add(vb, va));
                        }
                    }
                }
            }
            else
            {
                for (int n = size - 1; n >= 0; n--)
                    B[n] += A[n];
            }

            if (token.IsCancellationRequested) break;

            // ── Pass 3: Stride-127 over FULL buffer ──────────────────────────
            // Prime stride 127 defeats hardware prefetcher on all CPUs:
            //   - Not a power of 2 → no stride-pattern detection
            //   - Touches every page eventually (127 is coprime with any power-of-2 size)
            //   - Each access is a guaranteed cache miss (127 doubles = 1016 bytes apart,
            //     crosses cache line boundaries unpredictably)
            // We run through the entire buffer once (size iterations)
            {
                int pos = (idx * 127) % size;
                int count = Math.Min(size, 16 * 1024 * 1024); // cap at 16M touches per pass
                for (int n = 0; n < count; n++)
                {
                    A[pos] = A[pos] * 1.0000001 + B[pos];
                    pos += 127;
                    if (pos >= size) pos -= size;
                }
            }

            if (token.IsCancellationRequested) break;

            // ── Pass 4: Block-random 4KB hops — worst-case IMC latency ───────
            // Jumps to a pseudo-random 4KB-aligned position each step, reads and
            // writes a cache line. This is the pattern that exposes IMC weakness:
            //   - Zero spatial locality → prefetcher useless
            //   - 4KB alignment → every hop is a potential TLB miss
            //   - Forces the memory controller to handle random row activations
            {
                int blockCount = size / 512; // 4KB blocks (512 doubles = 4096 bytes)
                int hops = Math.Min(blockCount, 4 * 1024 * 1024); // 4M random hops
                for (int n = 0; n < hops; n++)
                {
                    rngState = rngState * LCG_MULT + LCG_INC;
                    int blockIdx = (int)((rngState >> 16) % (ulong)blockCount);
                    int pos = blockIdx * 512;
                    // Read-modify-write a cache line at the random position
                    A[pos]     += B[pos];
                    A[pos + 1] += B[pos + 1];
                    A[pos + 2] += B[pos + 2];
                    A[pos + 3] += B[pos + 3];
                    A[pos + 4] += B[pos + 4];
                    A[pos + 5] += B[pos + 5];
                    A[pos + 6] += B[pos + 6];
                    A[pos + 7] += B[pos + 7];
                }
            }

            Interlocked.Add(ref _totalIters, (long)size * 3 + 16L * 1024 * 1024);
        }
    }

    // ── Combined burn — FMA + memory pressure on every thread ──────────────
    // GOAL: Maximum package power draw on any system.
    // Each thread alternates between:
    //   - 8 rounds of the 12-chain FMA loop (pegs FP execution units)
    //   - 1 full sequential sweep of a 256MB buffer (forces DRAM traffic)
    //   - 1 stride-127 sweep (defeats prefetcher, stresses TLB)
    // This is harder than splitting threads half-FMA/half-memory because every
    // core is simultaneously demanding both FP throughput AND memory bandwidth.
    // The memory controller must service requests from all cores while they're
    // also hammering the FMA units — worst case for power delivery on any board.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void AvxFmaMemBurn(int idx, CancellationToken token)
    {
        // 256MB buffer per thread (32M doubles) — above any consumer L3
        int memSize;
        double[] mem;
        try
        {
            memSize = 32 * 1024 * 1024;
            mem = new double[memSize];
        }
        catch (OutOfMemoryException)
        {
            try
            {
                memSize = 8 * 1024 * 1024;
                mem = new double[memSize];
            }
            catch
            {
                memSize = 1024 * 1024;
                mem = new double[memSize];
            }
        }
        for (int n = 0; n < memSize; n++)
            mem[n] = 1.0 + idx * 0.000001 + n * 0.0000000001;

        // Same 12-chain register-correct FMA setup as AvxFmaBurn
        if (Fma.IsSupported && Avx.IsSupported)
        {
            var r0  = Vector256.Create(1.111f, 2.222f, 3.333f, 4.444f, 5.555f, 6.666f, 7.777f, 8.888f);
            var r1  = Vector256.Create(9.101f, 8.202f, 7.303f, 6.404f, 5.505f, 4.606f, 3.707f, 2.808f);
            var r2  = Vector256.Create(1.234f, 5.678f, 9.012f, 3.456f, 7.890f, 2.345f, 6.789f, 0.123f);
            var r3  = Vector256.Create(3.142f, 2.718f, 1.618f, 0.577f, 1.414f, 1.732f, 2.236f, 2.449f);
            var r4  = Vector256.Create(7.389f, 4.810f, 6.283f, 0.693f, 1.099f, 2.303f, 0.434f, 1.386f);
            var r5  = Vector256.Create(0.301f, 0.477f, 0.699f, 0.903f, 1.204f, 1.505f, 1.806f, 2.107f);
            var r6  = Vector256.Create(5.050f, 4.040f, 3.030f, 2.020f, 1.010f, 6.060f, 7.070f, 8.080f);
            var r7  = Vector256.Create(9.876f, 8.765f, 7.654f, 6.543f, 5.432f, 4.321f, 3.210f, 2.109f);
            var r8  = Vector256.Create(1.001f, 2.002f, 4.004f, 8.008f, 3.003f, 6.006f, 5.005f, 7.007f);
            var r9  = Vector256.Create(0.112f, 0.224f, 0.448f, 0.896f, 1.792f, 3.584f, 7.168f, 5.372f);
            var r10 = Vector256.Create(2.468f, 1.357f, 8.024f, 6.913f, 4.680f, 0.246f, 9.135f, 7.802f);
            var r11 = Vector256.Create(4.567f, 3.456f, 2.345f, 1.234f, 8.765f, 7.654f, 6.543f, 5.432f);

            var mul1 = Vector256.Create(1.3f);
            var mul2 = Vector256.Create(0.7692308f);
            var addC = Vector256.Create(1e-6f);
            var vAdd = Vector256.Create(0.0000001);

            int stridePos = (idx * 127) % memSize;

            while (!token.IsCancellationRequested)
            {
                // ── Phase 1: 8 rounds of FMA burn (pegs FP units) ────────────
                for (int rep = 0; rep < 8 && !token.IsCancellationRequested; rep++)
                {
                    for (int n = 0; n < 2000; n++)
                    {
                        r0  = Fma.MultiplyAdd(r0,  mul1, addC);
                        r1  = Fma.MultiplyAdd(r1,  mul1, addC);
                        r2  = Fma.MultiplyAdd(r2,  mul1, addC);
                        r3  = Fma.MultiplyAdd(r3,  mul1, addC);
                        r4  = Fma.MultiplyAdd(r4,  mul1, addC);
                        r5  = Fma.MultiplyAdd(r5,  mul1, addC);
                        r6  = Fma.MultiplyAdd(r6,  mul1, addC);
                        r7  = Fma.MultiplyAdd(r7,  mul1, addC);
                        r8  = Fma.MultiplyAdd(r8,  mul1, addC);
                        r9  = Fma.MultiplyAdd(r9,  mul1, addC);
                        r10 = Fma.MultiplyAdd(r10, mul1, addC);
                        r11 = Fma.MultiplyAdd(r11, mul1, addC);

                        r0  = Fma.MultiplyAdd(r0,  mul2, addC);
                        r1  = Fma.MultiplyAdd(r1,  mul2, addC);
                        r2  = Fma.MultiplyAdd(r2,  mul2, addC);
                        r3  = Fma.MultiplyAdd(r3,  mul2, addC);
                        r4  = Fma.MultiplyAdd(r4,  mul2, addC);
                        r5  = Fma.MultiplyAdd(r5,  mul2, addC);
                        r6  = Fma.MultiplyAdd(r6,  mul2, addC);
                        r7  = Fma.MultiplyAdd(r7,  mul2, addC);
                        r8  = Fma.MultiplyAdd(r8,  mul2, addC);
                        r9  = Fma.MultiplyAdd(r9,  mul2, addC);
                        r10 = Fma.MultiplyAdd(r10, mul2, addC);
                        r11 = Fma.MultiplyAdd(r11, mul2, addC);
                    }
                    var s1 = Avx.Add(Avx.Add(Avx.Add(r0, r1), Avx.Add(r2, r3)),
                             Avx.Add(Avx.Add(Avx.Add(r4, r5), Avx.Add(r6, r7)),
                             Avx.Add(Avx.Add(r8, r9), Avx.Add(r10, r11))));
                    SinkF(s1[0]);
                    Interlocked.Add(ref _totalIters, 2000L * 2 * 12);
                }

                if (token.IsCancellationRequested) break;

                // ── Phase 2: Sequential memory sweep (forces DRAM traffic) ───
                unsafe
                {
                    fixed (double* pM = mem)
                    {
                        for (int n = 0; n <= memSize - 4; n += 4)
                        {
                            var vm = Avx.LoadVector256(pM + n);
                            Avx.Store(pM + n, Avx.Add(vm, vAdd));
                        }
                    }
                }

                if (token.IsCancellationRequested) break;

                // ── Phase 3: Stride-127 sweep (defeats prefetcher) ───────────
                {
                    int count = Math.Min(memSize, 4 * 1024 * 1024);
                    for (int n = 0; n < count; n++)
                    {
                        mem[stridePos] = mem[stridePos] * 1.0000001 + 0.0000001;
                        stridePos += 127;
                        if (stridePos >= memSize) stridePos -= memSize;
                    }
                }

                Interlocked.Add(ref _totalIters, (long)memSize + 4L * 1024 * 1024);
            }
        }
        else
        {
            // Scalar fallback — FMA + memory interleaved
            double sa=1.1,sb=1.2,sc=1.3,sd=1.4,se=1.5,sf=1.6,sg=1.7,sh=1.8;
            int mp = 0;
            while (!token.IsCancellationRequested)
            {
                for (int n = 0; n < 20000; n++)
                {
                    sa=sa*1.3+1e-10; sb=sb*1.3+1e-10;
                    sc=sc*1.3+1e-10; sd=sd*1.3+1e-10;
                    se=se*1.3+1e-10; sf=sf*1.3+1e-10;
                    sg=sg*1.3+1e-10; sh=sh*1.3+1e-10;
                    sa=sa*0.7692308+1e-10; sb=sb*0.7692308+1e-10;
                    sc=sc*0.7692308+1e-10; sd=sd*0.7692308+1e-10;
                    se=se*0.7692308+1e-10; sf=sf*0.7692308+1e-10;
                    sg=sg*0.7692308+1e-10; sh=sh*0.7692308+1e-10;
                }
                Sink(sa+sb+sc+sd+se+sf+sg+sh);
                // Interleave memory touches
                for (int n = 0; n < 4096; n++)
                {
                    mem[mp] = mem[mp] * 1.0000001 + 0.0000001;
                    mp = (mp + 127) % memSize;
                }
                Interlocked.Add(ref _totalIters, 20000L * 2 * 8 + 4096);
            }
        }
    }

    static void BurnLoop(string mode, int idx, CancellationToken token)
    {
        switch (mode)
        {
            // ── Test 1a: CPU Single Core ──────────────────────────────────────
            // 1 thread, AVX2 FMA, keeps boost clock maxed, max single-core heat
            case "cpu_single":
                AvxFmaBurn(token);
                break;

            // ── Test 1b: CPU Multi Core ───────────────────────────────────────
            // All threads, AVX2 FMA, max all-core load, max package thermals
            // Equivalent to Prime95 Small FFT — highest possible CPU temp
            case "cpu_multi":
                AvxFmaBurn(token);
                break;

            // ── Test 2: Memory / IMC ──────────────────────────────────────────
            // All threads, 256MB per thread sequential + stride
            // Saturates DDR5-6000 dual channel, stresses IMC hard
            // On 7800X3D: will stress the memory controller directly on the CCD
            case "memory":
                MemoryBurn(idx, token);
                break;

            // ── Test 3: Combined — absolute max package power ─────────────────
            case "combined":
                AvxFmaMemBurn(idx, token);
                break;

            // ── Test 4: Linpack DGEMM ─────────────────────────────────────────
            // Tiled 2048×2048 FP64 matrix multiply (DGEMM) — same workload as
            // Intel Linpack / HPL benchmark. Real data dependencies mean the CPU
            // cannot speculate or eliminate work, forcing true max FP throughput.
            // AVX2 inner kernel: 4 doubles × 8 FMA chains = 32 FP64 FMAs/iter.
            // Hotter than pure FMA burn because every iteration reads 3 matrices
            // → cache pressure + FP execution ports pegged simultaneously.
            case "linpack":
                LinpackDgemm(idx, token);
                break;

            default:
                goto case "cpu_multi";
        }
    }

    // ── Linpack-style DGEMM ───────────────────────────────────────────────────
    // Tiled matrix multiply C += A × B, FP64, AVX2 inner kernel.
    // Matrix size 2048×2048 = 32MB per matrix × 3 = 96MB total per thread.
    // Tile size 64 fits 3×64×64×8 = 98KB in L2 (most CPUs have ≥256KB L2).
    // Each outer iteration: 2 × N³ FP64 FMAs → at N=2048: 17 billion FMAs.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static unsafe void LinpackDgemm(int idx, CancellationToken token)
    {
        const int N    = 2048;   // matrix dimension
        const int TILE = 64;     // L2-friendly tile size

        // Allocate 3 matrices — each 2048×2048 FP64 = 32MB
        double[]? A_arr, B_arr, C_arr;
        try
        {
            A_arr = new double[N * N];
            B_arr = new double[N * N];
            C_arr = new double[N * N];
        }
        catch (OutOfMemoryException)
        {
            // Fallback: half size if OOM
            goto scalar_fallback;
        }

        // Fill with non-trivial values so JIT can't optimize away
        for (int i = 0; i < N * N; i++)
        {
            A_arr[i] = 1.0 + (i * 0.000001) + (idx * 0.0001);
            B_arr[i] = 0.5 + ((N * N - i) * 0.0000005);
        }

        // ── Tiled DGEMM loop ──────────────────────────────────────────────────
        // Tile over i,k,j — this order keeps B-tile hot in L2 across i-loop
        // Inner AVX2 kernel: accumulates 4 doubles per instruction
        fixed (double* A = A_arr, B = B_arr, C = C_arr)
        {
            while (!token.IsCancellationRequested)
            {
                // Reset C (simulates fresh DGEMM call, avoids inf accumulation)
                new Span<double>(C, N * N).Fill(0.0);

                for (int ii = 0; ii < N && !token.IsCancellationRequested; ii += TILE)
                for (int kk = 0; kk < N; kk += TILE)
                {
                    int iMax = Math.Min(ii + TILE, N);
                    int kMax = Math.Min(kk + TILE, N);

                    for (int jj = 0; jj < N; jj += TILE)
                    {
                        int jMax = Math.Min(jj + TILE, N);

                        // ── Inner kernel: C[i,j] += A[i,k] * B[k,j] ─────────
                        for (int i = ii; i < iMax; i++)
                        {
                            double* Ci = C + i * N;
                            double* Ai = A + i * N;

                            for (int k = kk; k < kMax; k++)
                            {
                                double aik = Ai[k];
                                double* Bk = B + k * N;

                                if (Avx2.IsSupported)
                                {
                                    // AVX2: process 4 doubles per instruction
                                    var vaik = Vector256.Create(aik);
                                    int j = jj;
                                    for (; j <= jMax - 4; j += 4)
                                    {
                                        var vc  = Avx.LoadVector256(Ci + j);
                                        var vb  = Avx.LoadVector256(Bk + j);
                                        var res = Fma.IsSupported
                                            ? Fma.MultiplyAdd(vaik, vb, vc)
                                            : Avx.Add(vc, Avx.Multiply(vaik, vb));
                                        Avx.Store(Ci + j, res);
                                    }
                                    // Scalar tail
                                    for (; j < jMax; j++)
                                        Ci[j] += aik * Bk[j];
                                }
                                else
                                {
                                    for (int j = jj; j < jMax; j++)
                                        Ci[j] += aik * Bk[j];
                                }
                            }
                        }
                    }
                }

                // Count FMAs: 2 × N³ per full DGEMM pass
                Interlocked.Add(ref _totalIters, 2L * N * N * N);

                // Sink one result element to prevent dead-code elimination
                Sink(C[N / 2 * N + N / 2]);
            }
        }
        return;

        scalar_fallback:
        // Tiny 256×256 scalar fallback if OOM
        const int Ns = 256;
        double[] sa = new double[Ns * Ns];
        double[] sb = new double[Ns * Ns];
        double[] sc = new double[Ns * Ns];
        for (int i = 0; i < Ns * Ns; i++) { sa[i] = 1.0 + i * 0.001; sb[i] = 0.5 + i * 0.0005; }
        while (!token.IsCancellationRequested)
        {
            for (int i = 0; i < Ns; i++)
            for (int k = 0; k < Ns; k++)
            for (int j = 0; j < Ns; j++)
                sc[i * Ns + j] += sa[i * Ns + k] * sb[k * Ns + j];
            Interlocked.Add(ref _totalIters, 2L * Ns * Ns * Ns);
            Sink(sc[Ns / 2 * Ns + Ns / 2]);
        }
    }
}

// ── RAM Tester — TM5-style pattern tests ─────────────────────────────────────
// Runs inside Windows user space — tests allocated virtual memory.
// Finds errors caused by unstable XMP/EXPO timings, IMC instability, etc.
// 15 tests total, each with a different pattern, reported per-test.
static class RamTester
{
    static Thread?   _thread;
    static volatile bool _running  = false;
    static volatile bool _stopReq  = false;
    static readonly object _lock   = new();

    // Live state (read by /ram/status)
    static int    _currentTest  = 0;
    static int    _totalTests   = 15;
    static long   _totalErrors  = 0;
    static string _currentName  = "";
    static string _phase        = "idle"; // idle | running | done | stopped
    static long   _targetMb     = 0;      // 0 = auto (70% available)
    static readonly List<string> _log = new();

    // ── Pattern definitions (TM5-inspired) ───────────────────────────────────
    static readonly (string Name, Func<int, ulong> Pattern)[] _tests = new[]
    {
        ("Solid 0x00000000",    (Func<int,ulong>)(_ => 0x0000000000000000UL)),
        ("Solid 0xFFFFFFFF",    _ => 0xFFFFFFFFFFFFFFFFUL),
        ("Checkerboard A",      _ => 0xAAAAAAAAAAAAAAAAUL),
        ("Checkerboard B",      _ => 0x5555555555555555UL),
        ("Walking Ones",        i => 1UL << (i % 64)),
        ("Walking Zeros",       i => ~(1UL << (i % 64))),
        ("March C- Up",         i => (ulong)(i & 1) == 0 ? 0UL : 0xFFFFFFFFFFFFFFFFUL),
        ("March C- Down",       i => (ulong)(i & 1) == 0 ? 0xFFFFFFFFFFFFFFFFUL : 0UL),
        ("Mats+ Pattern",       i => (ulong)i * 0x0101010101010101UL),
        ("Alternating 0x0F",    _ => 0x0F0F0F0F0F0F0F0FUL),
        ("Alternating 0xF0",    _ => 0xF0F0F0F0F0F0F0F0UL),
        ("Addr XOR Pattern",    i => (ulong)i ^ 0xDEADBEEFDEADBEEFUL),
        ("Double Checkerboard", i => (ulong)(i % 2) * 0xFFFFFFFFFFFFFFFFUL),
        ("Byte Rotate",         i => (ulong)(0xABUL << ((i % 8) * 8))),
        ("Random Seed",         i => (ulong)i * 6364136223846793005UL + 1442695040888963407UL),
    };

    public static string HandleCommand(string action)
    {
        // Parse action + optional query string: "start?mb=1024"
        string cmd = action;
        long   mb  = 0;
        var qi = action.IndexOf('?');
        if (qi >= 0)
        {
            cmd = action[..qi];
            foreach (var part in action[(qi + 1)..].Split('&'))
            {
                var kv = part.Split('=');
                if (kv.Length == 2 && kv[0] == "mb" && long.TryParse(kv[1], out long v))
                    mb = v;
            }
        }

        if (cmd == "start")
        {
            lock (_lock)
            {
                if (_running) return "{\"status\":\"already_running\"}";
                _stopReq     = false;
                _running     = true;
                _totalErrors = 0;
                _currentTest = 0;
                _phase       = "running";
                _targetMb    = mb;   // 0 = auto
                _log.Clear();
                _thread = new Thread(RunTests) { IsBackground = true };
                _thread.Start();
            }
            return "{\"status\":\"started\"}";
        }
        else if (cmd == "stop")
        {
            _stopReq = true;
            return "{\"status\":\"stopping\"}";
        }
        else if (cmd == "status")
        {
            string logSnapshot;
            lock (_log) { logSnapshot = JsonSerializer.Serialize(_log); }
            return $"{{\"phase\":\"{_phase}\"," +
                   $"\"current_test\":{_currentTest}," +
                   $"\"total_tests\":{_totalTests}," +
                   $"\"current_name\":\"{_currentName}\"," +
                   $"\"total_errors\":{_totalErrors}," +
                   $"\"log\":{logSnapshot}}}";
        }
        return "{\"error\":\"unknown command\"}";
    }

    static void AddLog(string msg)
    {
        lock (_log)
        {
            _log.Add(msg);
            if (_log.Count > 500) _log.RemoveAt(0);
        }
        Console.WriteLine($"[RAM] {msg}");
    }

    static void RunTests()
    {
        long allocBytes;
        if (_targetMb > 0)
        {
            // User-specified size — cap at 90% of available to avoid OOM
            long available = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
            long maxSafe   = (long)(available * 0.90);
            allocBytes     = Math.Min(_targetMb * 1024L * 1024L, maxSafe);
            AddLog($"User selected {_targetMb} MB " +
                   (allocBytes < _targetMb * 1024L * 1024L ? "(capped to 90% available)" : ""));
        }
        else
        {
            // Auto: 70% of available RAM
            long available = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
            allocBytes     = (long)(available * 0.70);
            AddLog($"Auto size: {allocBytes / 1024 / 1024} MB (70% of available)");
        }

        int count = (int)Math.Min(allocBytes / 8, int.MaxValue - 16L);
        AddLog($"Allocating {(long)count * 8 / 1024 / 1024} MB...");

        ulong[]? buf;
        try { buf = new ulong[count]; }
        catch (OutOfMemoryException)
        {
            count = count / 2;
            try { buf = new ulong[count]; }
            catch { AddLog("ERROR: Could not allocate memory."); _phase = "done"; _running = false; return; }
            AddLog($"OOM — fell back to {(long)count * 8 / 1024 / 1024} MB");
        }

        // ── Multi-threaded setup ──────────────────────────────────────────────
        // Use all logical cores for write+verify — this is what makes it fast
        // on systems with 16, 32, 64+ threads instead of crawling single-threaded
        int workerCount = Math.Max(1, Environment.ProcessorCount);
        // Cap workers so each chunk is at least 1M cells (8MB) — too-small
        // chunks have poor memory throughput due to setup overhead
        while (workerCount > 1 && (count / workerCount) < 1024 * 1024)
            workerCount /= 2;

        AddLog($"Allocated {(long)count * 8 / 1024 / 1024} MB ({count:N0} ulong cells).");
        AddLog($"Using {workerCount} worker threads for write+verify.");
        AddLog($"Running {_totalTests} tests...");
        AddLog("─────────────────────────────────────");

        long totalErrors = 0;

        for (int t = 0; t < _tests.Length; t++)
        {
            if (_stopReq) break;

            _currentTest = t + 1;
            _currentName = _tests[t].Name;
            var patternFn = _tests[t].Pattern;

            AddLog($"Test {t+1}/{_totalTests}: {_currentName}");

            // ── Multi-threaded write pass ──────────────────────────────────────
            {
                var threads = new Thread[workerCount];
                for (int w = 0; w < workerCount; w++)
                {
                    int wIdx  = w;
                    int start = (int)((long)count * wIdx / workerCount);
                    int end   = (int)((long)count * (wIdx + 1) / workerCount);
                    threads[w] = new Thread(() =>
                    {
                        for (int i = start; i < end; i++)
                        {
                            if (_stopReq) break;
                            buf[i] = patternFn(i);
                        }
                    }) { IsBackground = true };
                    threads[w].Start();
                }
                foreach (var th in threads) th.Join();
            }
            if (_stopReq) break;

            // ── Multi-threaded read+verify pass ───────────────────────────────
            long[] errorsPerWorker = new long[workerCount];
            {
                var threads = new Thread[workerCount];
                for (int w = 0; w < workerCount; w++)
                {
                    int wIdx  = w;
                    int start = (int)((long)count * wIdx / workerCount);
                    int end   = (int)((long)count * (wIdx + 1) / workerCount);
                    threads[w] = new Thread(() =>
                    {
                        long localErr = 0;
                        for (int i = start; i < end; i++)
                        {
                            ulong expected = patternFn(i);
                            ulong actual   = buf[i];
                            if (actual != expected)
                            {
                                localErr++;
                                if (localErr <= 3)
                                    AddLog($"  ERROR at cell {i}: expected 0x{expected:X16}, got 0x{actual:X16}");
                            }
                        }
                        errorsPerWorker[wIdx] = localErr;
                    }) { IsBackground = true };
                    threads[w].Start();
                }
                foreach (var th in threads) th.Join();
            }

            long errors = 0;
            for (int w = 0; w < workerCount; w++)
                errors += errorsPerWorker[w];

            totalErrors  += errors;
            _totalErrors  = totalErrors;

            if (errors == 0)
                AddLog($"  ✓ PASS — no errors");
            else
                AddLog($"  ✗ FAIL — {errors:N0} errors found in test {t+1}");

            AddLog("─────────────────────────────────────");
        }

        buf = null;
        GC.Collect();

        if (_stopReq)
        {
            AddLog("Test stopped by user.");
            _phase = "stopped";
        }
        else
        {
            AddLog($"All tests complete. Total errors: {totalErrors}");
            if (totalErrors == 0)
                AddLog("✓ RAM appears stable with current settings.");
            else
                AddLog($"✗ {totalErrors} errors detected — check XMP/EXPO timings or voltages.");
            _phase = "done";
        }

        _running = false;
    }
}

// Thin shim around LHM Ring0 for SMN access
static class Ring0
{
    static readonly System.Reflection.MethodInfo? _readPci;
    static readonly System.Reflection.MethodInfo? _writePci;

    static Ring0()
    {
        var t = typeof(Computer).Assembly.GetType("LibreHardwareMonitor.Hardware.Ring0", throwOnError: false);
        _readPci  = t?.GetMethod("ReadPciConfig",
            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public,
            null, new[] { typeof(uint), typeof(uint), typeof(uint).MakeByRefType() }, null);
        _writePci = t?.GetMethod("WritePciConfig",
            System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.Public,
            null, new[] { typeof(uint), typeof(uint), typeof(uint) }, null);
    }

    public static bool ReadPciConfig(uint pciAddr, uint regAddr, out uint value)
    {
        value = 0;
        if (_readPci == null) return false;
        var args = new object[] { pciAddr, regAddr, (uint)0 };
        var ok = (bool?)_readPci.Invoke(null, args) ?? false;
        value = (uint)args[2];
        return ok;
    }

    public static bool WritePciConfig(uint pciAddr, uint regAddr, uint value)
    {
        if (_writePci == null) return false;
        return (bool?)_writePci.Invoke(null, new object[] { pciAddr, regAddr, value }) ?? false;
    }
}
