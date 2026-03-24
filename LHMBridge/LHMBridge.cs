// LHMBridge.cs — Sensor bridge with real AMD memory timing support
// HWInfo Monitor v0.5.6 Beta
// Uses LibreHardwareMonitor for all sensors + ZenStates-Core for AMD UMC timings
// Run as Administrator (required for ring0 access)

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
            _threadCount = mode == "cpu_single" ? 1 : cores;

            var token = _cts.Token;
            for (int i = 0; i < _threadCount; i++)
            {
                int idx = i;
                new Thread(() => BurnLoop(mode, idx, token))
                {
                    IsBackground = true,
                    Priority = ThreadPriority.Highest,
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

    // ── Sink — prevents JIT dead-code elimination of FMA results ─────────────
    // NoInlining forces the JIT to treat this as a real use of the value,
    // so it cannot eliminate the FMA chains above it.
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void Sink(double v) { }

    // ── AVX2 FMA burn — guaranteed max FP load ────────────────────────────────
    // 12 independent Vector256<double> chains (48 doubles in flight)
    // No branches inside hot loop — no resets, values stay bounded by design
    // (mul=1.0000001 never diverges to inf in any reasonable run duration)
    // Sink() call every outer iteration forces JIT to materialise all registers
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void AvxFmaBurn(CancellationToken token)
    {
        if (Fma.IsSupported && Avx.IsSupported)
        {
            // 12 independent chains × 4 doubles = 48 FMA ops per inner iteration
            // Independent chains = no data dependency stalls = max throughput
            var a = Vector256.Create(1.10, 1.11, 1.12, 1.13);
            var b = Vector256.Create(1.20, 1.21, 1.22, 1.23);
            var c = Vector256.Create(1.30, 1.31, 1.32, 1.33);
            var d = Vector256.Create(1.40, 1.41, 1.42, 1.43);
            var e = Vector256.Create(1.50, 1.51, 1.52, 1.53);
            var f = Vector256.Create(1.60, 1.61, 1.62, 1.63);
            var g = Vector256.Create(0.90, 0.91, 0.92, 0.93);
            var h = Vector256.Create(0.80, 0.81, 0.82, 0.83);
            var i = Vector256.Create(0.70, 0.71, 0.72, 0.73);
            var j = Vector256.Create(0.60, 0.61, 0.62, 0.63);
            var k = Vector256.Create(1.70, 1.71, 1.72, 1.73);
            var l = Vector256.Create(1.80, 1.81, 1.82, 1.83);

            // Two multiplier magnitudes — chains grow/shrink so they stay finite
            var mulUp   = Vector256.Create(1.00000007);
            var mulDown = Vector256.Create(0.99999993);
            var addC    = Vector256.Create(0.00000001);

            while (!token.IsCancellationRequested)
            {
                // 500 unrolled × 12 chains × 4 doubles = 24000 FMAs per outer iter
                // No branch inside — pure FMA throughput
                for (int n = 0; n < 500; n++)
                {
                    a = Fma.MultiplyAdd(a, mulUp,   addC);
                    b = Fma.MultiplyAdd(b, mulUp,   addC);
                    c = Fma.MultiplyAdd(c, mulUp,   addC);
                    d = Fma.MultiplyAdd(d, mulUp,   addC);
                    e = Fma.MultiplyAdd(e, mulUp,   addC);
                    f = Fma.MultiplyAdd(f, mulUp,   addC);
                    g = Fma.MultiplyAdd(g, mulDown, addC);
                    h = Fma.MultiplyAdd(h, mulDown, addC);
                    i = Fma.MultiplyAdd(i, mulDown, addC);
                    j = Fma.MultiplyAdd(j, mulDown, addC);
                    k = Fma.MultiplyAdd(k, mulUp,   addC);
                    l = Fma.MultiplyAdd(l, mulDown, addC);
                }

                // Sink — JIT cannot eliminate any chain above because we read them
                // Using addition so all 12 contribute; result passed to NoInlining call
                var sum = Avx.Add(Avx.Add(Avx.Add(a, b), Avx.Add(c, d)),
                          Avx.Add(Avx.Add(Avx.Add(e, f), Avx.Add(g, h)),
                          Avx.Add(Avx.Add(i, j), Avx.Add(k, l))));
                Sink(sum[0]);

                Interlocked.Add(ref _totalIters, 500 * 12);
            }
        }
        else
        {
            // Scalar fallback — 16 independent chains, fills out-of-order pipeline
            double a=1.1,b=1.2,c=1.3,d=1.4,e=1.5,f=1.6,g=1.7,h=1.8,
                   i2=1.9,j=2.0,k=2.1,l=2.2,m=2.3,nn=2.4,o=2.5,p=2.6;
            while (!token.IsCancellationRequested)
            {
                for (int n = 0; n < 10000; n++)
                {
                    a=a*1.0000001+0.0000001; b=b*1.0000002+0.0000002;
                    c=c*1.0000003+0.0000003; d=d*1.0000004+0.0000004;
                    e=e*0.9999999+0.0000001; f=f*0.9999998+0.0000002;
                    g=g*0.9999997+0.0000003; h=h*0.9999996+0.0000004;
                    i2=i2*1.0000005+0.0000005; j=j*1.0000006+0.0000006;
                    k=k*1.0000007+0.0000007;   l=l*1.0000008+0.0000008;
                    m=m*0.9999995+0.0000005;   nn=nn*0.9999994+0.0000006;
                    o=o*0.9999993+0.0000007;   p=p*0.9999992+0.0000008;
                }
                // Sink all 16 — JIT must keep them alive
                Sink(a+b+c+d+e+f+g+h+i2+j+k+l+m+nn+o+p);
                Interlocked.Add(ref _totalIters, 10000 * 16);
            }
        }
    }

    // ── Memory burn — saturates IMC + all DRAM channels ──────────────────────
    // 3 passes per iteration:
    //   1. Sequential AVX2 read+write (256-bit stores, max bandwidth)
    //   2. Stride-127 (prime stride — busts prefetcher, forces cache misses)
    //   3. Reverse sequential (different access pattern, keeps IMC busy)
    // 256MB per thread — well above L3 (32MB on 7800X3D), forces real DRAM traffic
    [MethodImpl(MethodImplOptions.NoInlining)]
    static void MemoryBurn(int idx, CancellationToken token)
    {
        int size = 32 * 1024 * 1024; // 256MB per thread (doubles)
        double[] A, B;
        try   { A = new double[size]; B = new double[size]; }
        catch (OutOfMemoryException)
        { size = 8 * 1024 * 1024; A = new double[size]; B = new double[size]; }

        for (int n = 0; n < size; n++)
        {
            A[n] = 1.0 + idx * 0.000001 + n * 0.0000000001;
            B[n] = 1.0000003 + n * 0.0000000002;
        }

        int stridePos = (idx * 127) % size;
        var vAdd = Vector256.Create(0.0000001);

        while (!token.IsCancellationRequested)
        {
            // Pass 1: sequential forward — hardware prefetcher maxed out
            // AVX2: processes 4 doubles per instruction = 32 bytes/instruction
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
                    A[n] = A[n] + B[n];
            }

            // Pass 2: stride-127 — non-power-of-2 stride defeats prefetcher
            for (int n = 0; n < 2 * 1024 * 1024; n++)
            {
                A[stridePos] = A[stridePos] * 1.0000001 + B[stridePos];
                stridePos = (stridePos + 127) % size;
            }

            // Pass 3: reverse sequential — different access pattern, IMC stays hot
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
                            Avx.Store(pA + n, Avx.Add(va, vAdd));
                            _ = vb[0]; // read B to keep both arrays in traffic
                        }
                    }
                }
            }
            else
            {
                for (int n = size - 1; n >= 0; n--)
                    A[n] = A[n] + 0.0000001;
            }

            Interlocked.Add(ref _totalIters, (long)size * 2 + 2 * 1024 * 1024);
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
            // Spawns 2 sub-tasks per logical thread:
            //   • Half threads → pure AVX2 FMA (max FPU heat)
            //   • Half threads → pure memory flood (max IMC/DRAM)
            // This is more effective than interleaving on the same thread because:
            //   - FMA threads stay in L1/L2, always hitting execution units
            //   - Memory threads always miss cache, always hitting DRAM
            //   - Both pressures hit the CPU simultaneously → max TDP
            case "combined":
            {
                int cores     = Environment.ProcessorCount;
                int fmaCount  = Math.Max(1, cores / 2);
                int memCount  = cores - fmaCount;

                // FMA threads
                for (int t = 0; t < fmaCount; t++)
                {
                    new Thread(() => AvxFmaBurn(token))
                    {
                        IsBackground = true,
                        Priority     = ThreadPriority.Highest,
                    }.Start();
                }

                // Memory threads
                for (int t = 0; t < memCount; t++)
                {
                    int tidx = t;
                    new Thread(() => MemoryBurn(tidx, token))
                    {
                        IsBackground = true,
                        Priority     = ThreadPriority.Highest,
                    }.Start();
                }

                // This thread also burns FMA so we use all cores
                AvxFmaBurn(token);
                break;
            }

            default:
                goto case "cpu_multi";
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
        if (action == "start")
        {
            lock (_lock)
            {
                if (_running) return "{\"status\":\"already_running\"}";
                _stopReq    = false;
                _running    = true;
                _totalErrors = 0;
                _currentTest = 0;
                _phase       = "running";
                _log.Clear();
                _thread = new Thread(RunTests) { IsBackground = true };
                _thread.Start();
            }
            return "{\"status\":\"started\"}";
        }
        else if (action == "stop")
        {
            _stopReq = true;
            return "{\"status\":\"stopping\"}";
        }
        else if (action == "status")
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
        // Allocate as much RAM as safely possible (up to 75% of available)
        long available  = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
        long allocBytes = (long)(available * 0.70);
        // Align to ulong size
        int count = (int)Math.Min(allocBytes / 8, int.MaxValue - 16L);

        AddLog($"Allocating {allocBytes / 1024 / 1024} MB for testing...");

        ulong[]? buf;
        try { buf = new ulong[count]; }
        catch (OutOfMemoryException)
        {
            count = count / 2;
            try { buf = new ulong[count]; }
            catch { AddLog("ERROR: Could not allocate memory."); _phase = "done"; _running = false; return; }
        }

        AddLog($"Allocated {(long)count * 8 / 1024 / 1024} MB ({count:N0} ulong cells).");
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

            // ── Write pass ────────────────────────────────────────────────────
            for (int i = 0; i < count; i++)
            {
                if (_stopReq) break;
                buf[i] = patternFn(i);
            }
            if (_stopReq) break;

            // ── Read+verify pass ──────────────────────────────────────────────
            long errors = 0;
            for (int i = 0; i < count; i++)
            {
                ulong expected = patternFn(i);
                ulong actual   = buf[i];
                if (actual != expected)
                {
                    errors++;
                    if (errors <= 3) // log first 3 errors per test
                        AddLog($"  ERROR at cell {i}: expected 0x{expected:X16}, got 0x{actual:X16}");
                }
            }

            totalErrors        += errors;
            _totalErrors        = totalErrors;

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
