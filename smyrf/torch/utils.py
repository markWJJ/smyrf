''' Utility functions for smyrf '''
import torch
import torch.nn.functional as F
from collections import defaultdict, Counter
import numpy as np
from tqdm import tqdm
import random


def get_achlioptas(dim, device='cuda'):
    arr = torch.empty(dim, dim, device=device)
    for i in range(dim):
        for j in range(dim):
            p = random.random()
            if p <= 1/6:
                arr[i][j] = -1
            elif p <= 2/3:
                arr[i][j] = 0
            else:
                arr[i][j] = 1
    return arr


def pop_many(old_list, indexes):
    ''' Remove a set of indexes (consistently) from a list '''
    # Create an empty new list
    new_list = []
    # Counter on the indices list
    j = 0

    for i, x in enumerate(old_list):
        if j == len(indexes) or i != indexes[j]:
            new_list.append(x)
        elif i == indexes[j]:
            j += 1
    return new_list

class QItem:
    def __init__(self, index, q_hash):
        self.index = index
        self.q_hash = q_hash

    def __eq__(self, other):
        return isinstance(other, type(self)), self.index == other.index

    def __hash__(self):
        return self.q_hash + self.index

    def __str__(self):
        return 'Q' + str(self.index)

    def __repr__(self):
        return 'Q' + str(self.index)


class KItem:
    def __init__(self, index, k_hash):
        self.index = index
        self.k_hash = k_hash

    def __eq__(self, other):
        return isinstance(other, type(self)), self.index == other.index

    def __hash__(self):
        return self.k_hash + self.index

    def __str__(self):
        return 'K' + str(self.index)

    def __repr__(self):
        return 'K' + str(self.index)


def collect_buckets(q_hashes, k_hashes):
    '''
        q_hashes, k_hashes: (N, L) (unique)
    '''
    N = q_hashes.shape[0]

    q_buckets = defaultdict(lambda: set())
    k_buckets = defaultdict(lambda: set())

    for i in tqdm(range(N)):
        q_h_list = [x.item() for x in q_hashes[i]]
        k_h_list = [x.item() for x in k_hashes[i]]

        q_set = Counter(q_h_list)
        k_set = Counter(k_h_list)

        for q_val in q_set.keys():
            q_item = QItem(i, N)
            q_buckets[q_val].add(q_item)


        for k_val in k_set.keys():
            k_item = KItem(i, N)
            k_buckets[k_val].add(k_item)

    to_pop = []

    for key in q_buckets:
        # only keys
        if not key in k_buckets:
            to_pop.append(key)

    for key in k_buckets:
        if not key in q_buckets:
            to_pop.append(key)

    for key in to_pop:
        try:
            del q_buckets[key]
        except:
            pass

        try:
            del k_buckets[key]
        except:
            pass

    return q_buckets, k_buckets



def random_flip(x):
    flips = torch.ceil((torch.rand(x.shape, device=x.device) - 0.5)).to(torch.uint8)
    return flips * x

def sign_randomness(fn):
    def do(*args, **kwargs):
        return random_flip(fn(*args, **kwargs))
    return do


@sign_randomness
def hadamard_transform(u, normalize=False):
    batch_size, n = u.shape
    m = int(np.log2(n))
    assert n == 1 << m, 'n must be a power of 2'
    x = u[..., np.newaxis]
    for d in range(m)[::-1]:
        x = torch.cat((x[..., ::2, :] + x[..., 1::2, :], x[..., ::2, :] - x[..., 1::2, :]), dim=-1)
    return x.squeeze(-2) / 2**(m / 2) if normalize else x.squeeze(-2)


def inversion_number(arr1, arr2):
    '''
        Counts "relative" mistakes.
    '''
    mapping = {}
    count = 0
    not_found = 0

    for i, elem in enumerate(arr2):
        mapping[elem] = i

    for i, elem_a in enumerate(arr1):
        if not elem_a in mapping:
            not_found += 1
            count += len(arr1[i+1:])
            continue

        for elem_b in arr1[i+1:]:
            mapped_a = mapping[elem_a]
            if not elem_b in mapping:
                count += 1
                continue
            mapped_b = mapping[elem_b]
            if mapped_a > mapped_b:
                count += 1
    return count, not_found


def two_dimensional(fn):
    def do(self, x, *args, **kwargs):
        if len(x.shape) == 2:
            return fn(self, x, *args, **kwargs)
        else:
            x = x.reshape(-1, x.shape[-1])
            return fn(self, x, *args, **kwargs)
    return do


def sort_key_val(t1, t2, dim=-1, n_buckets=1):
    '''
        Sort t2 based on t1.
    '''
    values, indices = t1.sort(dim=dim)
    t2 = t2.expand_as(t1)
    return values, t2.gather(dim, indices)


def uniform(a, b, shape, device='cuda'):
    '''
        Draws shape samples from a uniform distribution U(a, b).

    '''
    return (b - a) * torch.rand(shape, device=device) + a


def batched_index_select(values, indices):
    last_dim = values.shape[-1]
    return values.gather(1, indices[:, :, None].expand(-1, -1, last_dim))


def max_neg_value(tensor):
    '''
        Returns -infty
    '''
    return -torch.finfo(tensor.dtype).max



'''                   Preprocessing functions for ALSH                      '''
class AsymmetricTransform:
    def Q(self, *args, **kwargs):
        raise NotImplementedError('Query transform not implemented')

    def K(self, *args, **kwargs):
        raise NotImplementedError('Key transform not implemented')


class L2LSH(AsymmetricTransform):
    def K(self, vec):
        # Normalize x = vec / max_norm
        norms = vec.norm(p=2, dim=-1).unsqueeze(-1)
        max_norm = torch.max(norms, dim=0)[0]
        x = vec / max_norm

        # compute new_norms
        norms = x.norm(p=2,dim=-1).unsqueeze(-1)

        # transform: x = [x; norm_x**2, norm_x**4]
        return torch.cat((x, norms**2, norms**4, norms**8), -1)

    def Q(self, vec):
        # normalize queries
        x = (vec - vec.mean(dim=-1).unsqueeze(-1)) / vec.std(dim=-1).unsqueeze(-1)
        device = vec.device
        ext = torch.empty(x.shape[:-1] + (1,), device=device).fill_(0.5)
        return torch.cat((x, ext, ext, ext), -1)


class XBOX(AsymmetricTransform):
    def K(self, x):
        norms = x.norm(p=2, dim=-1).unsqueeze(-1)
        max_norm = torch.max(norms, dim=0)[0]
        ext = torch.sqrt(max_norm**2 - norms**2)
        return torch.cat((x, ext), -1)

    def Q(self, x):
        zero = torch.tensor([0.0], device=x.device).repeat(x.shape[0], 1)
        return torch.cat((x, zero), -1)


class H2LSH(AsymmetricTransform):
    '''
        "Advanced" xbox for queries. Technique: H2-ALSH.
        Based on paper: Accurate and Fast ALSH (KDD 2018)
    '''

    def K(self, x):
        norms = x.norm(p=2, dim=-1).unsqueeze(-1)
        max_norm = torch.max(norms, dim=0)[0]
        self.max_norm = max_norm
        ext = torch.sqrt(max_norm**2 - norms**2)
        return torch.cat((x, ext), -1)


    def Q(self, x):
        assert hasattr(self, 'max_norm'), 'Max norm not set'
        zero = torch.tensor([0.0], device=x.device).repeat(x.shape[0], 1)
        res = torch.cat((self.max_norm * x, zero), -1)
        del self.max_norm
        return res



'''                              Hashing                                     '''

class LSH:
    def __call__(self, *args, **kwargs):
        raise NotImplementedError('LSH scheme not implemented')

    def compute_hash_agreement(self, q_hash, k_hash):
        return (q_hash == k_hash).min(dim=-1)[0].sum(dim=-1)



class VoronoiLSH(LSH):
    def __init__(self, L, K, dim, device='cuda'):
        '''
            We repeat L times the following process.
            Choose K gaussians. Compute the inner product, keep the index of
            the maximum.

            L: increases the probability of collision for near ones.
            K: decreases the probability of collision for far ones.

            Suggested values:
                -> K = ln(N) / ln(2)
                -> L = sqrt(N)
        '''
        self.gaussians = torch.randn(dim, K * L, device=device)
        self.K = K
        self.L = L
        self.dim = dim

    def __call__(self, vecs):
        products = vecs @ self.gaussians
        return torch.argmax(products.reshape(-1, self.L, self.K), dim=-1)


class CrossPolytopeLSH(LSH):
    def __init__(self, L, K, dim, device='cuda'):
        self.L = L
        self.K = K
        self.dim = dim

    def __call__(self, vecs):
        x = vecs.repeat([self.L * self.K, 1])
        x = hadamard_transform(x, normalize=True)
        x = hadamard_transform(x)
        x = x.reshape(self.L, self.K, -1, vecs.shape[-1])
        indices = torch.argmax(x, dim=-1).permute(2, 0, 1)
        return indices

class E2LSH(LSH):
    def __init__(self, L, K, dim, r=9, device='cuda'):
        super(E2LSH, self).__init__()
        self.alpha = torch.normal(0, 1, (dim, L * K), device=device)
        self.beta = uniform(0, r, shape=(L * K,), device=device)
        self.L = L
        self.K = K
        self.dim = dim
        self.r = r

    @two_dimensional
    def __call__(self, vecs):
        '''
            L2 Sensitive Hashing based on p-stable distributions.
            Also known as E2LSH.

            Args:
                vecs: (bs * N, dim) (dtype: torch.float32)
            Output:
                buckets: (bs * N, n_hashes) (dtype: torch.int32)
        '''
        projection = vecs @ self.alpha
        projection_shift = projection + self.beta
        projection_shift_rescale = projection_shift / self.r
        return projection_shift_rescale.to(torch.long).reshape(-1, self.L, self.K)


class QLSH(LSH):
    def __init__(self, L, K, dim, r=4, device='cuda'):
        self.alpha = torch.normal(0, 1, (dim, L * K), device=device)
        self.dim = dim
        self.L = L
        self.K = K
        self.r = r

    @two_dimensional
    def __call__(self, queries, keys):
        q_projection = (queries @ self.alpha).reshape(-1, self.L, self.K)
        k_projection = (keys @ self.alpha).reshape(-1, self.L, self.K)

        return self.compute_hash_agreement(q_projection, k_projection)

    def compute_hash_agreement(self, q_projection, k_projection):
        diff = k_projection - q_projection
        left_part = diff >= (- self.r / 2)
        right_part = diff <= (self.r / 2)
        truth_table = (left_part * right_part).min(dim=-1)[0].sum(dim=-1)
        return truth_table
