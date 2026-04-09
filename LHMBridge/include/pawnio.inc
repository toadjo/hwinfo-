// pawnio.inc — PawnIO native declarations for HardwareToad
// Compatible with standard Pawn compiler (pawncc from CompuPhase)

// ── Tags ─────────────────────────────────────────────────────────────────────
#if !defined NTSTATUS
  #define NTSTATUS: _:
#endif

// ── Status codes ─────────────────────────────────────────────────────────────
const STATUS_SUCCESS         = 0;
const STATUS_NOT_SUPPORTED   = 0xC00000BB;

#define NT_SUCCESS(%1) ((%1) == STATUS_SUCCESS)

// ── Architecture ─────────────────────────────────────────────────────────────
const ARCH_X86 = 0;
const ARCH_X64 = 1;

// ── Native functions ─────────────────────────────────────────────────────────
native get_arch();

// PCI config
native NTSTATUS:pci_config_read_dword(bus, dev, func, reg, &value);

// I/O port — dword (32-bit)
native io_in_dword(port);
native io_out_dword(port, value);

// I/O port — byte (8-bit)
native io_in_byte(port);
native io_out_byte(port, value);

// ── IOCTL definition macro ───────────────────────────────────────────────────
// DEFINE_IOCTL_SIZED(name, in_count, out_count)
// Expands to: public name(in[], out[])
// The caller sizes are checked by the PawnIO runtime.
#define DEFINE_IOCTL_SIZED(%1,%2,%3) \
    public %1(in[], out[])
