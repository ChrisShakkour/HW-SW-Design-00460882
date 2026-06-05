// =============================================================================
// conv1x1_opt.cpp  --  OPTIMIZED 1x1 convolution (pointwise convolution)
//
// Same math, same inputs, same output as conv1x1_naive.cpp:
//
//     out[co][h][w] = sum_ci  in[ci][h][w] * weight[co][ci]
//
// WHAT CHANGED (and the hardware insight behind it)
//   1. DATA LAYOUT  NCHW -> NHWC.
//      We transpose the input so that, for a fixed pixel, the Cin channel
//      values are CONTIGUOUS in memory. Now the reduction over `ci` is a unit-
//      stride sweep: the HW prefetcher streams it, every cache line is fully
//      used, and the compiler can auto-vectorize the dot product (SSE/AVX FMA).
//      The weight row weight[co][*] is also contiguous over ci.
//
//   2. REGISTER BLOCKING over output channels (4 at a time).
//      Each input pixel value `x` is loaded once and reused across 4 output
//      channels held in registers. This raises arithmetic intensity (more FLOPs
//      per byte loaded) and keeps the FMA units busy -> higher IPC.
//
// The reduction is, per pixel, a [1 x Cin] . [Cin x Cout] product -- i.e. the
// whole op is a cache- and SIMD-friendly GEMM. This is exactly how real NN
// inference engines / accelerators lay out pointwise convolutions.
//
// Build with the SAME flags as the naive version (-O3 -march=native): the win
// here comes from layout + blocking, not from compiler flags.
// =============================================================================

#include <cstdio>
#include <cstdint>
#include <vector>
#include <chrono>

// -----------------------------------------------------------------------------
// Compile-time switch for terminal prints.
//   Default ON. Disable for clean perf runs / output diffing with:  -DVERBOSE=0
// -----------------------------------------------------------------------------
#ifndef VERBOSE
#define VERBOSE 1
#endif
#if VERBOSE
#define LOG(...) std::printf(__VA_ARGS__)
#else
#define LOG(...) ((void)0)
#endif

// -----------------------------------------------------------------------------
// Problem dimensions -- MUST match conv1x1_naive.cpp.
// -----------------------------------------------------------------------------
#ifndef CIN
#define CIN 512
#endif
#ifndef COUT
#define COUT 512
#endif
#ifndef DIM_H
#define DIM_H 128
#endif
#ifndef DIM_W
#define DIM_W 128
#endif
constexpr int Cin  = CIN;
constexpr int Cout = COUT;
constexpr int H    = DIM_H;
constexpr int W    = DIM_W;
constexpr int HW   = H * W;

static_assert(Cout % 4 == 0, "register blocking assumes Cout is a multiple of 4");

// Identical deterministic generator -> identical inputs as the naive build.
static inline float det_val(uint32_t idx) {
    uint32_t x = idx * 2654435761u + 12345u;
    x ^= x >> 13; x *= 0x5bd1e995u; x ^= x >> 15;
    return (static_cast<float>(x & 0xFFFFu) / 32768.0f) - 1.0f;  // in [-1, 1)
}

int main() {
    LOG("[opt] 1x1 conv  Cin=%d Cout=%d H=%d W=%d  (%lld MACs)\n",
        Cin, Cout, H, W, (long long)Cout * Cin * HW);

    // Weights are [Cout][Cin] (row = one output channel, contiguous over ci).
    std::vector<float> wt(static_cast<size_t>(Cout) * Cin);

    // NHWC tensors: index = pixel * channels + channel.
    std::vector<float> in_nhwc(static_cast<size_t>(HW) * Cin);
    std::vector<float> out_nhwc(static_cast<size_t>(HW) * Cout, 0.0f);

    // ---- Deterministic init -------------------------------------------------
    // Inputs are generated from the SAME canonical NCHW index as the naive
    // build, then transposed into NHWC. Logical values are therefore identical.
    LOG("[opt] initializing inputs (NCHW canonical -> NHWC)...\n");
    for (int ci = 0; ci < Cin; ++ci) {
        for (int p = 0; p < HW; ++p) {
            uint32_t canonical = static_cast<uint32_t>(ci) * HW + p;  // NCHW index
            in_nhwc[(size_t)p * Cin + ci] = det_val(canonical);
        }
    }
    for (size_t i = 0; i < wt.size(); ++i) wt[i] = det_val(static_cast<uint32_t>(i) + 0x9000000u);

    // ---- Compute ------------------------------------------------------------
    LOG("[opt] computing...\n");
    auto t0 = std::chrono::high_resolution_clock::now();

    for (int p = 0; p < HW; ++p) {
        const float* xin = &in_nhwc[(size_t)p * Cin];          // Cin contiguous floats
        for (int co = 0; co < Cout; co += 4) {
            const float* w0 = &wt[(size_t)(co + 0) * Cin];
            const float* w1 = &wt[(size_t)(co + 1) * Cin];
            const float* w2 = &wt[(size_t)(co + 2) * Cin];
            const float* w3 = &wt[(size_t)(co + 3) * Cin];
            float a0 = 0.f, a1 = 0.f, a2 = 0.f, a3 = 0.f;
            // Unit-stride, vectorizable reduction; `x` reused across 4 channels.
            for (int ci = 0; ci < Cin; ++ci) {
                float x = xin[ci];
                a0 += x * w0[ci];
                a1 += x * w1[ci];
                a2 += x * w2[ci];
                a3 += x * w3[ci];
            }
            float* o = &out_nhwc[(size_t)p * Cout + co];
            o[0] = a0; o[1] = a1; o[2] = a2; o[3] = a3;
        }
    }

    auto t1 = std::chrono::high_resolution_clock::now();
    double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

    // ---- Layout-independent checksum (must match the naive build exactly) ----
    // Logical out[co][h][w] lives at out_nhwc[(h*W+w)*Cout + co].
    double sum = 0.0;
    for (int co = 0; co < Cout; ++co)
        for (int p = 0; p < HW; ++p)
            sum += out_nhwc[(size_t)p * Cout + co];

    float s_first = out_nhwc[(size_t)0 * Cout + 0];                       // [0][0][0]
    float s_last  = out_nhwc[(size_t)(HW - 1) * Cout + (Cout - 1)];       // [Cout-1][H-1][W-1]

    std::fprintf(stderr, "[opt] compute time: %.3f ms\n", ms);
    std::printf("RESULT checksum=%.6f  sample[0][0][0]=%.6f sample[Cout-1][H-1][W-1]=%.6f\n",
                sum, s_first, s_last);
    return 0;
}
