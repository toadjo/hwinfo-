// ════════════════════════════════════════════════════════════════════════════
// PawnIO.cs — Shared PawnIO connection manager for HardwareToad
//
// Provides I/O port (byte/dword) and PCI config access via PawnIO as a
// fallback when WinRing0 is unavailable (HVCI, Secure Boot, AV blocking).
//
// Used by: MemoryTimings (RAM timing reads)
//          SuperIOReader  (fan/temp/voltage when LHM SuperIO fails)
//          Ring0 shim     (PCI config fallback)
//
// Module: MchbarIO.amx — must be recompiled after adding byte I/O IOCTLs:
//   pawncc MchbarIO.p -i"include" -o MchbarIO.amx
// ════════════════════════════════════════════════════════════════════════════

using System;
using System.IO;
using System.Runtime.InteropServices;

static class PawnIO
{
    // ── PawnIOLib P/Invoke ────────────────────────────────────────────────────
    const string DLL = "PawnIOLib";

    static PawnIO()
    {
        var exeDir = AppDomain.CurrentDomain.BaseDirectory;
        var dllPath = Path.Combine(exeDir, "PawnIOLib.dll");
        if (File.Exists(dllPath))
        {
            SetDllDirectory(exeDir);
        }
        else if (File.Exists(@"C:\Program Files\PawnIO\PawnIOLib.dll"))
        {
            SetDllDirectory(@"C:\Program Files\PawnIO");
        }
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool SetDllDirectory(string lpPathName);

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

    // ── State ─────────────────────────────────────────────────────────────────
    static IntPtr _handle = IntPtr.Zero;
    static bool   _ready  = false;
    static bool   _tried  = false;
    static bool   _hasByteIo = false; // true if module supports ioctl_io_in_byte
    static readonly object _lock = new();

    static string[] GetModulePaths() => new[] {
        Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "MchbarIO.amx"),
        Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "..", "MchbarIO.amx"),
        @"C:\Program Files\PawnIO\Modules\MchbarIO.amx",
        @"C:\ProgramData\PawnIO\Modules\MchbarIO.amx",
        @"C:\Program Files\PawnIO\MchbarIO.amx",
    };

    public static bool IsReady { get { lock (_lock) return _ready; } }
    public static bool HasByteIo { get { lock (_lock) return _hasByteIo; } }

    public static bool Init()
    {
        lock (_lock)
        {
            if (_tried) return _ready;
            _tried = true;

            var dllPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "PawnIOLib.dll");
            if (!File.Exists(dllPath))
                dllPath = @"C:\Program Files\PawnIO\PawnIOLib.dll";
            if (!File.Exists(dllPath))
            {
                LHMBridge.DbgLog($"[PawnIO] PawnIOLib.dll not found (checked exe dir + Program Files)");
                return false;
            }

            string? mod = null;
            LHMBridge.DbgLog("[PawnIO] Searching for MchbarIO.amx:");
            foreach (var p in GetModulePaths())
            {
                LHMBridge.DbgLog($"  - {p}");
                if (File.Exists(p) && mod == null) mod = p;
            }

            if (mod == null)
            {
                LHMBridge.DbgLog("[PawnIO] MchbarIO.amx not found — install PawnIO or place module next to exe");
                return false;
            }

            try
            {
                int r = pawnio_open(out _handle);
                if (r != 0 || _handle == IntPtr.Zero)
                {
                    LHMBridge.DbgLog($"[PawnIO] pawnio_open failed: 0x{r:X}");
                    return false;
                }

                byte[] blob = File.ReadAllBytes(mod);
                r = pawnio_load(_handle, blob, (UIntPtr)blob.Length);
                if (r != 0)
                {
                    LHMBridge.DbgLog($"[PawnIO] pawnio_load failed: 0x{r:X}");
                    pawnio_close(_handle); _handle = IntPtr.Zero;
                    return false;
                }

                LHMBridge.DbgLog($"[PawnIO] Module loaded ({mod})");
                _ready = true;

                // Probe for byte I/O support (new module has it, old module doesn't)
                var probe = Exec("ioctl_io_in_byte", new ulong[] { 0x80 /* safe dummy port */ });
                _hasByteIo = probe != null;
                LHMBridge.DbgLog($"[PawnIO] Byte I/O support: {_hasByteIo}");

                return true;
            }
            catch (Exception ex)
            {
                LHMBridge.DbgLog($"[PawnIO] Init exception: {ex.Message}");
                return false;
            }
        }
    }

    // ── Execute IOCTL ─────────────────────────────────────────────────────────
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
            if (r != 0) return null;
            return outBuf;
        }
        catch { return null; }
    }

    // ── Dword I/O ─────────────────────────────────────────────────────────────
    public static uint? IoInDword(uint port)
    {
        var r = Exec("ioctl_io_in_dword", new ulong[] { port });
        return r == null ? null : (uint)r[0];
    }

    public static void IoOutDword(uint port, uint val)
        => Exec("ioctl_io_out_dword", new ulong[] { port, val }, 0);

    // ── Byte I/O (for SuperIO chip access) ────────────────────────────────────
    // Requires updated MchbarIO.amx with byte IOCTLs.
    // Falls back to dword read + mask if byte IOCTLs not available.
    public static byte? IoInByte(uint port)
    {
        if (_hasByteIo)
        {
            var r = Exec("ioctl_io_in_byte", new ulong[] { port });
            if (r != null) return (byte)(r[0] & 0xFF);
        }
        // Fallback: dword read, mask low byte
        // Works on most x86 systems for ISA/LPC ports
        var d = Exec("ioctl_io_in_dword", new ulong[] { port });
        return d == null ? null : (byte)(d[0] & 0xFF);
    }

    public static void IoOutByte(uint port, byte val)
    {
        if (_hasByteIo)
        {
            Exec("ioctl_io_out_byte", new ulong[] { port, val }, 0);
            return;
        }
        // Fallback: write as dword with upper bytes zeroed
        Exec("ioctl_io_out_dword", new ulong[] { port, (ulong)val }, 0);
    }

    // ── PCI config ────────────────────────────────────────────────────────────
    public static uint? PciRead(uint bus, uint dev, uint fn, uint reg)
    {
        var r = Exec("ioctl_pci_read", new ulong[] { bus, dev, fn, reg });
        return r == null ? null : (uint)r[0];
    }

    public static void PciWrite(uint bus, uint dev, uint fn, uint reg, uint val)
    {
        uint addr = 0x80000000u | (bus << 16) | (dev << 11) | (fn << 8) | (reg & 0xFCu);
        IoOutDword(0xCF8, addr);
        IoOutDword(0xCFC, val);
    }
}
