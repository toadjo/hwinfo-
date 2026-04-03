// ════════════════════════════════════════════════════════════════════════════
// MemoryTimings_PawnIO.cs — HardwareToad v0.8.2
//
// Uses PawnIOLib.dll (C:\Program Files\PawnIO\PawnIOLib.dll) with the real
// pawnio_open / pawnio_load / pawnio_execute C API — not raw DeviceIoControl.
//
// Module: LpcIO.amx (installed by PawnIO setup)
//   ioctl_io_in_dword(port)         -> dword
//   ioctl_io_out_dword(port, value) -> void
//
// All hardware access goes through I/O ports only (CF8/CFC for PCI config,
// iGPU IOBAR index/data for MCHBAR) — no physical memory mapping needed,
// nothing that Windows policy can block.
// ════════════════════════════════════════════════════════════════════════════

using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;

static class MemoryTimings
{
    // ── PawnIOLib P/Invoke ────────────────────────────────────────────────────
    const string DLL = "PawnIOLib.dll"; // local-first, falls back to system if present

    [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
    static extern int pawnio_open(out IntPtr handle);

    [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
    static extern int pawnio_load(IntPtr handle, byte[] module, UIntPtr size);

    [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
    static extern int pawnio_execute(
        IntPtr handle,
        [MarshalAs(UnmanagedType.LPStr)] string function,
        ulong[] inData,  UIntPtr inSize,
        ulong[] outData, UIntPtr outSize,
        out UIntPtr outCount);

    [DllImport(DLL, CallingConvention = CallingConvention.Cdecl)]
    static extern void pawnio_close(IntPtr handle);

    // ── Module search paths ───────────────────────────────────────────────────
    static readonly string[] ModulePaths = {
        Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "LpcIO.amx"), // local fallback
        @"C:\Program Files\PawnIO\Modules\LpcIO.amx",
        @"C:\ProgramData\PawnIO\Modules\LpcIO.amx",
        @"C:\Program Files\PawnIO\LpcIO.amx",
    };

    // ── State ─────────────────────────────────────────────────────────────────
    static IntPtr _handle = IntPtr.Zero;
    static bool   _ready  = false;
    static bool   _tried  = false;
    static readonly object _lock = new();

    static bool Init()
    {
        lock (_lock)
        {
            if (_tried) return _ready;
            _tried = true;

            if (!File.Exists(DLL))
            {
                LHMBridge.DbgLog($"[MemTimings] PawnIOLib.dll not found at {DLL}");
                return false;
            }

            string? mod = null;

            LHMBridge.DbgLog("[MemTimings] Searching for LpcIO.amx in:");
            foreach (var p in ModulePaths)
                LHMBridge.DbgLog("  - " + p);

            foreach (var p in ModulePaths)
                if (File.Exists(p)) { mod = p; break; }

            if (mod == null)
            {
                LHMBridge.DbgLog("[MemTimings] LpcIO.amx not found — check PawnIO installed modules");
                return false;
            }

            try
            {
                int r = pawnio_open(out _handle);
                if (r != 0 || _handle == IntPtr.Zero)
                { LHMBridge.DbgLog($"[MemTimings] pawnio_open failed: 0x{r:X}"); return false; }

                byte[] blob = File.ReadAllBytes(mod);
                r = pawnio_load(_handle, blob, (UIntPtr)blob.Length);
                if (r != 0)
                {
                    LHMBridge.DbgLog($"[MemTimings] pawnio_load failed: 0x{r:X}");
                    pawnio_close(_handle); _handle = IntPtr.Zero; return false;
                }

                LHMBridge.DbgLog($"[MemTimings] PawnIO + LpcIO ready ({mod})");
                _ready = true;
                return true;
            }
            catch (Exception ex)
            { LHMBridge.DbgLog($"[MemTimings] Init exception: {ex.Message}"); return false; }
        }
    }

    // ── Execute a LpcIO IOCTL ─────────────────────────────────────────────────
    static ulong[]? Exec(string fn, ulong[] args, int outSz = 1)
    {
        if (_handle == IntPtr.Zero) return null;
        var outBuf = new ulong[Math.Max(outSz, 1)];
        try
        {
            int r = pawnio_execute(_handle, fn,
                args, (UIntPtr)args.Length,
                outBuf, (UIntPtr)outSz,
                out _);
            if (r != 0) { LHMBridge.DbgLog($"[MemTimings] {fn} => 0x{r:X}"); return null; }
            return outBuf;
        }
        catch (Exception ex) { LHMBridge.DbgLog($"[MemTimings] {fn} ex: {ex.Message}"); return null; }
    }

    // ── I/O port helpers (LpcIO) ──────────────────────────────────────────────
    static uint? IoIn(uint port)
    {
        var r = Exec("ioctl_io_in_dword", new ulong[] { port });
        return r == null ? null : (uint?)((uint)r[0]);
    }

    static void IoOut(uint port, uint val)
        => Exec("ioctl_io_out_dword", new ulong[] { port, val }, 0);

    // ── PCI config via CF8/CFC I/O ports ─────────────────────────────────────
    static uint? PciRead(uint bus, uint dev, uint fn, uint reg)
    {
        uint addr = 0x80000000u | (bus << 16) | (dev << 11) | (fn << 8) | (reg & 0xFCu);
        IoOut(0xCF8, addr);
        return IoIn(0xCFC);
    }

    static void PciWrite(uint bus, uint dev, uint fn, uint reg, uint val)
    {
        uint addr = 0x80000000u | (bus << 16) | (dev << 11) | (fn << 8) | (reg & 0xFCu);
        IoOut(0xCF8, addr);
        IoOut(0xCFC, val);
    }

    // ── MCHBAR read via iGPU I/O BAR index/data ──────────────────────────────
    // Write MCHBAR-relative offset to IOBAR+0, read result from IOBAR+4.
    static uint? MchbarRead(uint iobar, uint offset)
    {
        IoOut(iobar, offset);
        return IoIn(iobar + 4);
    }

    // ── AMD SMN indirect ──────────────────────────────────────────────────────
    static uint ReadSMN(uint addr)
    {
        PciWrite(0, 0, 0, 0xB8, addr);
        return PciRead(0, 0, 0, 0xBC) ?? 0;
    }

    // ── Public entry ──────────────────────────────────────────────────────────
    public static Dictionary<string, object>? Read()
    {
        if (!Init()) return null;
        return ReadAmd() ?? ReadIntel();
    }

    // ── AMD ───────────────────────────────────────────────────────────────────
    static Dictionary<string, object>? ReadAmd()
    {
        uint[] bases = { 0x00050000, 0x00150000, 0x00250000, 0x00350000 };
        foreach (var b in bases)
        {
            uint r200 = ReadSMN(b + 0x200);
            uint r204 = ReadSMN(b + 0x204);
            uint tCL    = (r200 >>  0) & 0x7F;
            uint tRCDRD = (r200 >> 16) & 0x7F;
            uint tRP    = (r200 >> 24) & 0x7F;
            uint tRAS   = (r204 >>  0) & 0x7FFF;
            if (tCL < 8 || tCL > 100 || tRAS < 20) continue;

            uint tRFC  = ReadSMN(b + 0x20C) & 0xFFFF;
            uint tRFC2 = ReadSMN(b + 0x210) & 0xFFFF;
            uint cr    = ReadSMN(b + 0x2B0) & 1;
            LHMBridge.DbgLog($"[MemTimings] AMD: tCL={tCL} tRCDRD={tRCDRD} tRP={tRP} tRAS={tRAS}");
            return new Dictionary<string, object>
            {
                ["tCL"] = tCL, ["tRCDRD"] = tRCDRD, ["tRP"] = tRP, ["tRAS"] = tRAS,
                ["tRFC"] = tRFC, ["tRFC2"] = tRFC2, ["CR"] = cr == 1 ? "2T" : "1T",
                ["source"] = "SMN",
            };
        }
        LHMBridge.DbgLog("[MemTimings] AMD: no valid UMC");
        return null;
    }

    // ── Intel ─────────────────────────────────────────────────────────────────
    static Dictionary<string, object>? ReadIntel()
    {
        // iGPU = B:0 D:2 F:0 — try PCI config offset 0x10 first (I/O BAR)
        uint? iobarRaw = PciRead(0, 2, 0, 0x10);
        if (iobarRaw == null || (iobarRaw.Value & 1) == 0)
        {
            // Fallback to offset 0x20 (used on some generations)
            iobarRaw = PciRead(0, 2, 0, 0x20);
        }

        if (iobarRaw == null || (iobarRaw.Value & 1) == 0)
        { LHMBridge.DbgLog($"[MemTimings] Intel: no iGPU I/O BAR (raw=0x{iobarRaw.GetValueOrDefault():X})"); return null; }

        uint iobar = iobarRaw.Value & 0xFFFCu;
        if (iobar == 0) { LHMBridge.DbgLog("[MemTimings] Intel: IOBAR base is 0"); return null; }
        LHMBridge.DbgLog($"[MemTimings] Intel: iGPU IOBAR=0x{iobar:X}");

        int gen = GetIntelGen();
        LHMBridge.DbgLog($"[MemTimings] Intel: gen={gen}");

        if (gen >= 12) return ReadAlderLake(iobar);
        if (gen >= 6)  return ReadSkylake(iobar);
        return null;
    }

    // Gen 6–11: TC_DBP @ 0x4000, TC_RAP @ 0x4004
    static Dictionary<string, object>? ReadSkylake(uint iobar)
    {
        var dbp = MchbarRead(iobar, 0x4000);
        var rap = MchbarRead(iobar, 0x4004);
        if (dbp == null || rap == null) { LHMBridge.DbgLog("[MemTimings] Skylake: IOBAR read failed"); return null; }

        uint tCL  = (dbp.Value >> 16) & 0x1F;
        uint tRCD = (dbp.Value >>  0) & 0x1F;
        uint tRP  = (dbp.Value >>  8) & 0x1F;
        uint tCWL = (dbp.Value >> 24) & 0x1F;
        uint tRAS = (rap.Value >>  0) & 0xFF;
        uint tWR  = (rap.Value >> 24) & 0xFF;

        if (tCL < 4 || tCL > 50) { LHMBridge.DbgLog($"[MemTimings] Skylake: bad tCL={tCL}"); return null; }
        LHMBridge.DbgLog($"[MemTimings] Skylake: tCL={tCL} tRCD={tRCD} tRP={tRP} tRAS={tRAS}");
        return new Dictionary<string, object>
        {
            ["tCL"] = tCL, ["tRCD"] = tRCD, ["tRP"] = tRP, ["tRAS"] = tRAS,
            ["tCWL"] = tCWL, ["tWR"] = tWR, ["source"] = "MCHBAR",
        };
    }

    // Gen 12+: TC_PRE @ 0xE000, TC_ACT @ 0xE008, TC_ODT @ 0xE01C, TC_WR @ 0xE010
    static Dictionary<string, object>? ReadAlderLake(uint iobar)
    {
        var pre = MchbarRead(iobar, 0xE000);
        var act = MchbarRead(iobar, 0xE008);
        var odt = MchbarRead(iobar, 0xE01C);
        var wr  = MchbarRead(iobar, 0xE010);
        if (pre == null || act == null || odt == null) { LHMBridge.DbgLog("[MemTimings] AlderLake: IOBAR read failed"); return null; }

        uint tRP  = (pre.Value >>  0) & 0x7F;
        uint tRAS = (pre.Value >>  8) & 0x7F;
        uint tRCD = (act.Value >> 24) & 0x7F;
        uint tCL  = (odt.Value >>  0) & 0x7F;
        uint tCWL = wr != null ? (wr.Value >>  0) & 0xFF : 0;
        uint tWR  = wr != null ? (wr.Value >> 16) & 0xFF : 0;

        if (tCL == 0 || tCL > 80)
        {
            var alt = MchbarRead(iobar, 0xE050);
            if (alt != null) tCL = alt.Value & 0x7F;
        }
        if (tCL < 4 || tCL > 80) { LHMBridge.DbgLog($"[MemTimings] AlderLake: bad tCL={tCL}"); return null; }

        LHMBridge.DbgLog($"[MemTimings] AlderLake: tCL={tCL} tRCD={tRCD} tRP={tRP} tRAS={tRAS}");
        return new Dictionary<string, object>
        {
            ["tCL"] = tCL, ["tRCD"] = tRCD, ["tRP"] = tRP, ["tRAS"] = tRAS,
            ["tCWL"] = tCWL, ["tWR"] = tWR, ["source"] = "MCHBAR",
        };
    }

    // Intel gen from Host Bridge Device ID
    static int GetIntelGen()
    {
        var v = PciRead(0, 0, 0, 0x00);
        if (v == null) return 0;
        uint did = v.Value >> 16;
        if ((did & 0xFFF0) is 0x1900 or 0x1910) return 6;
        if ((did & 0xFFF0) is 0x5900 or 0x5910) return 7;
        if ((did & 0xFF00) == 0x3E00) return 8;
        if ((did & 0xFF00) == 0x9B00) return 10;
        if ((did & 0xFF00) == 0x4C00) return 11;
        if ((did & 0xFF00) == 0x4600) return 12;
        if ((did & 0xFF00) == 0xA700) return 13;
        if ((did & 0xFF00) == 0x7D00) return 14;
        if ((did & 0xFF00) == 0xA800) return 15;
        if (did >= 0x4600) return 12;
        return 6;
    }
}
