// MchbarIO.p — PawnIO module for HardwareToad
// Exposes PCI config read and I/O port read/write (byte + dword) as IOCTLs
// Compile: pawncc MchbarIO.p -i"include" -o MchbarIO.amx

#include <pawnio>

// ── IOCTL: Read PCI config dword ─────────────────────────────────────────────
// in[0] = bus, in[1] = dev, in[2] = func, in[3] = reg
// out[0] = value
DEFINE_IOCTL_SIZED(ioctl_pci_read, 4, 1)
{
    new value;
    new NTSTATUS:status = pci_config_read_dword(in[0], in[1], in[2], in[3], value);
    if (!NT_SUCCESS(status))
        return status;
    out[0] = value;
    return STATUS_SUCCESS;
}

// ── IOCTL: Write I/O port dword ──────────────────────────────────────────────
// in[0] = port, in[1] = value
DEFINE_IOCTL_SIZED(ioctl_io_out_dword, 2, 0)
{
    io_out_dword(in[0], in[1]);
    return STATUS_SUCCESS;
}

// ── IOCTL: Read I/O port dword ───────────────────────────────────────────────
// in[0] = port
// out[0] = value
DEFINE_IOCTL_SIZED(ioctl_io_in_dword, 1, 1)
{
    out[0] = io_in_dword(in[0]);
    return STATUS_SUCCESS;
}

// ── IOCTL: Write I/O port byte ───────────────────────────────────────────────
// in[0] = port, in[1] = value (low 8 bits)
// Used by SuperIO chip access (ports 0x2E/0x2F, 0x4E/0x4F)
DEFINE_IOCTL_SIZED(ioctl_io_out_byte, 2, 0)
{
    io_out_byte(in[0], in[1]);
    return STATUS_SUCCESS;
}

// ── IOCTL: Read I/O port byte ────────────────────────────────────────────────
// in[0] = port
// out[0] = value (8-bit, zero-extended)
DEFINE_IOCTL_SIZED(ioctl_io_in_byte, 1, 1)
{
    out[0] = io_in_byte(in[0]);
    return STATUS_SUCCESS;
}

NTSTATUS:main()
{
    if (get_arch() != ARCH_X64)
        return STATUS_NOT_SUPPORTED;
    return STATUS_SUCCESS;
}
