// =============================================================================
// conv1x1_naive.cpp  --  UNOPTIMIZED 1x1 convolution (pointwise convolution)
//
// A 1x1 convolution maps an input feature map [Cin, H, W] to an output feature
// map [Cout, H, W] using a weight tensor [Cout, Cin]. Mathematically it is a
// per-pixel matrix-vector product (and over all pixels, a matrix multiply):
//
//     out[co][h][w] = sum_ci  in[ci][h][w] * weight[co][ci]
//
// WHY THIS IS THE "NAIVE" VERSION
//   * Data is stored in NCHW layout (channel-major). The reduction loop runs
//     over the input channel `ci`, but consecutive `ci` values are H*W floats
//     apart in memory. So the hot inner loop strides through memory with a huge
//     stride -> almost every load is a cache miss, the HW prefetcher cannot
//     help, and SIMD units sit idle.
//   * No reuse of the loaded input pixel across output channels.
//
// Build with the SAME flags as the optimized version so the measured speedup is
// attributable to the data layout / cache behaviour, not to compiler flags.
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
// Problem dimensions (a realistic mid-network pointwise-conv shape).
//   Cin = Cout = 256, spatial 64x64  ->  256*256*64*64 ~= 268M MACs.
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

// Deterministic value generator so the naive and optimized builds see EXACTLY
// the same inputs (and therefore must produce the same output).
static inline float det_val(uint32_t idx) {
    uint32_t x = idx * 2654435761u + 12345u;
    x ^= x >> 13; x *= 0x5bd1e995u; x ^= x >> 15;
    return (static_cast<float>(x & 0xFFFFu) / 32768.0f) - 1.0f;  // in [-1, 1)
}

int main() {
    LOG("[naive] 1x1 conv  Cin=%d Cout=%d H=%d W=%d  (%lld MACs)\n",
        Cin, Cout, H, W, (long long)Cout * Cin * HW);

    // ---- Allocate tensors (NCHW for input/output, [Cout][Cin] for weights) --
    std::vector<float> in(static_cast<size_t>(Cin) * HW);
    std::vector<float> wt(static_cast<size_t>(Cout) * Cin);
    std::vector<float> out(static_cast<size_t>(Cout) * HW, 0.0f);

    // ---- Deterministic initialization (canonical NCHW index for input) ------
    LOG("[naive] initializing inputs...\n");
    for (size_t i = 0; i < in.size(); ++i) in[i] = det_val(static_cast<uint32_t>(i));
    for (size_t i = 0; i < wt.size(); ++i) wt[i] = det_val(static_cast<uint32_t>(i) + 0x9000000u);

    // ---- Compute -------------------------------------------------------------
    LOG("[naive] computing...\n");
    auto t0 = std::chrono::high_resolution_clock::now();

    for (int co = 0; co < Cout; ++co) {
        for (int h = 0; h < H; ++h) {
            for (int w = 0; w < W; ++w) {
                float acc = 0.0f;
                // Reduction over input channels: in[ci*HW + h*W + w] strides by
                // HW (=4096 floats = 16 KB) every iteration -> cache-miss storm.
                for (int ci = 0; ci < Cin; ++ci) {
                    acc += in[(size_t)ci * HW + h * W + w] * wt[(size_t)co * Cin + ci];
                }
                out[(size_t)co * HW + h * W + w] = acc;
            }
        }
    }

    auto t1 = std::chrono::high_resolution_clock::now();
    double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

    // ---- Layout-independent checksum (identical across both versions) --------
    double sum = 0.0;
    for (int co = 0; co < Cout; ++co)
        for (int p = 0; p < HW; ++p)
            sum += out[(size_t)co * HW + p];

    // Timing -> stderr so it never pollutes the diffable stdout output.
    std::fprintf(stderr, "[naive] compute time: %.3f ms\n", ms);

    // Result -> stdout, always printed, stable across runs => safe to diff.
    std::printf("RESULT checksum=%.6f  sample[0][0][0]=%.6f sample[Cout-1][H-1][W-1]=%.6f\n",
                sum, out[0], out[(size_t)(Cout - 1) * HW + (H - 1) * W + (W - 1)]);
    return 0;
}
