// ════════════════════════════════════════════════════════════════════════════
// SuperIO_PawnIO.cs — HardwareToad v0.8.2
//
// Reads fan RPM, temperatures, and voltages directly from SuperIO chips
// via PawnIO byte I/O as a fallback when LHM's WinRing0 is blocked.
//
// Supported chip families:
//   - ITE IT87xx (IT8686E, IT8688E, IT8689E, IT8628E, IT8625E, IT8613E,
//                 IT8620E, IT8721F, IT8728F, IT8771E, IT8772E)
//   - Nuvoton NCT67xx (NCT6775F, NCT6776F, NCT6779D, NCT6791D, NCT6792D,
//                       NCT6795D, NCT6796D, NCT6797D, NCT6798D)
//
// Protocol: Standard ISA SuperIO via index/data port pairs (0x2E/0x2F
// or 0x4E/0x4F). Enter extended mode, read chip ID, select HW monitor
// LDN, read base address, then read sensor registers.
// ════════════════════════════════════════════════════════════════════════════

using System;
using System.Collections.Generic;

static class SuperIOReader
{
    // ── Result types ──────────────────────────────────────────────────────────
    public class SensorData
    {
        public string ChipName   { get; set; } = "Unknown";
        public ushort ChipId     { get; set; }
        public List<FanReading>  Fans  { get; set; } = new();
        public List<TempReading> Temps { get; set; } = new();
    }

    public record FanReading(string Name, int Rpm);
    public record TempReading(string Name, float Celsius);

    // ── State ─────────────────────────────────────────────────────────────────
    static SensorData? _cached;
    static DateTime    _lastRead = DateTime.MinValue;
    static bool        _probed   = false;
    static ushort      _chipId   = 0;
    static string      _chipName = "";
    static ushort      _basePort = 0;   // index port (0x2E or 0x4E)
    static ushort      _ecBase   = 0;   // HW monitor base address
    static ChipFamily  _family   = ChipFamily.None;

    enum ChipFamily { None, ITE, Nuvoton }

    // ── Public API ────────────────────────────────────────────────────────────
    public static SensorData? Read()
    {
        if (!PawnIO.Init()) return null;

        // Cache for 2 seconds
        if (_cached != null && (DateTime.UtcNow - _lastRead).TotalSeconds < 2)
            return _cached;

        if (!_probed)
        {
            _probed = true;
            if (!ProbeChip())
            {
                LHMBridge.DbgLog("[SuperIO] No supported chip found");
                return null;
            }
        }

        if (_family == ChipFamily.None) return null;

        var data = new SensorData { ChipName = _chipName, ChipId = _chipId };

        switch (_family)
        {
            case ChipFamily.ITE:     ReadITE(data); break;
            case ChipFamily.Nuvoton: ReadNuvoton(data); break;
        }

        _cached = data;
        _lastRead = DateTime.UtcNow;
        return data;
    }

    // ── Chip probing ──────────────────────────────────────────────────────────
    static bool ProbeChip()
    {
        // Try both standard SuperIO port pairs
        foreach (ushort port in new ushort[] { 0x2E, 0x4E })
        {
            // Try ITE first
            if (TryITE(port)) return true;
            // Then Nuvoton/Winbond/Fintek (same enter sequence)
            if (TryNuvoton(port)) return true;
        }
        return false;
    }

    // ── ITE IT87xx detection ──────────────────────────────────────────────────
    static bool TryITE(ushort port)
    {
        try
        {
            ushort data = (ushort)(port + 1);

            // Enter ITE extended function mode
            WriteByte(port, 0x87);
            WriteByte(port, 0x01);
            WriteByte(port, 0x55);
            WriteByte(port, port == 0x2E ? (byte)0x55 : (byte)0xAA);

            // Read chip ID
            WriteByte(port, 0x20);
            byte idHi = ReadByte(data);
            WriteByte(port, 0x21);
            byte idLo = ReadByte(data);
            ushort id = (ushort)((idHi << 8) | idLo);

            // Exit extended mode
            WriteByte(port, 0x02);
            WriteByte(data, 0x02);

            string? name = id switch
            {
                0x8613 => "ITE IT8613E",
                0x8620 => "ITE IT8620E",
                0x8625 => "ITE IT8625E",
                0x8628 => "ITE IT8628E",
                0x8655 => "ITE IT8655E",
                0x8665 => "ITE IT8665E",
                0x8686 => "ITE IT8686E",
                0x8688 => "ITE IT8688E",
                0x8689 => "ITE IT8689E",
                0x8695 => "ITE IT8695E",
                0x8721 => "ITE IT8721F",
                0x8726 => "ITE IT8726F",
                0x8728 => "ITE IT8728F",
                0x8771 => "ITE IT8771E",
                0x8772 => "ITE IT8772E",
                _ => null,
            };
            if (name == null)
            {
                if (idHi == 0x87) // IT87xx family but unknown model
                    LHMBridge.DbgLog($"[SuperIO] Unknown ITE chip 0x{id:X4} on port 0x{port:X}");
                return false;
            }

            // Re-enter extended mode to read EC base address
            WriteByte(port, 0x87);
            WriteByte(port, 0x01);
            WriteByte(port, 0x55);
            WriteByte(port, port == 0x2E ? (byte)0x55 : (byte)0xAA);

            // Select Environment Controller LDN (0x04 for IT87xx)
            WriteByte(port, 0x07);
            WriteByte(data, 0x04);

            // Read base address
            WriteByte(port, 0x60);
            byte baseHi = ReadByte(data);
            WriteByte(port, 0x61);
            byte baseLo = ReadByte(data);
            ushort ecBase = (ushort)((baseHi << 8) | baseLo);

            // Check if EC is activated
            WriteByte(port, 0x30);
            byte active = ReadByte(data);

            // Exit extended mode
            WriteByte(port, 0x02);
            WriteByte(data, 0x02);

            if (ecBase == 0 || ecBase == 0xFFFF)
            {
                LHMBridge.DbgLog($"[SuperIO] {name}: EC base invalid (0x{ecBase:X})");
                return false;
            }

            _chipId   = id;
            _chipName = name;
            _basePort = port;
            _ecBase   = ecBase;
            _family   = ChipFamily.ITE;
            LHMBridge.DbgLog($"[SuperIO] Found {name} (0x{id:X4}) on port 0x{port:X}, EC base=0x{ecBase:X}, active={active}");
            return true;
        }
        catch (Exception ex)
        {
            LHMBridge.DbgLog($"[SuperIO] ITE probe failed on 0x{port:X}: {ex.Message}");
            return false;
        }
    }

    // ── Nuvoton NCT67xx detection ─────────────────────────────────────────────
    static bool TryNuvoton(ushort port)
    {
        try
        {
            ushort data = (ushort)(port + 1);

            // Enter Winbond/Nuvoton extended function mode
            WriteByte(port, 0x87);
            WriteByte(port, 0x87);

            // Read chip ID
            WriteByte(port, 0x20);
            byte idHi = ReadByte(data);
            WriteByte(port, 0x21);
            byte idLo = ReadByte(data);
            ushort id = (ushort)((idHi << 8) | idLo);

            string? name = id switch
            {
                0xB470 => "Nuvoton NCT6775F",
                0xC330 => "Nuvoton NCT6776F",
                0xC560 => "Nuvoton NCT6779D",
                0xC803 => "Nuvoton NCT6791D",
                0xC911 => "Nuvoton NCT6792D",
                0xD121 => "Nuvoton NCT6795D",
                0xD352 or 0xD354 => "Nuvoton NCT6796D",
                0xD451 or 0xD452 => "Nuvoton NCT6797D",
                0xD428 => "Nuvoton NCT6798D",
                0xD802 => "Nuvoton NCT6799D",
                _ => null,
            };

            if (name == null)
            {
                // Exit extended mode before returning
                WriteByte(port, 0xAA);
                if (idHi is 0xB4 or 0xC3 or 0xC5 or 0xC8 or 0xC9 or 0xD1 or 0xD3 or 0xD4 or 0xD8)
                    LHMBridge.DbgLog($"[SuperIO] Unknown Nuvoton chip 0x{id:X4} on port 0x{port:X}");
                return false;
            }

            // Select HW Monitor LDN (0x0B for NCT67xx)
            WriteByte(port, 0x07);
            WriteByte(data, 0x0B);

            // Read base address
            WriteByte(port, 0x60);
            byte baseHi = ReadByte(data);
            WriteByte(port, 0x61);
            byte baseLo = ReadByte(data);
            ushort ecBase = (ushort)((baseHi << 8) | baseLo);

            // Exit extended mode
            WriteByte(port, 0xAA);

            if (ecBase == 0 || ecBase == 0xFFFF)
            {
                LHMBridge.DbgLog($"[SuperIO] {name}: EC base invalid (0x{ecBase:X})");
                return false;
            }

            _chipId   = id;
            _chipName = name;
            _basePort = port;
            _ecBase   = ecBase;
            _family   = ChipFamily.Nuvoton;
            LHMBridge.DbgLog($"[SuperIO] Found {name} (0x{id:X4}) on port 0x{port:X}, EC base=0x{ecBase:X}");
            return true;
        }
        catch (Exception ex)
        {
            LHMBridge.DbgLog($"[SuperIO] Nuvoton probe failed on 0x{port:X}: {ex.Message}");
            return false;
        }
    }

    // ── ITE IT87xx sensor reading ─────────────────────────────────────────────
    static void ReadITE(SensorData data)
    {
        ushort b = _ecBase;

        // Fan tachometer registers — 16-bit counter, RPM = 1350000 / count
        // Fan 1: ext=base+0x18, low=base+0x0D
        // Fan 2: ext=base+0x19, low=base+0x0E
        // Fan 3: ext=base+0x1A, low=base+0x0F
        // Fan 4: ext=base+0x80, low=base+0x81  (IT8686E+)
        // Fan 5: ext=base+0x82, low=base+0x83  (IT8686E+)
        (string name, ushort extOff, ushort lowOff)[] fanRegs = {
            ("Fan 1", 0x18, 0x0D),
            ("Fan 2", 0x19, 0x0E),
            ("Fan 3", 0x1A, 0x0F),
        };

        // Extended fan registers for newer chips
        bool hasExtFans = _chipId is 0x8686 or 0x8688 or 0x8689 or 0x8695
            or 0x8625 or 0x8628 or 0x8655 or 0x8665;
        if (hasExtFans)
        {
            fanRegs = new[] {
                ("Fan 1", (ushort)0x18, (ushort)0x0D),
                ("Fan 2", (ushort)0x19, (ushort)0x0E),
                ("Fan 3", (ushort)0x1A, (ushort)0x0F),
                ("Fan 4", (ushort)0x80, (ushort)0x81),
                ("Fan 5", (ushort)0x82, (ushort)0x83),
            };
        }

        foreach (var (name, extOff, lowOff) in fanRegs)
        {
            byte ext = ReadEC(b, extOff);
            byte low = ReadEC(b, lowOff);
            int count = (ext << 8) | low;
            int rpm = (count > 0 && count < 0xFFFF) ? 1350000 / count : 0;
            data.Fans.Add(new FanReading(name, rpm));
        }

        // Temperature registers — direct Celsius readings
        // Temp 1: base+0x29 (CPU), Temp 2: base+0x2A (System), Temp 3: base+0x2B
        (string name, ushort offset)[] tempRegs = {
            ("Temperature 1", 0x29),
            ("Temperature 2", 0x2A),
            ("Temperature 3", 0x2B),
        };

        foreach (var (name, offset) in tempRegs)
        {
            byte val = ReadEC(b, offset);
            if (val > 0 && val < 127) // valid range
                data.Temps.Add(new TempReading(name, val));
        }

        LHMBridge.DbgLog($"[SuperIO] ITE read: {data.Fans.Count} fans, {data.Temps.Count} temps");
    }

    // ── Nuvoton NCT67xx sensor reading ────────────────────────────────────────
    static void ReadNuvoton(SensorData data)
    {
        ushort b = _ecBase;

        // Nuvoton uses banked register access via port+5 (bank) and port+6 (index)
        // Fan RPM registers (16-bit, direct RPM value):
        //   Bank 4: FAN1=0xC0/0xC1, FAN2=0xC2/0xC3, FAN3=0xC4/0xC5,
        //           FAN4=0xC6/0xC7, FAN5=0xC8/0xC9
        (string name, byte hiReg, byte loReg)[] fanRegs = {
            ("Fan 1", 0xC0, 0xC1),
            ("Fan 2", 0xC2, 0xC3),
            ("Fan 3", 0xC4, 0xC5),
            ("Fan 4", 0xC6, 0xC7),
            ("Fan 5", 0xC8, 0xC9),
        };

        foreach (var (name, hiReg, loReg) in fanRegs)
        {
            byte hi = ReadNctBank(b, 4, hiReg);
            byte lo = ReadNctBank(b, 4, loReg);
            int count = (hi << 8) | lo;
            // Nuvoton stores actual RPM in some models, or count requiring conversion
            // For NCT6775+, the register contains a tachometer count
            // RPM = 1350000 / count (same formula as ITE for tach mode)
            int rpm;
            if (count == 0 || count == 0xFFFF)
                rpm = 0;
            else if (count > 10000) // looks like a tach count, not RPM
                rpm = 1350000 / count;
            else
                rpm = count; // already RPM
            data.Fans.Add(new FanReading(name, rpm));
        }

        // Temperature registers — Bank 0/1/2, various offsets
        // SYSTIN: Bank 0, Reg 0x27; CPUTIN: Bank 0, Reg 0x73; AUXTIN0: Bank 0, Reg 0x75
        (string name, byte bank, byte reg)[] tempRegs = {
            ("SYSTIN",  0, 0x27),
            ("CPUTIN",  0, 0x73),
            ("AUXTIN0", 0, 0x75),
            ("AUXTIN1", 0, 0x77),
            ("AUXTIN2", 0, 0x79),
        };

        foreach (var (name, bank, reg) in tempRegs)
        {
            byte val = ReadNctBank(b, bank, reg);
            if (val > 0 && val < 127)
                data.Temps.Add(new TempReading(name, val));
        }

        LHMBridge.DbgLog($"[SuperIO] Nuvoton read: {data.Fans.Count} fans, {data.Temps.Count} temps");
    }

    // ── I/O helpers ───────────────────────────────────────────────────────────
    static byte ReadByte(uint port)
        => PawnIO.IoInByte(port) ?? 0;

    static void WriteByte(uint port, byte val)
        => PawnIO.IoOutByte(port, val);

    // ITE EC register read: write offset to base+5, read from base+6
    static byte ReadEC(ushort ecBase, ushort offset)
    {
        PawnIO.IoOutByte((uint)(ecBase + 5), (byte)(offset & 0xFF));
        return PawnIO.IoInByte((uint)(ecBase + 6)) ?? 0;
    }

    // Nuvoton banked register read:
    // NCT67xx uses ISA-style indexed I/O with a bank select register.
    // Bank select: write bank number to (ecBase + 0x4E) 
    // Then standard index/data: write reg to (ecBase + 0x05), read (ecBase + 0x06)
    static byte ReadNctBank(ushort ecBase, byte bank, byte reg)
    {
        // Select bank
        PawnIO.IoOutByte((uint)(ecBase + 0x4E), bank);
        // Read via index/data
        PawnIO.IoOutByte((uint)(ecBase + 0x05), reg);
        return PawnIO.IoInByte((uint)(ecBase + 0x06)) ?? 0;
    }
}
