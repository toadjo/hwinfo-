/*
 * stress_native.c
 * Tight FMA loop — compiled at runtime, called via ctypes (GIL-free)
 * Each function runs until *stop_flag != 0
 */
#include <math.h>
#include <stdint.h>

/* ── Small FFT proxy: tight FP64 FMA loop, fits in L1/L2 ─────────────── */
void burn_small_fft(volatile int *stop_flag, double *score_out) {
    double a = 1.00000001, b = 1.00000002, c = 1.00000003, d = 1.00000004;
    double e = 0.99999999, f = 0.99999998, g = 0.99999997, h = 0.99999996;
    unsigned long long iters = 0;
    while (!(*stop_flag)) {
        /* 8 independent FMA chains — maximises IPC and FP throughput */
        a = a * 1.0000001 + 0.0000001;
        b = b * 1.0000002 + 0.0000002;
        c = c * 1.0000003 + 0.0000003;
        d = d * 1.0000004 + 0.0000004;
        e = e * 0.9999999 + 0.0000001;
        f = f * 0.9999998 + 0.0000002;
        g = g * 0.9999997 + 0.0000003;
        h = h * 0.9999996 + 0.0000004;
        /* Periodic renorm to prevent denormals */
        if (iters % 1000000 == 0) {
            a = fabs(a) < 1e-100 ? 1.0 : (fabs(a) > 1e100 ? 1.0 : a);
            b = fabs(b) < 1e-100 ? 1.0 : (fabs(b) > 1e100 ? 1.0 : b);
            c = fabs(c) < 1e-100 ? 1.0 : (fabs(c) > 1e100 ? 1.0 : c);
            d = fabs(d) < 1e-100 ? 1.0 : (fabs(d) > 1e100 ? 1.0 : d);
            e = fabs(e) < 1e-100 ? 1.0 : (fabs(e) > 1e100 ? 1.0 : e);
            f = fabs(f) < 1e-100 ? 1.0 : (fabs(f) > 1e100 ? 1.0 : f);
            g = fabs(g) < 1e-100 ? 1.0 : (fabs(g) > 1e100 ? 1.0 : g);
            h = fabs(h) < 1e-100 ? 1.0 : (fabs(h) > 1e100 ? 1.0 : h);
        }
        iters++;
    }
    *score_out = (double)iters;
}

/* ── Large FFT proxy: same FMA but with cache-busting memory access ───── */
void burn_large_fft(volatile int *stop_flag, double *buf, int buf_len, double *score_out) {
    double acc = 1.0;
    unsigned long long iters = 0;
    int idx = 0;
    while (!(*stop_flag)) {
        /* FMA chain */
        acc = acc * 1.0000001 + buf[idx];
        buf[idx] = acc;
        idx = (idx + 127) % buf_len;   /* stride access — busts cache */
        /* Secondary FMA burst */
        double x = acc;
        x = x*1.1+0.1; x = x*1.1+0.1; x = x*1.1+0.1; x = x*1.1+0.1;
        x = x*0.9-0.1; x = x*0.9-0.1; x = x*0.9-0.1; x = x*0.9-0.1;
        acc += x * 1e-30;  /* prevent optimizer removal */
        if (iters % 500000 == 0) {
            acc = fabs(acc) > 1e100 ? 1.0 : acc;
        }
        iters++;
    }
    *score_out = (double)iters;
}

/* ── Blend: FMA + large sequential memory sweep ──────────────────────── */
void burn_blend(volatile int *stop_flag, double *buf, int buf_len, double *score_out) {
    double a = 1.0, b = 2.0, c = 3.0, d = 4.0;
    unsigned long long iters = 0;
    int idx = 0;
    while (!(*stop_flag)) {
        /* FMA burst */
        a = a * 1.0000001 + 0.0000001;
        b = b * 1.0000002 + 0.0000002;
        c = c * 1.0000003 + 0.0000003;
        d = d * 1.0000004 + 0.0000004;
        /* Sequential memory sweep — stresses memory controller */
        buf[idx] = a + b + c + d;
        idx = (idx + 1) % buf_len;
        if (iters % 500000 == 0) {
            a = fabs(a) > 1e100 ? 1.0 : a;
            b = fabs(b) > 1e100 ? 2.0 : b;
            c = fabs(c) > 1e100 ? 3.0 : c;
            d = fabs(d) > 1e100 ? 4.0 : d;
        }
        iters++;
    }
    *score_out = (double)iters;
}
