from smyrf.torch.attn import RandomBucketsAttention, dense, AsymmetricLSHAttention
import unittest
from profilehooks import timecall
import torch


class Profiler(unittest.TestCase):
    def test_cuda_seq_benchmark(self):
        benchmark_trials = 10
        q_seqlen = 1024
        k_seqlen = 1024
        dim = 100
        v_dim = 100

        bs = 1
        q_bucket_size = 32
        k_bucket_size = 32
        n_hashes = 32

        queries = torch.normal(0, 1, (benchmark_trials, 1, q_seqlen, dim), device='cuda')
        keys = torch.normal(0, 1, (benchmark_trials, 1, k_seqlen, dim), device='cuda')
        values = torch.normal(0, 1, (benchmark_trials, 1, k_seqlen, v_dim), device='cuda')

        random_attn = RandomBucketsAttention(q_seqlen,
                                             k_seqlen,
                                             q_bucket_size=q_bucket_size,
                                             k_bucket_size=k_bucket_size,
                                             n_hashes=n_hashes,
                                             max_perms=bs)
        alsh_attn = AsymmetricLSHAttention(q_bucket_size=q_bucket_size,
                                           k_bucket_size=k_bucket_size,
                                           n_hashes=n_hashes)
        @timecall
        def time_profile(layer, *inputs):
            return layer(*inputs)

        for i in range(benchmark_trials):
            inputs = [queries[i], keys[i], values[i]]
            q_rand = time_profile(random_attn, *inputs)
            q_dense = time_profile(dense, *inputs)
            q_alsh = time_profile(alsh_attn, *inputs)


if __name__ == '__main__':
    unittest.main()