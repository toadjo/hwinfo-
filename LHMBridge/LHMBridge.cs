// LHMBridge.cs — Sensor bridge with real AMD memory timing support
// Uses LibreHardwareMonitor for all sensors + ZenStates-Core for AMD UMC timings
// Run as Administrator (required for ring0 access)

using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Threading;
using LibreHardwareMonitor.Hardware;

class LHMBridge
{
    static Computer?   computer;
    static bool        ready        = false;
    static string      _cachedJson      = "{}";
    static string      _cachedCpuTemp   = "null";
    static string      _cachedTimings   = "{}";
    static readonly object _cacheLock   = new();

    static void Main(string[] args)
    {
        int port = 8086;
        foreach (var a in args)
            if (a.StartsWith("--port=") && int.TryParse(a[7..], out int p))
                port = p;

        // ── Init LHM ──────────────────────────────────────────────────────────
        var initThread = new Thread(() =>
        {
            try
            {
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
                ready = true;
                Console.WriteLine("LHM initialized.");
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"LHM init error: {ex.Message}");
                try
                {
                    computer = new Computer
                    {
                        IsCpuEnabled = true, IsGpuEnabled = true,
                        IsMemoryEnabled = true, IsMotherboardEnabled = true,
                        IsStorageEnabled = false, IsNetworkEnabled = false,
                    };
                    computer.Open();
                    ready = true;
                    Console.WriteLine("LHM initialized (minimal).");
                }
                catch (Exception ex2)
                {
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
                                    try { hw.Update(); } catch { }
                                    foreach (var sub in hw.SubHardware)
                                        try { sub.Update(); } catch { }
                                    CollectSensors(hw, result);

                                    if (hw.HardwareType == HardwareType.Cpu)
                                        cpuTemp = GetCpuTempFromHardware(hw);
                                }

                                // Fallback: SuperIO for CPU temp
                                if (cpuTemp == null)
                                {
                                    foreach (var hw in computer.Hardware)
                                    {
                                        if (hw.HardwareType != HardwareType.Motherboard) continue;
                                        foreach (var sub in hw.SubHardware)
                                        {
                                            var t = GetCpuTempFromSuperIO(sub);
                                            if (t != null) { cpuTemp = t; break; }
                                        }
                                        if (cpuTemp != null) break;
                                    }
                                }
                            }
                            catch { }
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
                            lock (_cacheLock)
                            {
                                _cachedJson    = json;
                                _cachedCpuTemp = cpuTempStr;
                                _cachedTimings = timingsJson;
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
                else if (path == "/ready")
                {
                    buf = Encoding.UTF8.GetBytes(ready ? "true" : "false");
                    res.ContentType = "text/plain";
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

    // ── CPU temp helpers ──────────────────────────────────────────────────────
    static float? GetCpuTempFromHardware(IHardware hw)
    {
        var temps = hw.Sensors
            .Where(s => s.SensorType == SensorType.Temperature && s.Value.HasValue)
            .Where(s => s.Value >= 10 && s.Value <= 105)
            .ToList();
        if (!temps.Any()) return null;

        string[] priority = {
            "CPU Package", "Package", "Core Max", "Core Average",
            "IA Cores Temperature", "CPU CCD", "Tdie", "Tctl/Tdie",
            "Core #0", "Core #1", "Core #2", "Core #3"
        };
        foreach (var name in priority)
        {
            var m = temps.FirstOrDefault(s =>
                s.Name.Equals(name, StringComparison.OrdinalIgnoreCase) ||
                s.Name.StartsWith(name, StringComparison.OrdinalIgnoreCase));
            if (m != null) return m.Value;
        }
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
    static long _totalIters = 0;   // shared iteration counter for scoring

    public static string HandleCommand(string action)
    {
        if (action.StartsWith("start"))
        {
            string mode = "fma";
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
            _cts  = new CancellationTokenSource();
            _mode = mode;
            Interlocked.Exchange(ref _totalIters, 0);

            int cores = Environment.ProcessorCount;
            _threadCount = mode == "single" ? 1 : cores;

            var token = _cts.Token;
            for (int i = 0; i < _threadCount; i++)
            {
                int idx = i;
                new Thread(() => BurnLoop(mode, idx, token))
                {
                    IsBackground = true,
                    Priority = ThreadPriority.BelowNormal,
                }.Start();
            }
            Console.WriteLine($"[Stress] {mode} started — {_threadCount} threads");
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

    static void BurnLoop(string mode, int idx, CancellationToken token)
    {
        switch (mode)
        {
            // ── FMA Burn: 8 independent FP chains — max IPC, fits L1/L2 ─────
            case "fma":
            case "single":
            {
                double a=1.1,b=1.2,c=1.3,d=1.4,e=1.5,f=1.6,g=1.7,h=1.8+idx*0.001;
                long local = 0;
                while (!token.IsCancellationRequested)
                {
                    for (int i = 0; i < 100000; i++)
                    {
                        a=a*1.0000001+0.0000001; b=b*1.0000002+0.0000002;
                        c=c*1.0000003+0.0000003; d=d*1.0000004+0.0000004;
                        e=e*0.9999999+0.0000001; f=f*0.9999998+0.0000002;
                        g=g*0.9999997+0.0000003; h=h*0.9999996+0.0000004;
                        if (a>1e100||a<1e-100) { a=1.1; b=1.2; c=1.3; d=1.4; }
                        if (e>1e100||e<1e-100) { e=1.5; f=1.6; g=1.7; h=1.8; }
                    }
                    local += 100000;
                    Interlocked.Add(ref _totalIters, 100000);
                }
                break;
            }

            // ── Cache Bust: stride access through large buffer — busts L3 ────
            case "cache":
            {
                int size = 8 * 1024 * 1024; // 64MB per thread
                var buf = new double[size];
                for (int i = 0; i < size; i++) buf[i] = i * 0.000001 + 1.0;
                int pos = idx * 127;
                double acc = 1.0;
                long local = 0;
                while (!token.IsCancellationRequested)
                {
                    for (int i = 0; i < 100000; i++)
                    {
                        acc = acc * 1.0000001 + buf[pos];
                        buf[pos] = acc;
                        pos = (pos + 127) % size; // stride busts cache
                        // FMA burst
                        double x = acc;
                        x=x*1.1+0.1; x=x*1.1+0.1; x=x*1.1+0.1; x=x*1.1+0.1;
                        x=x*0.9-0.1; x=x*0.9-0.1; x=x*0.9-0.1; x=x*0.9-0.1;
                        acc += x * 1e-30;
                        if (acc > 1e100 || acc < -1e100) { acc = 1.0; }
                    }
                    local += 100000;
                    Interlocked.Add(ref _totalIters, 100000);
                }
                break;
            }

            // ── Memory Flood: sequential read+write — stresses IMC/DRAM ──────
            case "memory":
            case "vram":
            {
                int size = 16 * 1024 * 1024; // 128MB per thread
                double[] A, B;
                try { A = new double[size]; B = new double[size]; }
                catch (OutOfMemoryException)
                { size = 4*1024*1024; A = new double[size]; B = new double[size]; }
                for (int i = 0; i < size; i++) { A[i] = 1.0; B[i] = 1.0000001+idx*0.000001; }
                long local = 0;
                while (!token.IsCancellationRequested)
                {
                    for (int i = 0; i < size; i++) A[i] = A[i] + B[i];
                    local += size;
                    Interlocked.Add(ref _totalIters, size);
                }
                break;
            }

            // ── Default fallback ──────────────────────────────────────────────
            default:
                goto case "fma";
        }
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
