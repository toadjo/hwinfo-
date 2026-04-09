// ════════════════════════════════════════════════════════════════════════════
// MemoryTimings_PawnIO.cs — HardwareToad v0.8.2
//
// Memory timing reader using shared PawnIO connection (PawnIO.cs).
//
// Module: MchbarIO.amx (custom, ships with HardwareToad)
//   ioctl_pci_read(bus, dev, func, reg) -> dword
//   ioctl_io_in_dword(port)             -> dword
//   ioctl_io_out_dword(port, value)     -> void
//   ioctl_io_in_byte(port)              -> byte     (new, for SuperIO)
//   ioctl_io_out_byte(port, value)      -> void     (new, for SuperIO)
//
// All hardware access goes through I/O ports only (CF8/CFC for PCI config,
// iGPU IOBAR index/data for MCHBAR) — no physical memory mapping needed.
// ════════════════════════════════════════════════════════════════════════════

using System;
using System.Collections.Generic;

static class MemoryTimings
{
    // ── I/O helpers (delegate to shared PawnIO) ───────────────────────────────
    static uint? IoIn(uint port) => PawnIO.IoInDword(port);
    static void IoOut(uint port, uint val) => PawnIO.IoOutDword(port, val);
    static uint? PciRead(uint bus, uint dev, uint fn, uint reg) => PawnIO.PciRead(bus, dev, fn, reg);
    static void PciWrite(uint bus, uint dev, uint fn, uint reg, uint val) => PawnIO.PciWrite(bus, dev, fn, reg, val);

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
        if (!PawnIO.Init()) return null;
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
